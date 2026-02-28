# MemoryFileSystem (MFS) 詳細実装設計書 (DetailedDesignSpec)

本書は `spec_v12.md` を実装者向けに具体化した詳細設計書である。クラス定義・アルゴリズム・擬似コード・エラーハンドリング網羅表を含み、これ単体で実装に着手可能なレベルの情報を提供する。

> **ドキュメント位置づけ（重要）**: 本書には設計意図を残すための履歴的な擬似コード・解説が含まれる。実装との相違が生じた場合は、`spec_v12.md` と実コード（`dmemfs/*.py`）を正とする。

> **v10 更新**: ディレクトリインデックス層（`DirNode`/`FileNode`）の導入、`glob("**")` 対応、`copy_tree()` / `move()` API追加、`wb` truncate 順序修正、`walk()` スレッドセーフティ注記、`export_as_bytesio()` ロック粒度改善、`__del__` stacklevel修正。**全項目実装済み。**

> **v11 更新**: Phase 3 設計。ファイルタイムスタンプ（`created_at`/`modified_at`）と `stat()` API、`bytearray` shrink 機構、PEP 703 対応設計、`AsyncMemoryFileSystem` / `AsyncMemoryFileHandle` ラッパー。**全項目実装済み。**

> **v12 更新**: Opus評価レポート（v3）フィードバック反映。`_NoOpQuotaManager` 削除、`AsyncMemoryFileSystem` の `__getattr__` 遅延インポート、`_force_reserve()` 使用制約の明記、`copy()` API仕様の補完、`get_size()`/`listdir()` のロック保護、`walk()`/`glob()` のGILフリースナップショット安全性。**全項目実装済み。**

---

## 1. モジュール構成

```
dmemfs/
├── __init__.py               # 公開APIの re-export + __getattr__ 遅延インポート
├── _exceptions.py            # MFSQuotaExceededError 定義
├── _lock.py                  # ReadWriteLock 実装
├── _quota.py                 # QuotaManager (reserve / release / _force_reserve)
├── _file.py                  # IMemoryFile, SequentialMemoryFile, RandomAccessMemoryFile
├── _handle.py                # MemoryFileHandle
├── _fs.py                    # MemoryFileSystem (公開API本体) + DirNode / FileNode
├── _typing.py                # MFSStats, MFSStatResult (TypedDict)
├── _path.py                  # パス正規化ユーティリティ
└── _async.py                 # AsyncMemoryFileSystem / AsyncMemoryFileHandle
```

### 公開インターフェース（`__init__.py`）

```python
from typing import TYPE_CHECKING

from ._fs import MemoryFileSystem
from ._handle import MemoryFileHandle
from ._exceptions import MFSQuotaExceededError
from ._typing import MFSStats, MFSStatResult

if TYPE_CHECKING:
    from ._async import AsyncMemoryFileSystem, AsyncMemoryFileHandle


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in ("AsyncMemoryFileSystem", "AsyncMemoryFileHandle"):
        from ._async import AsyncMemoryFileSystem, AsyncMemoryFileHandle

        globals()["AsyncMemoryFileSystem"] = AsyncMemoryFileSystem
        globals()["AsyncMemoryFileHandle"] = AsyncMemoryFileHandle
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MemoryFileSystem",
    "MemoryFileHandle",
    "MFSQuotaExceededError",
    "MFSStats",
    "MFSStatResult",
    "AsyncMemoryFileSystem",
    "AsyncMemoryFileHandle",
]
__version__ = "0.2.0"
```

> **v12 設計判断**: `AsyncMemoryFileSystem` は `__getattr__` + `TYPE_CHECKING` ガードにより遅延インポートを実現する（spec_v12.md §6.4 準拠）。`asyncio` 未使用環境でのインポートコスト増を回避しつつ、`isinstance()` チェック、IDE補完、`help()` が正常に動作する。

---

## 2. 例外定義（`_exceptions.py`）

```python
class MFSQuotaExceededError(OSError):
    """クォータ上限超過時に送出される。OSError のサブクラス。"""
    def __init__(self, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            f"MFS quota exceeded: requested {requested} bytes, "
            f"only {available} bytes available."
        )
```

---

## 3. 型定義（`_typing.py`）

```python
from typing import TypedDict

class MFSStats(TypedDict):
    used_bytes: int               # クォータ計上済み総バイト数（実データ＋OH推定含む）
    quota_bytes: int              # 設定された最大クォータ
    free_bytes: int               # 残余クォータ（quota_bytes - used_bytes）
    file_count: int               # ファイルエントリ数
    dir_count: int                # ディレクトリエントリ数
    chunk_count: int              # SequentialMemoryFile の全チャンク総数
    overhead_per_chunk_estimate: int  # 環境キャリブレーション済みのチャンクあたりOH推定値


class MFSStatResult(TypedDict):
    size: int                     # ファイルサイズ（バイト数）
    created_at: float             # 作成日時（time.time() の戻り値と同形式）
    modified_at: float            # 最終更新日時
    generation: int               # 変更検知用世代ID
    is_dir: bool                  # True: ディレクトリ, False: ファイル [v13: is_sequential から変更]
```

`stats() -> MFSStats` の返却型に使用する。`stat() -> MFSStatResult` は個別ファイル情報の返却型。実装は `TypedDict` のサブクラスでなく単純な `dict` でよいが、型ヒントとして使うことで型チェッカー・IDEの補完が効く。

---

## 4. ReadWriteLock 実装（`_lock.py`）

### 設計原則
- `threading.Condition` を内部実装に使用。
- 複数スレッドの同時 Read を許容し、Write は完全排他。
- `lock_timeout` パラメータで無期限ブロッキング / タイムアウト / try-lock を切り替える。
- Write ロック取得時は「現在の Read 数がゼロかつ Write が保持されていない」まで待機する。

### 実装スケルトン

```python
import threading
import time


def _calc_deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    if timeout == 0.0:
        return 0.0
    return time.monotonic() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    r = deadline - time.monotonic()
    return max(0.0, r)


class ReadWriteLock:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._read_count: int = 0
        self._write_held: bool = False

    # ── Read ロック ─────────────────────────────────────────────────
    def acquire_read(self, timeout: float | None = None) -> None:
        """
        読み取りロックを取得する。
        - timeout=None  : 無期限ブロッキング
        - timeout=0.0   : try-lock（即座に失敗 → BlockingIOError）
        - timeout=正数  : 指定秒数まで待機 → タイムアウトで BlockingIOError
        """
        deadline = _calc_deadline(timeout)
        with self._condition:
            while self._write_held:
                remaining = _remaining(deadline)
                if remaining == 0.0:
                    raise BlockingIOError("Could not acquire read lock within timeout.")
                if not self._condition.wait(timeout=remaining):
                    raise BlockingIOError("Could not acquire read lock within timeout.")
            self._read_count += 1

    def release_read(self) -> None:
        with self._condition:
            self._read_count -= 1
            if self._read_count == 0:
                self._condition.notify_all()

    # ── Write ロック ────────────────────────────────────────────────
    def acquire_write(self, timeout: float | None = None) -> None:
        """
        書き込みロックを取得する。
        既存のすべての Read ロックおよび Write ロックが解放されるまで待機。
        """
        deadline = _calc_deadline(timeout)
        with self._condition:
            while self._write_held or self._read_count > 0:
                remaining = _remaining(deadline)
                if remaining == 0.0:
                    raise BlockingIOError("Could not acquire write lock within timeout.")
                if not self._condition.wait(timeout=remaining):
                    raise BlockingIOError("Could not acquire write lock within timeout.")
            self._write_held = True

    def release_write(self) -> None:
        with self._condition:
            self._write_held = False
            self._condition.notify_all()

    # ── 状態確認 ────────────────────────────────────────────────────
    @property
    def is_locked(self) -> bool:
        """Read または Write ロックが1つでも保持されているか。"""
        with self._condition:
            return self._write_held or self._read_count > 0
```

### ロック取得の順序規約（デッドロック防止）

全実装を通じて、**`_global_lock` (FS全体 `threading.RLock`) → `_quota._lock` (QuotaManager 内部) → `FileNode._rw_lock` (ファイル単位 `ReadWriteLock`) の順**でロックを取得することを厳守する。逆順の取得を行ってはならない。

---

## 5. クォータマネージャ（`_quota.py`）

### `QuotaManager`

```python
from contextlib import contextmanager
import threading
from ._exceptions import MFSQuotaExceededError


class QuotaManager:
    def __init__(self, max_quota: int) -> None:
        self._max_quota: int = max_quota
        self._used: int = 0
        self._lock: threading.Lock = threading.Lock()

    @contextmanager
    def reserve(self, size: int):
        """
        size バイトのクォータを予約するコンテキストマネージャ。
        - with ブロック突入時: 上限チェック → 超過なら MFSQuotaExceededError
        - 正常終了: 予約を確定（ロールバック不要）
        - 例外終了: 予約を解放（ロールバック）
        """
        if size <= 0:
            yield
            return
        with self._lock:
            available = self._max_quota - self._used
            if size > available:
                raise MFSQuotaExceededError(requested=size, available=available)
            self._used += size
        try:
            yield
        except BaseException:
            with self._lock:
                self._used -= size
            raise

    def release(self, size: int) -> None:
        """削除・縮小時にクォータを即時返却する。"""
        if size <= 0:
            return
        with self._lock:
            self._used = max(0, self._used - size)

    def _force_reserve(self, size: int) -> None:
        """
        内部専用: 上限チェックを行わずに _used を加算する。
        import_tree / copy_tree での事前チェック後の一括加算に使用。

        使用条件（v12 制約）:
        1. _global_lock 保持下でのみ呼び出し可能
        2. 呼び出し前に free との比較によるクォータ事前チェックが完了していること
        3. 使用箇所: import_tree() および copy_tree() のみ
        """
        if size <= 0:
            return
        with self._lock:
            self._used += size

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def free(self) -> int:
        with self._lock:
            return self._max_quota - self._used

    @property
    def maximum(self) -> int:
        return self._max_quota
```

---

## 6. 内部ストレージ層（`_file.py`）

### 6.1 チャンクオーバーヘッドのキャリブレーション

```python
import sys

def _calibrate_chunk_overhead(safety_mul: float = 1.5, safety_add: int = 32) -> int:
    """
    現在のPythonランタイムにおける bytes チャンクの管理オーバーヘッドを推定する。
    理論値: bytes オブジェクト本体 + list エントリのポインタ
    安全マージンを乗じた推定値を返す（過大計上は許容）。
    """
    empty_bytes_size = sys.getsizeof(b"")
    list_ptr_size = sys.getsizeof([None]) - sys.getsizeof([])
    raw = empty_bytes_size + list_ptr_size
    return int(raw * safety_mul) + safety_add

# モジュールロード時にキャリブレーションを実行
CHUNK_OVERHEAD_ESTIMATE: int = _calibrate_chunk_overhead()
```

このキャリブレーション値は `MemoryFileSystem` の初期化時に引数で上書き可能とする（`chunk_overhead_override: int | None = None`）。

### 6.2 `IMemoryFile`（インターフェース）

v10 で `is_dir`・`generation`・`_rw_lock` は `DirNode`/`FileNode` に移管された。`IMemoryFile` は純粋なデータストレージ抽象である。

```python
from abc import ABC, abstractmethod

class IMemoryFile(ABC):
    """Abstract base for file data storage.

    In v10+, metadata (is_dir, generation, _rw_lock) has been moved to
    DirNode/FileNode.  IMemoryFile is now pure data storage.
    """

    @abstractmethod
    def read_at(self, offset: int, size: int) -> bytes: ...

    @abstractmethod
    def write_at(
        self, offset: int, data: bytes, quota_mgr
    ) -> "tuple[int, RandomAccessMemoryFile | None, int]":
        """
        データを書き込む。クォータ予約はこのメソッド内で行う。
        Sequential で末尾以外のオフセット指定時は自動昇格を発火する。
        戻り値: (書き込んだバイト数, 昇格先ファイルまたはNone, 旧データサイズ)
        """
        ...

    @abstractmethod
    def truncate(self, size: int, quota_mgr) -> None: ...

    @abstractmethod
    def get_size(self) -> int: ...

    @abstractmethod
    def get_quota_usage(self) -> int:
        """クォータ計算に使用する現在のメモリ使用量を返す。"""
        ...
```

### 6.3 `SequentialMemoryFile`

```python
import bisect

class SequentialMemoryFile(IMemoryFile):
    """
    list[bytes] を内部バッファとして持つ追記特化型実装。
    末尾以外へのランダムアクセス書き込み時に RandomAccessMemoryFile へ自動昇格する。
    _cumulative 配列による O(log N) チャンク読み取りを実装。
    """
    PROMOTION_HARD_LIMIT: int = 512 * 1024 * 1024  # 512MB（昇格時の上限）

    def __init__(self, chunk_overhead: int = CHUNK_OVERHEAD_ESTIMATE) -> None:
        super().__init__()
        self._chunks: list[bytes] = []
        self._cumulative: list[int] = []
        self._size: int = 0
        self._chunk_overhead: int = chunk_overhead

    def get_size(self) -> int:
        return self._size

    def get_quota_usage(self) -> int:
        return self._size + len(self._chunks) * self._chunk_overhead

    def read_at(self, offset: int, size: int) -> bytes:
        """bisect_right で対象チャンクを高速特定。O(log N + data_size)。"""
        if offset >= self._size or size == 0:
            return b""
        end = self._size if size < 0 else min(offset + size, self._size)
        start_idx = bisect.bisect_right(self._cumulative, offset)
        result = bytearray()
        for i in range(start_idx, len(self._chunks)):
            chunk_file_start = self._cumulative[i - 1] if i > 0 else 0
            chunk_file_end = self._cumulative[i]
            lo = max(offset, chunk_file_start) - chunk_file_start
            hi = min(end, chunk_file_end) - chunk_file_start
            result.extend(self._chunks[i][lo:hi])
            if chunk_file_end >= end:
                break
        return bytes(result)

    def write_at(self, offset: int, data: bytes, quota_mgr
    ) -> "tuple[int, RandomAccessMemoryFile | None, int]":
        if offset != self._size:
            # 末尾以外への書き込み → 自動昇格
            return self._promote_and_write(offset, data, quota_mgr)
        n = len(data)
        if n == 0:
            return 0, None, 0
        overhead = self._chunk_overhead
        with quota_mgr.reserve(n + overhead):
            self._chunks.append(data)
            self._size += n
            self._cumulative.append(self._size)
        return n, None, 0

    def truncate(self, size: int, quota_mgr) -> None:
        if size >= self._size:
            return
        # 縮小: 全チャンク結合後スライスして再構築
        data = b"".join(self._chunks)[:size]
        old_overhead = len(self._chunks) * self._chunk_overhead
        self._chunks = [data] if data else []
        self._cumulative = [size] if data else []
        new_overhead = len(self._chunks) * self._chunk_overhead
        release_bytes = (self._size - size) + (old_overhead - new_overhead)
        quota_mgr.release(release_bytes)
        self._size = size

    def _promote_and_write(self, offset: int, data: bytes, quota_mgr
    ) -> "tuple[int, RandomAccessMemoryFile, int]":
        """
        SequentialMemoryFile → RandomAccessMemoryFile への昇格フロー。
          1. ハードリミット判定
          2. 二重クォータ予約（現サイズ分）
          3. bytearray へのディープコピー
          4. 旧バッファオーバーヘッド分を解放
          5. 昇格先で書き込み実行
          6. 呼び出し元に (written, promoted, old_data_size) を返却
        """
        current_size = self._size
        if current_size > self.PROMOTION_HARD_LIMIT:
            raise io.UnsupportedOperation(
                f"Cannot promote SequentialMemoryFile: size {current_size} "
                f"exceeds hard limit {self.PROMOTION_HARD_LIMIT}."
            )
        # 予約（コピーのための一時的な 2倍確保）
        with quota_mgr.reserve(current_size):
            new_buf = bytearray(b"".join(self._chunks))
        # 旧バッファのオーバーヘッド分を解放
        old_overhead = len(self._chunks) * self._chunk_overhead
        quota_mgr.release(old_overhead)
        # RandomAccess に昇格して書き込み
        promoted = RandomAccessMemoryFile.from_bytearray(new_buf)
        written, _, _ = promoted.write_at(offset, data, quota_mgr)
        return written, promoted, current_size
```

### 6.4 `RandomAccessMemoryFile`

```python
class RandomAccessMemoryFile(IMemoryFile):
    """bytearray を内部バッファとして持つランダムアクセス対応型実装。"""

    SHRINK_THRESHOLD: float = 0.25  # [v11] バッファ容量の 25% 以下に縮小した場合に shrink

    def __init__(self, initial_data: bytes = b"") -> None:
        super().__init__()
        self._buf: bytearray = bytearray(initial_data)

    @classmethod
    def from_bytearray(cls, buf: bytearray) -> "RandomAccessMemoryFile":
        obj = cls.__new__(cls)
        IMemoryFile.__init__(obj)
        obj._buf = buf
        return obj

    def get_size(self) -> int:
        return len(self._buf)

    def get_quota_usage(self) -> int:
        return len(self._buf)

    def read_at(self, offset: int, size: int) -> bytes:
        if size < 0:
            return bytes(self._buf[offset:])
        return bytes(self._buf[offset: offset + size])

    def write_at(self, offset: int, data: bytes, quota_mgr
    ) -> "tuple[int, None, int]":
        n = len(data)
        if n == 0:
            return 0, None, 0
        current_len = len(self._buf)
        new_size = max(current_len, offset + n)
        extend = new_size - current_len
        if extend > 0:
            with quota_mgr.reserve(extend):
                if offset > current_len:
                    self._buf.extend(bytes(offset - current_len))  # ゼロ埋め
                    self._buf.extend(data)
                else:
                    overlap = current_len - offset
                    self._buf[offset:current_len] = data[:overlap]
                    self._buf.extend(data[overlap:])
        else:
            self._buf[offset: offset + n] = data
        return n, None, 0

    def truncate(self, size: int, quota_mgr) -> None:
        old_size = len(self._buf)
        if size >= old_size:
            return
        release = old_size - size
        del self._buf[size:]
        # [v11] shrink 判定: 新サイズが旧容量の 25% 以下なら再割り当て
        if old_size > 0 and size <= old_size * self.SHRINK_THRESHOLD:
            self._buf = bytearray(self._buf)  # 新バッファにコピー → 旧バッファを GC 回収
        quota_mgr.release(release)
```

---

## 7. ディレクトリインデックス層 (Directory Index Layer)

v10 で導入。ファイルの実体データ（IMemoryFile）とディレクトリ構造（メタデータツリー）を分離する。`_fs.py` 内に定義。

### 7.1 ノード定義

```python
import time
from ._lock import ReadWriteLock
from ._file import IMemoryFile


class DirNode:
    """ディレクトリを表すメタデータノード。子エントリ名 → NodeId のマッピングのみ保持。"""
    __slots__ = ("node_id", "children")

    def __init__(self, node_id: int) -> None:
        self.node_id: int = node_id
        self.children: dict[str, int] = {}


class FileNode:
    """ファイルを表すメタデータノード。ストレージ参照・RWロック・変更検知ID・タイムスタンプを保持。"""
    __slots__ = ("node_id", "storage", "_rw_lock", "generation",
                 "created_at", "modified_at")

    def __init__(self, node_id: int, storage: IMemoryFile) -> None:
        self.node_id: int = node_id
        self.storage: IMemoryFile = storage
        self._rw_lock: ReadWriteLock = ReadWriteLock()
        self.generation: int = 0
        now = time.time()
        self.created_at: float = now     # [v11] ファイル作成日時
        self.modified_at: float = now    # [v11] 最終更新日時


Node = DirNode | FileNode
```

### 7.2 IMemoryFile からの移管フィールド

| フィールド | v9 での所在 | v10+ での所在 |
|---|---|---|
| `is_dir: bool` | `IMemoryFile` | `DirNode` / `FileNode` の型で判別 |
| `generation: int` | `IMemoryFile` | `FileNode.generation` |
| `_rw_lock: ReadWriteLock` | `IMemoryFile` | `FileNode._rw_lock` |
| `created_at: float` | なし | `FileNode.created_at` [v11] |
| `modified_at: float` | なし | `FileNode.modified_at` [v11] |

### 7.3 計算量改善

| 操作 | v9 (フラット辞書) | v10+ (ディレクトリインデックス) |
|---|---|---|
| `listdir(path)` | $O(N)$ — 全キーのプレフィックススキャン | $O(\text{children\_count})$ — `DirNode.children` の直接参照 |
| `exists(path)` | $O(1)$ — 辞書ルックアップ | $O(d)$ — パス深度 $d$ でのツリー走査 |
| `rename(src, dst)` (ファイル) | $O(1)$ | $O(d)$ — 親ノードの `children` 更新 |
| `rename(src, dst)` (ディレクトリ) | $O(N)$ — 配下全キー書き換え | $O(d)$ — 親ノードの `children` 更新のみ |
| `walk(path)` | $O(N)$ — 毎階層でプレフィックススキャン | $O(\text{subtree\_size})$ — ツリー走査 |
| `glob(pattern)` | $O(N)$ — 全キーマッチング | $O(\text{subtree\_size})$ — ツリー走査 |
| `rmtree(path)` | $O(N)$ — プレフィックスでフィルタ | $O(\text{subtree\_size})$ — サブツリー走査 |

> $N$: FS全体のエントリ数、$d$: パスの深度（平均的に小さい定数）、$\text{children\_count}$: 直下の子ノード数、$\text{subtree\_size}$: サブツリー内のノード数

---

## 8. MemoryFileHandle（`_handle.py`）

```python
from __future__ import annotations
import io
import time
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._fs import MemoryFileSystem, FileNode


class MemoryFileHandle:
    def __init__(
        self,
        mfs: MemoryFileSystem,
        fnode: FileNode,
        path: str,
        mode: str,
        is_append: bool = False,
    ) -> None:
        self._mfs = mfs        # MFS への強参照（GC防止）
        self._fnode = fnode     # FileNode への参照
        self._path = path       # 正規化済みパス
        self._mode = mode
        self._cursor: int = fnode.storage.get_size() if is_append else 0
        self._is_closed: bool = False
        self._is_append: bool = is_append

    # ── モード判定ヘルパー ─────────────────────────────────────────
    def _assert_readable(self) -> None:
        if self._mode in ("wb", "ab", "xb"):
            raise io.UnsupportedOperation(f"not readable in mode '{self._mode}'")

    def _assert_writable(self) -> None:
        if self._mode == "rb":
            raise io.UnsupportedOperation(f"not writable in mode '{self._mode}'")

    def _assert_open(self) -> None:
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

    # ── read ──────────────────────────────────────────────────────
    def read(self, size: int = -1) -> bytes:
        self._assert_open()
        self._assert_readable()
        storage = self._fnode.storage
        current_size = storage.get_size()
        if self._cursor >= current_size:
            return b""
        if size < 0:
            data = storage.read_at(self._cursor, current_size - self._cursor)
            self._cursor = current_size
        else:
            actual = min(size, current_size - self._cursor)
            data = storage.read_at(self._cursor, actual)
            self._cursor += actual
        return data

    # ── write ─────────────────────────────────────────────────────
    def write(self, data: bytes) -> int:
        self._assert_open()
        self._assert_writable()
        if self._is_append:
            # ab モード: 毎回 EOF へシーク（seek() で動かしても無効化）
            self._cursor = self._fnode.storage.get_size()
        n, promoted, old_quota = self._fnode.storage.write_at(
            self._cursor, data, self._mfs._quota
        )
        if promoted is not None:
            # SequentialMemoryFile → RandomAccessMemoryFile 昇格
            self._fnode.storage = promoted
            self._mfs._quota.release(old_quota)
        self._cursor += n
        if n > 0:
            self._fnode.generation += 1
            self._fnode.modified_at = time.time()
        return n

    # ── seek / tell ───────────────────────────────────────────────
    def seek(self, offset: int, whence: int = 0) -> int:
        self._assert_open()
        if whence == 0:    # SEEK_SET
            if offset < 0:
                raise ValueError("seek offset must be >= 0 for SEEK_SET")
            new_pos = offset
        elif whence == 1:  # SEEK_CUR
            new_pos = self._cursor + offset
        elif whence == 2:  # SEEK_END
            if offset > 0:
                raise ValueError(
                    "Seeking past end-of-file (SEEK_END with positive offset) "
                    "is not supported in MFS."
                )
            new_pos = self._fnode.storage.get_size() + offset
        else:
            raise ValueError(f"Invalid whence value: {whence}. Must be 0, 1, or 2.")
        if new_pos < 0:
            raise ValueError(f"Resulting cursor position {new_pos} is negative.")
        self._cursor = new_pos
        return self._cursor

    def tell(self) -> int:
        self._assert_open()
        return self._cursor

    # ── close / context manager ───────────────────────────────────
    def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        mode = self._mode
        if mode in ("wb", "ab", "r+b", "xb"):
            self._fnode._rw_lock.release_write()
        else:
            self._fnode._rw_lock.release_read()

    def __enter__(self) -> MemoryFileHandle:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        if not self._is_closed:
            warnings.warn(
                "MFS MemoryFileHandle was not closed properly. "
                "Always use 'with mfs.open(...) as f:' to ensure cleanup.",
                ResourceWarning,
                stacklevel=1,  # __del__ は GC から呼ばれるため stacklevel=1 が正確
            )
            try:
                self.close()
            except Exception:
                pass  # __del__ 内での例外は抑制
```

---

## 9. パス正規化ユーティリティ（`_path.py`）

```python
import posixpath


def normalize_path(path: str) -> str:
    """
    入力パスを MFS 内部表現（POSIX 絶対パス）に正規化する。
    1. バックスラッシュをスラッシュに変換（Windows 互換）
    2. 空文字列は "/" として扱う
    3. トラバーサル検出（仮想ルートを超える遡上 → ValueError）
    4. 先頭に "/" を付与して絶対パスを保証
    5. posixpath.normpath で正規化
    """
    converted = path.replace("\\", "/")
    if not converted:
        return "/"

    # Traversal check: simulate path resolution from root (depth 0)
    parts = converted.split("/")
    depth = 0
    for part in parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                raise ValueError(f"Path traversal attempt detected: '{path}'")
        elif part and part != ".":
            depth += 1

    # Normalize: make absolute then normpath
    if not converted.startswith("/"):
        converted = "/" + converted
    normalized = posixpath.normpath(converted)
    return normalized
```

---

## 10. MemoryFileSystem（`_fs.py`）

### 10.1 クラス骨格とコンストラクタ

```python
from __future__ import annotations
import fnmatch
import io
import posixpath
import threading
import time
from typing import Iterator
from ._exceptions import MFSQuotaExceededError
from ._quota import QuotaManager
from ._file import IMemoryFile, SequentialMemoryFile, RandomAccessMemoryFile, CHUNK_OVERHEAD_ESTIMATE
from ._handle import MemoryFileHandle
from ._typing import MFSStats, MFSStatResult
from ._path import normalize_path
from ._lock import ReadWriteLock


class MemoryFileSystem:
    def __init__(
        self,
        max_quota: int = 256 * 1024 * 1024,  # デフォルト 256MB
        chunk_overhead_override: int | None = None,
    ) -> None:
        self._quota = QuotaManager(max_quota)
        self._global_lock = threading.RLock()
        self._chunk_overhead: int = (
            chunk_overhead_override
            if chunk_overhead_override is not None
            else CHUNK_OVERHEAD_ESTIMATE
        )
        self._nodes: dict[int, Node] = {}
        self._next_node_id: int = 0
        # ルートディレクトリ
        self._root = self._alloc_dir()
```

### 10.2 ノード割り当てヘルパー

```python
    def _alloc_dir(self) -> DirNode:
        """新しい DirNode を生成し _nodes に登録する。"""
        nid = self._next_node_id
        self._next_node_id += 1
        node = DirNode(nid)
        self._nodes[nid] = node
        return node

    def _alloc_file(self, storage: IMemoryFile) -> FileNode:
        """新しい FileNode を生成し _nodes に登録する。"""
        nid = self._next_node_id
        self._next_node_id += 1
        node = FileNode(nid, storage)
        self._nodes[nid] = node
        return node
```

### 10.3 パス解決ヘルパー

```python
    def _np(self, path: str) -> str:
        """正規化済みパスを返す。トラバーサル検出あり。"""
        return normalize_path(path)

    def _resolve_path(self, npath: str) -> Node | None:
        """
        正規化済みパスをツリー走査で解決し、対応するノードを返す。
        存在しない場合は None を返す。
        フルパスキャッシュは使用しない（rename/move 時の整合性問題を回避）。
        """
        if npath == "/":
            return self._root
        parts = [p for p in npath.split("/") if p]
        current: Node = self._root
        for part in parts:
            if not isinstance(current, DirNode):
                return None
            child_id = current.children.get(part)
            if child_id is None:
                return None
            current = self._nodes[child_id]
        return current

    def _resolve_parent_and_name(self, npath: str) -> tuple[DirNode, str] | None:
        """パスの親ディレクトリノードと名前コンポーネントを返す。"""
        parent_path = posixpath.dirname(npath) or "/"
        name = posixpath.basename(npath)
        parent_node = self._resolve_path(parent_path)
        if parent_node is None or not isinstance(parent_node, DirNode):
            return None
        return parent_node, name
```

### 10.4 `open()`

```python
    def open(
        self,
        path: str,
        mode: str = "rb",
        preallocate: int = 0,
        lock_timeout: float | None = None,
    ) -> MemoryFileHandle:
        valid_modes = {"rb", "wb", "ab", "r+b", "xb"}
        if mode not in valid_modes:
            raise ValueError(
                f"Invalid mode '{mode}'. MFS supports binary modes only: {valid_modes}"
            )
        npath = self._np(path)
        handle = None
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is not None and isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")

            fnode: FileNode | None = node if isinstance(node, FileNode) else None

            if mode == "rb":
                if fnode is None:
                    raise FileNotFoundError(f"No such file: '{path}'")
                fnode._rw_lock.acquire_read(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "wb":
                if fnode is None:
                    fnode = self._create_file(npath)
                    fnode._rw_lock.acquire_write(timeout=lock_timeout)
                    handle = MemoryFileHandle(self, fnode, npath, mode)
                else:
                    # 書き込みロック取得後に truncate（v10 変更: PEP 703 対応）
                    fnode._rw_lock.acquire_write(timeout=lock_timeout)
                    fnode.storage.truncate(0, self._quota)
                    fnode.generation += 1
                    fnode.modified_at = time.time()
                    handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "ab":
                if fnode is None:
                    fnode = self._create_file(npath)
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode, is_append=True)

            elif mode == "r+b":
                if fnode is None:
                    raise FileNotFoundError(f"No such file: '{path}'")
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "xb":
                if fnode is not None:
                    raise FileExistsError(f"File exists: '{path}'")
                fnode = self._create_file(npath)
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

        # preallocate 処理（ロック取得後に実行）
        if preallocate > 0 and handle is not None and fnode is not None:
            current = fnode.storage.get_size()
            if preallocate > current:
                try:
                    n, promoted, old_quota = fnode.storage.write_at(
                        current, bytes(preallocate - current), self._quota
                    )
                    if promoted is not None:
                        fnode.storage = promoted
                        self._quota.release(old_quota)
                    fnode.generation += 1
                except Exception:
                    handle.close()
                    raise

        return handle  # type: ignore[return-value]

    def _create_file(self, npath: str) -> FileNode:
        """中間ディレクトリを確認しファイルエントリを作成しノードツリーに登録する。"""
        pinfo = self._resolve_parent_and_name(npath)
        if pinfo is None:
            parent_path = posixpath.dirname(npath) or "/"
            raise FileNotFoundError(f"Parent directory does not exist: '{parent_path}'")
        parent, name = pinfo
        storage = SequentialMemoryFile(self._chunk_overhead)
        fnode = self._alloc_file(storage)
        parent.children[name] = fnode.node_id
        return fnode
```

### 10.5 `mkdir()`

```python
    def mkdir(self, path: str, exist_ok: bool = False) -> None:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is not None:
                if isinstance(node, DirNode):
                    if not exist_ok:
                        raise FileExistsError(f"Directory exists: '{path}'")
                    return
                else:
                    raise FileExistsError(f"File exists at path: '{path}'")
            self._makedirs(npath)

    def _makedirs(self, npath: str) -> None:
        """中間ディレクトリを再帰的に作成（parents=True 相当）。"""
        parts = [p for p in npath.split("/") if p]
        current = self._root
        for part in parts:
            child_id = current.children.get(part)
            if child_id is not None:
                child = self._nodes[child_id]
                if isinstance(child, DirNode):
                    current = child
                else:
                    raise FileExistsError(f"A file exists at path component: '{part}'")
            else:
                new_dir = self._alloc_dir()
                current.children[part] = new_dir.node_id
                current = new_dir
```

### 10.6 `rename()` / `move()`

```python
    def rename(self, src: str, dst: str) -> None:
        nsrc = self._np(src)
        ndst = self._np(dst)
        if nsrc == "/":
            raise ValueError("Cannot rename the root directory.")
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            dst_node = self._resolve_path(ndst)
            if dst_node is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            dst_pinfo = self._resolve_parent_and_name(ndst)
            if dst_pinfo is None:
                raise FileNotFoundError(f"Destination parent does not exist: '{dst}'")
            # オープン済みハンドルのフェイルファスト
            self._assert_no_open_handles(src_node, nsrc)
            # 親ノードの children 更新
            src_pinfo = self._resolve_parent_and_name(nsrc)
            assert src_pinfo is not None
            src_parent, src_name = src_pinfo
            dst_parent, dst_name = dst_pinfo
            del src_parent.children[src_name]
            dst_parent.children[dst_name] = src_node.node_id

    def move(self, src: str, dst: str) -> None:
        """rename() と異なり、dst の親ディレクトリが存在しない場合は中間ディレクトリを自動作成する。"""
        nsrc = self._np(src)
        ndst = self._np(dst)
        if nsrc == "/":
            raise ValueError("Cannot move the root directory.")
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            dst_node = self._resolve_path(ndst)
            if dst_node is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            self._assert_no_open_handles(src_node, nsrc)
            # dst の親ディレクトリを自動作成
            dst_parent_path = posixpath.dirname(ndst) or "/"
            if self._resolve_path(dst_parent_path) is None:
                self._makedirs(dst_parent_path)
            dst_pinfo = self._resolve_parent_and_name(ndst)
            assert dst_pinfo is not None
            src_pinfo = self._resolve_parent_and_name(nsrc)
            assert src_pinfo is not None
            src_parent, src_name = src_pinfo
            dst_parent, dst_name = dst_pinfo
            del src_parent.children[src_name]
            dst_parent.children[dst_name] = src_node.node_id

    def _assert_no_open_handles(self, node: Node, path_for_error: str) -> None:
        """ノード（およびディレクトリ配下の全ノード）にオープン済みハンドルがないことを確認。"""
        if isinstance(node, FileNode):
            if node._rw_lock.is_locked:
                raise BlockingIOError(f"File is open: '{path_for_error}'")
        elif isinstance(node, DirNode):
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                child_path = path_for_error.rstrip("/") + "/" + name
                self._assert_no_open_handles(child, child_path)
```

### 10.7 `remove()` / `rmtree()`

```python
    def remove(self, path: str) -> None:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            if node._rw_lock.is_locked:
                raise BlockingIOError(f"File is open: '{path}'")
            size = node.storage.get_quota_usage()
            pinfo = self._resolve_parent_and_name(npath)
            assert pinfo is not None
            parent, name = pinfo
            del parent.children[name]
            del self._nodes[node.node_id]
            self._quota.release(size)

    def rmtree(self, path: str) -> None:
        npath = self._np(path)
        if npath == "/":
            raise ValueError("Cannot remove the root directory.")
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such directory: '{path}'")
            if not isinstance(node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{path}'")
            self._assert_no_open_handles(node, npath)
            total_released = self._calc_subtree_quota(node)
            pinfo = self._resolve_parent_and_name(npath)
            if pinfo is not None:
                parent, name = pinfo
                del parent.children[name]
            self._remove_subtree(node)
            self._quota.release(total_released)

    def _calc_subtree_quota(self, node: Node) -> int:
        """サブツリー全体のクォータ使用量を再帰計算。"""
        total = 0
        if isinstance(node, FileNode):
            total += node.storage.get_quota_usage()
        elif isinstance(node, DirNode):
            for child_id in node.children.values():
                total += self._calc_subtree_quota(self._nodes[child_id])
        return total

    def _remove_subtree(self, node: Node) -> None:
        """サブツリーの全ノードを _nodes から除去。"""
        if isinstance(node, DirNode):
            for child_id in list(node.children.values()):
                self._remove_subtree(self._nodes[child_id])
            node.children.clear()
        if node.node_id in self._nodes:
            del self._nodes[node.node_id]
```

### 10.8 `listdir()` / `exists()` / `is_dir()` / `get_size()`

```python
    def listdir(self, path: str) -> list[str]:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such directory: '{path}'")
            if not isinstance(node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{path}'")
            return list(node.children.keys())

    def exists(self, path: str) -> bool:
        try:
            return self._resolve_path(self._np(path)) is not None
        except ValueError:
            return False

    def is_dir(self, path: str) -> bool:
        try:
            node = self._resolve_path(self._np(path))
        except ValueError:
            return False
        return node is not None and isinstance(node, DirNode)

    def get_size(self, path: str) -> int:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            return node.storage.get_size()
```

### 10.9 `stat()` / `stats()`

```python
    def stat(self, path: str) -> MFSStatResult:
        """指定パスのファイル/ディレクトリメタデータを返す。[v11 実装済み, v13 ディレクトリ対応]"""
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                return MFSStatResult(
                    size=0,
                    created_at=node.created_at,
                    modified_at=node.modified_at,
                    generation=node.generation,
                    is_dir=True,
                )
            return MFSStatResult(
                size=node.storage.get_size(),
                created_at=node.created_at,
                modified_at=node.modified_at,
                generation=node.generation,
                is_dir=False,
            )

    def stats(self) -> MFSStats:
        with self._global_lock:
            file_count = 0
            dir_count = 0
            chunk_count = 0
            for node in self._nodes.values():
                if isinstance(node, DirNode):
                    dir_count += 1
                elif isinstance(node, FileNode):
                    file_count += 1
                    if isinstance(node.storage, SequentialMemoryFile):
                        chunk_count += len(node.storage._chunks)
        return MFSStats(
            used_bytes=self._quota.used,
            quota_bytes=self._quota.maximum,
            free_bytes=self._quota.free,
            file_count=file_count,
            dir_count=dir_count,
            chunk_count=chunk_count,
            overhead_per_chunk_estimate=self._chunk_overhead,
        )
```

### 10.10 `export_as_bytesio()`

```python
    def export_as_bytesio(self, path: str, max_size: int | None = None) -> io.BytesIO:
        """
        ⚠️ 注意: 返却される BytesIO はクォータ管理外のメモリを消費する。
        MFS の OOM 保護はこの返却値には及ばない。
        """
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            fnode: FileNode = node
        fnode._rw_lock.acquire_read()
        try:
            size = fnode.storage.get_size()
            if max_size is not None and size > max_size:
                raise ValueError(f"File size {size} exceeds max_size={max_size}.")
            data = fnode.storage.read_at(0, size)
        finally:
            fnode._rw_lock.release_read()
        return io.BytesIO(data)
```

### 10.11 `export_tree()` / `iter_export_tree()`

```python
    def export_tree(self, prefix: str = "/", only_dirty: bool = False) -> dict[str, bytes]:
        return dict(self.iter_export_tree(prefix=prefix, only_dirty=only_dirty))

    def iter_export_tree(self, prefix: str = "/", only_dirty: bool = False
    ) -> Iterator[tuple[str, bytes]]:
        """
        ストリーミングエクスポート。
        整合性モデル（弱整合性）:
          - キーセット: イテレーション開始時点で確定（スナップショット）
          - データ: 各エントリの読み取り時点での最新値
          - イテレーション中に削除されたエントリはスキップ
        """
        nprefix = self._np(prefix)
        with self._global_lock:
            entries: list[tuple[str, FileNode]] = []
            self._collect_files(self._resolve_path(nprefix), nprefix, entries)
            if only_dirty:
                entries = [(p, fn) for p, fn in entries if fn.generation > 0]
        for fpath, fnode in entries:
            if fnode.node_id not in self._nodes:
                continue  # 削除済みの場合はスキップ
            fnode._rw_lock.acquire_read()
            try:
                data = fnode.storage.read_at(0, fnode.storage.get_size())
            finally:
                fnode._rw_lock.release_read()
            yield fpath, data

    def _collect_files(self, node: Node | None, current_path: str,
                       result: list[tuple[str, FileNode]]) -> None:
        """サブツリー内の全 FileNode をパスとともに収集する。"""
        if node is None:
            return
        if isinstance(node, FileNode):
            result.append((current_path, node))
        elif isinstance(node, DirNode):
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                child_path = current_path.rstrip("/") + "/" + name
                self._collect_files(child, child_path, result)
```

### 10.12 `import_tree()`

```python
    def import_tree(self, tree: dict[str, bytes]) -> None:
        """
        All-or-Nothing インポート。クォータ超過時は全体をロールバック。
        _force_reserve() を使用（v12 制約: _global_lock 保持下 + 事前チェック完了後のみ）。
        """
        if not tree:
            return
        with self._global_lock:
            normalized: dict[str, bytes] = {}
            for path, data in tree.items():
                npath = self._np(path)
                normalized[npath] = data

            # フェイルファスト: オープン済みハンドルの確認
            for npath in normalized:
                node = self._resolve_path(npath)
                if node is not None and isinstance(node, FileNode) and node._rw_lock.is_locked:
                    raise BlockingIOError(f"Cannot import: file is open: '{npath}'")

            # クォータ計算
            old_quota = 0
            old_nodes: dict[str, FileNode | None] = {}
            for npath in normalized:
                node = self._resolve_path(npath)
                if node is not None and isinstance(node, FileNode):
                    old_quota += node.storage.get_quota_usage()
                    old_nodes[npath] = node
                else:
                    old_nodes[npath] = None

            new_quota = 0
            for npath, data in normalized.items():
                if len(data) > 0:
                    new_quota += len(data) + self._chunk_overhead

            net = new_quota - old_quota
            if net > 0:
                avail = self._quota.free
                if net > avail:
                    raise MFSQuotaExceededError(requested=net, available=avail)

            if old_quota > 0:
                self._quota.release(old_quota)

            written_npaths: list[str] = []
            new_fnodes: dict[str, FileNode] = {}

            try:
                for npath, data in normalized.items():
                    self._ensure_parents(npath)
                    storage = SequentialMemoryFile(self._chunk_overhead)
                    if data:
                        storage._chunks = [data]
                        storage._size = len(data)
                        storage._cumulative = [len(data)]
                    fnode = self._alloc_file(storage)
                    fnode.generation = 0
                    pinfo = self._resolve_parent_and_name(npath)
                    assert pinfo is not None
                    parent, name = pinfo
                    old_node = old_nodes.get(npath)
                    if old_node is not None:
                        del self._nodes[old_node.node_id]
                    parent.children[name] = fnode.node_id
                    new_fnodes[npath] = fnode
                    written_npaths.append(npath)
            except Exception:
                # ロールバック
                for npath in written_npaths:
                    fn = new_fnodes.get(npath)
                    if fn is not None and fn.node_id in self._nodes:
                        del self._nodes[fn.node_id]
                    old_fn = old_nodes.get(npath)
                    pinfo = self._resolve_parent_and_name(npath)
                    if pinfo is not None:
                        parent, name = pinfo
                        if old_fn is not None:
                            self._nodes[old_fn.node_id] = old_fn
                            parent.children[name] = old_fn.node_id
                        elif name in parent.children:
                            del parent.children[name]
                if old_quota > 0:
                    self._quota._force_reserve(old_quota)
                raise

            if new_quota > 0:
                self._quota._force_reserve(new_quota)

    def _ensure_parents(self, npath: str) -> None:
        """ファイルパスの親ディレクトリが存在しない場合は自動作成する。"""
        parent_path = posixpath.dirname(npath) or "/"
        if self._resolve_path(parent_path) is None:
            self._makedirs(parent_path)
```

### 10.13 `copy()` / `copy_tree()`

```python
    def copy(self, src: str, dst: str) -> None:
        """
        ファイルの内容をバイト単位でディープコピーする。
        コピー先は新規の FileNode（新しい NodeId、新しいタイムスタンプ）として作成される。
        """
        nsrc = self._np(src)
        ndst = self._np(dst)
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file: '{src}'")
            if isinstance(src_node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{src}'")
            if self._resolve_path(ndst) is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            src_node._rw_lock.acquire_read()
            try:
                data = src_node.storage.read_at(0, src_node.storage.get_size())
            finally:
                src_node._rw_lock.release_read()
            fnode = self._create_file(ndst)
            if data:
                n, promoted, old_quota = fnode.storage.write_at(0, data, self._quota)
                if promoted is not None:
                    fnode.storage = promoted
                    self._quota.release(old_quota)
                fnode.generation += 1

    def copy_tree(self, src: str, dst: str) -> None:
        """
        ディレクトリツリー全体をディープコピーする。
        _force_reserve() を使用（v12 制約: _global_lock 保持下 + 事前チェック完了後のみ）。
        """
        nsrc = self._np(src)
        ndst = self._np(dst)
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            if not isinstance(src_node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{src}'")
            if self._resolve_path(ndst) is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            dst_pinfo = self._resolve_parent_and_name(ndst)
            if dst_pinfo is None:
                raise FileNotFoundError(f"Destination parent does not exist: '{dst}'")
            # クォータ事前チェック
            total_data = self._calc_subtree_quota(src_node)
            if total_data > 0:
                avail = self._quota.free
                if total_data > avail:
                    raise MFSQuotaExceededError(requested=total_data, available=avail)
            # ディープコピー実行
            dst_parent, dst_name = dst_pinfo
            new_root = self._deep_copy_subtree(src_node)
            dst_parent.children[dst_name] = new_root.node_id
            if total_data > 0:
                self._quota._force_reserve(total_data)

    def _deep_copy_subtree(self, node: Node) -> Node:
        """サブツリーを再帰的にディープコピーする。"""
        if isinstance(node, FileNode):
            node._rw_lock.acquire_read()
            try:
                data = node.storage.read_at(0, node.storage.get_size())
            finally:
                node._rw_lock.release_read()
            storage = SequentialMemoryFile(self._chunk_overhead)
            if data:
                storage._chunks = [data]
                storage._size = len(data)
                storage._cumulative = [len(data)]
            new_fnode = self._alloc_file(storage)
            new_fnode.generation = 0
            return new_fnode
        elif isinstance(node, DirNode):
            new_dir = self._alloc_dir()
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                new_child = self._deep_copy_subtree(child)
                new_dir.children[name] = new_child.node_id
            return new_dir
        raise TypeError(f"Unknown node type: {type(node)}")
```

### 10.14 `walk()` / `glob()`

```python
    def walk(self, path: str = "/") -> Iterator[tuple[str, list[str], list[str]]]:
        """
        ディレクトリツリーを再帰的に走査（トップダウン）。

        .. warning::
            Thread Safety (Weak Consistency):
            walk() は _global_lock をイテレーション全体では保持しない。
            各階層の子ノード一覧取得時に list() でスナップショットを取得する。
            構造変更により削除されたエントリはスキップされる（クラッシュはしない）。
        """
        npath = self._np(path)
        node = self._resolve_path(npath)
        if node is None:
            raise FileNotFoundError(f"No such directory: '{path}'")
        if not isinstance(node, DirNode):
            raise NotADirectoryError(f"Not a directory: '{path}'")
        yield from self._walk_dir(npath, node)

    def _walk_dir(self, dir_path: str, dir_node: DirNode
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        dirnames: list[str] = []
        filenames: list[str] = []
        child_dirs: list[tuple[str, DirNode]] = []
        # list() でスナップショット取得（GIL フリー環境での dict 変更対策）
        for name, child_id in list(dir_node.children.items()):
            child = self._nodes.get(child_id)
            if child is None:
                continue  # 削除済みエントリをスキップ
            if isinstance(child, DirNode):
                dirnames.append(name)
                child_dirs.append((dir_path.rstrip("/") + "/" + name, child))
            else:
                filenames.append(name)
        yield dir_path, dirnames, filenames
        for child_path, child_dir in child_dirs:
            if child_dir.node_id in self._nodes:
                yield from self._walk_dir(child_path, child_dir)

    def glob(self, pattern: str) -> list[str]:
        """
        パターンにマッチするパスのソート済みリストを返す。
        * は単一階層、** は再帰マッチ、? は任意1文字、[seq] は文字クラス。
        """
        pattern = pattern.replace("\\", "/")
        if not pattern.startswith("/"):
            pattern = "/" + pattern
        parts = [p for p in pattern.split("/") if p]
        results: list[str] = []
        self._glob_match(self._root, "/", parts, 0, results)
        return sorted(results)

    def _glob_match(self, node: Node, current_path: str,
                    parts: list[str], idx: int, results: list[str]) -> None:
        if not isinstance(node, DirNode):
            return
        if idx >= len(parts):
            return
        part = parts[idx]
        is_last = (idx == len(parts) - 1)

        if part == "**":
            # ゼロ個のディレクトリにマッチ: 次のパートへ
            if idx + 1 < len(parts):
                self._glob_match(node, current_path, parts, idx + 1, results)
            else:
                self._collect_all_paths(node, current_path, results)
            # 1個以上のディレクトリにマッチ: 子を再帰
            for name, child_id in list(node.children.items()):
                child = self._nodes.get(child_id)
                if child is None:
                    continue
                child_path = current_path.rstrip("/") + "/" + name
                if isinstance(child, DirNode):
                    self._glob_match(child, child_path, parts, idx, results)
                elif is_last or (idx + 1 < len(parts) and idx + 1 == len(parts) - 1):
                    pass
                if isinstance(child, FileNode):
                    if idx + 1 < len(parts):
                        next_part = parts[idx + 1]
                        if fnmatch.fnmatch(name, next_part) and idx + 1 == len(parts) - 1:
                            results.append(child_path)
                    else:
                        results.append(child_path)
        else:
            for name, child_id in list(node.children.items()):
                if not fnmatch.fnmatch(name, part):
                    continue
                child = self._nodes.get(child_id)
                if child is None:
                    continue
                child_path = current_path.rstrip("/") + "/" + name
                if is_last:
                    results.append(child_path)
                elif isinstance(child, DirNode):
                    self._glob_match(child, child_path, parts, idx + 1, results)

    def _collect_all_paths(self, node: DirNode, current_path: str,
                           results: list[str]) -> None:
        for name, child_id in list(node.children.items()):
            child = self._nodes.get(child_id)
            if child is None:
                continue
            child_path = current_path.rstrip("/") + "/" + name
            results.append(child_path)
            if isinstance(child, DirNode):
                self._collect_all_paths(child, child_path, results)
```

---

## 11. エラーハンドリング網羅表

| 操作 | 条件 | 送出例外 |
|---|---|---|
| `open(path, mode)` | テキストモード（`r`/`w` 等） | `ValueError` |
| `open(path, "rb")` | パスが存在しない | `FileNotFoundError` |
| `open(path, "r+b")` | パスが存在しない | `FileNotFoundError` |
| `open(path, "xb")` | パスが既に存在する | `FileExistsError` |
| `open(path, any)` | パスがディレクトリ | `IsADirectoryError` |
| `open(path, any)` | lock_timeout 超過 | `BlockingIOError` |
| `open(path, any)` | パストラバーサル検出 | `ValueError` |
| `write(data)` | クォータ超過 | `MFSQuotaExceededError` |
| `write(data)` | `rb` ハンドル | `io.UnsupportedOperation` |
| `read()` | `wb`/`ab`/`xb` ハンドル | `io.UnsupportedOperation` |
| `read()` / `write()` / `seek()` | クローズ済みハンドル | `ValueError` |
| `seek(n, 2)` where n > 0 | SEEK_END + 正オフセット | `ValueError` |
| `seek(n, w)` | whence が 0/1/2 以外 | `ValueError` |
| `seek(n, 0)` where n < 0 | SEEK_SET + 負オフセット | `ValueError` |
| `mkdir(path)` | 既存のディレクトリ・`exist_ok=False` | `FileExistsError` |
| `mkdir(path)` | 既存のファイルパス | `FileExistsError` |
| `rename(src, dst)` | src が存在しない | `FileNotFoundError` |
| `rename(src, dst)` | dst が既に存在する | `FileExistsError` |
| `rename(src, dst)` | dst の親ディレクトリが存在しない | `FileNotFoundError` |
| `rename("/", any)` | ルートの改名 | `ValueError` |
| `rename(src, dst)` | src にオープン済みハンドル | `BlockingIOError` |
| `remove(path)` | パスが存在しない | `FileNotFoundError` |
| `remove(path)` | パスがディレクトリ | `IsADirectoryError` |
| `remove(path)` | オープン済みハンドル存在 | `BlockingIOError` |
| `rmtree(path)` | パスがルート（`/`） | `ValueError` |
| `rmtree(path)` | パスが存在しない | `FileNotFoundError` |
| `rmtree(path)` | パスがファイル | `NotADirectoryError` |
| `rmtree(path)` | 配下にオープン済みハンドル | `BlockingIOError` |
| `listdir(path)` | パスが存在しない | `FileNotFoundError` |
| `listdir(path)` | パスがファイル | `NotADirectoryError` |
| `export_as_bytesio(path)` | パスが存在しない | `FileNotFoundError` |
| `export_as_bytesio(path)` | パスがディレクトリ | `IsADirectoryError` |
| `export_as_bytesio(path, max_size=N)` | ファイルサイズ > N | `ValueError` |
| `import_tree(tree)` | クォータ超過（ロールバック後） | `MFSQuotaExceededError` |
| `import_tree(tree)` | 対象ファイルにオープン済みハンドル | `BlockingIOError` |
| 自動昇格 | ファイルサイズがハードリミット超過 | `io.UnsupportedOperation` |
| `copy(src, dst)` | src が存在しない | `FileNotFoundError` |
| `copy(src, dst)` | src がディレクトリ | `IsADirectoryError` |
| `copy(src, dst)` | dst が既に存在する | `FileExistsError` |
| `copy(src, dst)` | dst の親ディレクトリが存在しない | `FileNotFoundError` |
| `get_size(path)` | パスが存在しない | `FileNotFoundError` |
| `get_size(path)` | パスがディレクトリ | `IsADirectoryError` |
| `copy_tree(src, dst)` | src が存在しない | `FileNotFoundError` |
| `copy_tree(src, dst)` | src がディレクトリでない | `NotADirectoryError` |
| `copy_tree(src, dst)` | dst が既に存在する | `FileExistsError` |
| `copy_tree(src, dst)` | dst の親ディレクトリが存在しない | `FileNotFoundError` |
| `copy_tree(src, dst)` | クォータ超過 | `MFSQuotaExceededError` |
| `move(src, dst)` | src が存在しない | `FileNotFoundError` |
| `move(src, dst)` | dst が既に存在する | `FileExistsError` |
| `move(src, dst)` | src にオープン済みハンドル | `BlockingIOError` |
| `move("/", any)` | ルートの移動 | `ValueError` |
| `stat(path)` | パスが存在しない | `FileNotFoundError` |
| `stat(path)` | パスがディレクトリ | `IsADirectoryError` |

---

## 12. 補足：仕様上の設計判断の論拠

### `SEEK_END` で正の offset を `ValueError` とする理由
Python 標準の `io.BytesIO` は `seek(n, 2)` で正の `n` を許容し、ファイル末尾を超えた位置へのシークが可能である（その後の `write()` でファイルがゼロ埋め拡張される）。MFS においてこれを非サポートとしたのは以下の理由による：
- ゼロ埋め拡張のクォータ計算（末尾超えシーク → write 前の時点でクォータを予約できない）が設計を複雑にする
- ゼロ埋め目的には `open(path, 'wb', preallocate=N)` で代替可能
- EOF 超えシークは日常的な使用パターンではなく、誤用の可能性が高い

### `rename()` で dst が既存ディレクトリの場合の扱い
`os.rename()` は、src がファイルで dst が空ディレクトリの場合に上書きを許可するOS（POSIX）がある。MFS では `dst` にエントリが存在する場合は **種別にかかわらず一律 `FileExistsError`** とする。理由：
- POSIX/Windows で挙動が異なるOSレベルの複雑な互換挙動をMFSに持ち込まない
- 呼び出し側が明示的に `rmtree(dst)` してから `rename()` することを促すことで、意図しない上書きを防ぐ

---

## 13. spec_v9.md との対応確認チェックリスト

以下は本設計書が spec_v9.md の全項目を網羅していることの確認表である。

| spec_v9.md の項目 | 本書の対応箇所 |
|---|---|
| §1.1 Non-Goals（VFS非対応、PathLike排除、リンク非サポート） | §1（モジュール構成）・§10の設計方針 |
| §1.2 tmpfs / BytesIO との差異 | README に転載（設計書では設計判断として内包） |
| §1.3 3原則（クォータ・ゼロ依存・関心の分離） | §2（例外）・§3（型）・§5（クォータ）に具現化 |
| §1.3 Python 3.11+ 要件の根拠 | §1（`typing.Self` 使用箇所に `from __future__ import annotations` で対応） |
| §1.4 ユースケース・メリット表 | README に転載 |
| §2.1 asyncio スタンス（純粋同期） | §10.4（`open()` 等の def 定義）、§21（AsyncMemoryFileSystem） |
| §2.2 FS全体ロック（RLock）・ファイルRWLock・ロック取得タイミング | §4（ReadWriteLock）・§10.4〜10.7 |
| §2.2 lock_timeout（None/0.0/正値）・BlockingIOError | §4（acquire_read/write）・§10.4 |
| §2.2 デッドロック防止規約（global→quota→rw順） | §4（順序規約）・§10.6〜10.7 |
| §3.1 例外マッピング（8種） | §2（MFSQuotaExceededError）・§11（網羅表） |
| §3.2 パス正規化・トラバーサル防止 | §9（normalize_path） |
| §3.3 世代ID (generation) | §7（FileNode.generation）・§8（write でインクリメント）・§10.12（import後リセット） |
| §4.1 BytesIO ブリッジ（ディープコピー・ロック・max_size・OOM注記） | §10.10 |
| §4.2 export_tree・iter_export_tree（弱整合性セマンティクス明記） | §10.11 |
| §4.2 import_tree（All-or-Nothing・ロールバック・メモリコスト注記） | §10.12 |
| §4.3 SQLite統合（serialize/deserialize・iterdump fallback） | §12（設計判断）＋README のコード例参照 |
| §5.1 _nodes・クォータ内部状態・_global_lock | §10.1 |
| §5.1 reserve_quota / _release_quota / _force_reserve | §5（QuotaManager） |
| §5.1 open()・preallocate・lock_timeout・5モード | §10.4 |
| §5.1 mkdir()（parents=True相当・os.mkdir互換注意） | §10.5 |
| §5.1 rename()（全エッジケース） | §10.6 |
| §5.1 move()（中間ディレクトリ自動作成） | §10.6 |
| §5.1 remove()・rmtree()（BlockingIOError・クォータ返却） | §10.7 |
| §5.1 listdir()（エントリ名のみ・NotADirectoryError） | §10.8 |
| §5.1 stats()（TypedDict・7キー） | §3（MFSStats TypedDict）・§10.9 |
| §5.1 stat()（MFSStatResult） | §10.9 |
| §5.2 IMemoryFile（純粋データストレージ） | §6.2 |
| §5.2 SequentialMemoryFile（キャリブレーション・bisect読み取り・昇格） | §6.1・§6.3 |
| §5.2 RandomAccessMemoryFile（shrink 対応） | §6.4 |
| §5.2 read_at・write_at・truncate・get_size・get_quota_usage | §6.2〜6.4 |
| §5.3 MemoryFileHandle（_cursor・_mode・_is_closed） | §8 |
| §5.3 read()（EOF=b""・モード違反）| §8 |
| §5.3 write()（差分クォータ計算・ab POSIX互換・タイムスタンプ更新） | §8 |
| §5.3 seek()（0/1/2対応・SEEK_END正値=ValueError・負カーソル=ValueError） | §8・§12（論拠） |
| §5.3 close()・__enter__/__exit__・__del__（ResourceWarning・stacklevel=1） | §8 |
| §5.3 MFSインスタンスGC（強参照・MFS側__del__不要） | §8（_mfs 強参照の保持） |
| §5.4 自動昇格フロー（FileNode.storage 差し替え・global_lock不要） | §6.3（_promote_and_write）・§4（順序規約） |

---

## 14. [v10 実装済み] ディレクトリインデックス層リファレンス

> **ステータス**: spec_v10.md §2.1 で設計確定。**実装完了。**

ディレクトリインデックス層の設計と実装の詳細は §7 に統合済み。`DirNode` / `FileNode` の定義、パス解決アルゴリズム、計算量改善については §7.1〜§7.3 を参照。

`IMemoryFile` からの `is_dir` / `generation` / `_rw_lock` の除去については §7.2 を参照。

---

## 15. [v10 実装済み] 新規API: `copy_tree()` / `move()`

> **ステータス**: spec_v10.md §4.4, §5.1 で設計確定。**実装完了。**

実装コードは §10.13（`copy_tree`）および §10.6（`move`）を参照。

---

## 16. [v10 実装済み] `glob("**")` パターン対応

> **ステータス**: spec_v10.md §5.1 で設計確定。**実装完了。**

### セマンティクス

| パターン | 挙動 |
|---|---|
| `*` | `/` **以外**の任意文字列にマッチ（単一階層） |
| `**` | ゼロ個以上のディレクトリに再帰マッチ |
| `?` | `/` を除く任意の1文字 |
| `[seq]`, `[!seq]` | 文字クラスの指定 |

実装コードは §10.14 を参照。`DirNode.children` を再帰走査し、各子ノードの名前に `fnmatch.fnmatch` でマッチングする。

---

## 17. [v10 実装済み] `walk()` スレッドセーフティ

> **ステータス**: **実装完了。**

`walk()` は弱整合性（Weak Consistency）モデルで動作する。各階層の子ノード一覧取得時に `list(node.children.items())` でスナップショットを取得し、GILフリー環境での `RuntimeError: dictionary changed size during iteration` を防止する。削除されたエントリはスキップされ、クラッシュはしない。

実装コードは §10.14 を参照。

---

## 18. v10 対応確認チェックリスト

| spec_v10.md の項目 | 本書の対応箇所 | 実装状態 |
|---|---|---|
| §2.1 ディレクトリインデックス層（DirNode/FileNode/NodeId） | §7 | ✅ 実装済み |
| §2.3 ロック階層 3層構造（global → quota → rw） | §4（順序規約） | ✅ 実装済み（global_lock 兼務） |
| §4.4 `copy_tree()` | §10.13 | ✅ 実装済み |
| §4.4 `move()` | §10.6 | ✅ 実装済み |
| §5.1 `wb` truncate 順序修正（ロック取得後に実行） | §10.4 | ✅ 実装済み |
| §5.1 `glob("**")` パターン対応 | §10.14, §16 | ✅ 実装済み |
| §5.1 `walk()` スレッドセーフティ注記 | §10.14, §17 | ✅ 実装済み |
| §5.1 `stats()` chunk_count 注記（SequentialMemoryFile のみ） | §10.9 | ✅ 実装済み |
| §5.2 `IMemoryFile` から is_dir/generation/_rw_lock 除去 | §6.2, §7.2 | ✅ 実装済み |
| §5.3 `__del__` stacklevel=1 | §8 | ✅ 実装済み |
| §4.1 `export_as_bytesio()` _global_lock 保護 | §10.10 | ✅ 実装済み |
| §5.5 弱整合性モデルの明記 | §10.11, §10.14 | ✅ 実装済み |
| `rename()` dst 親ディレクトリ存在確認 | §10.6 | ✅ 実装済み |
| §6 将来ロードマップ（タイムスタンプ等） | §19〜§22（v11 で詳細設計に昇格） | — |

---

## 19. [v11 実装済み] ファイルタイムスタンプと `stat()` API

> **ステータス**: spec_v11.md §6.1 で設計確定。**実装完了。**

### 19.1 タイムスタンプフィールド

`FileNode` に `created_at: float` と `modified_at: float` を保持（§7.1 参照）。`DirNode` にはタイムスタンプを持たせない（純粋な名前空間コンテナのため）。

### 19.2 タイムスタンプ更新タイミング

| 操作 | `created_at` | `modified_at` |
|---|---|---|
| ファイル新規作成（`open(wb/xb)` で新規） | `time.time()` | `created_at` と同値 |
| `write()` | 変更なし | `time.time()` |
| `truncate()` （`open(wb)` の既存ファイル） | 変更なし | `time.time()` |
| `rename()` / `move()` | 変更なし | 変更なし |
| `copy()` | コピー先: `time.time()` | コピー先: `created_at` と同値 |
| `copy_tree()` | 各コピー先: `time.time()` | 各コピー先: `created_at` と同値 |
| `import_tree()` | 各ファイル: `time.time()` | `created_at` と同値 |

実装箇所:
- `FileNode.__init__()`: `time.time()` で初期化（§7.1）
- `MemoryFileHandle.write()`: 書き込み成功後に `self._fnode.modified_at = time.time()`（§8）
- `MemoryFileSystem.open()` wb モード: truncate 後に `fnode.modified_at = time.time()`（§10.4）

### 19.3 `stat()` API

実装コードは §10.9 を参照。`_global_lock` 下でノード解決を行い、`MFSStatResult` を返却する。

### 19.4 メモリオーバーヘッド

`float` × 2 = 16 バイト / ファイル。1万ファイルでも約 160 KB であり、実データに対して無視可能。クォータ計算には含めない（メタデータ扱い）。

---

## 20. [v11 実装済み] メモリ使用量の最適化 (bytearray shrink)

> **ステータス**: spec_v11.md §6.2 で設計確定。**実装完了。**

### 20.1 shrink アルゴリズム

`RandomAccessMemoryFile.truncate()` において、新サイズが旧容量の 25% 以下に縮小した場合、`bytearray(self._buf)` で新バッファに再割り当てし、旧バッファを GC に回収させる。

```python
SHRINK_THRESHOLD: float = 0.25

def truncate(self, size: int, quota_mgr) -> None:
    old_size = len(self._buf)
    if size >= old_size:
        return
    release = old_size - size
    del self._buf[size:]
    # shrink 判定
    if old_size > 0 and size <= old_size * self.SHRINK_THRESHOLD:
        self._buf = bytearray(self._buf)
    quota_mgr.release(release)
```

### 20.2 設計判断

- **閾値 25%**: 元のサイズの 1/4 以下に縮小した場合にのみ shrink。頻繁な shrink のコピーコストを抑える。
- **クォータ整合性**: クォータ解放は shrink 有無に関係なく即時実行。shrink は実メモリ消費とクォータ計上値の乖離を緩和する最適化。
- **SequentialMemoryFile への影響**: shrink 不要。`truncate()` 時にチャンクリストを再構築する既存挙動で、不要チャンクは GC に回収される。

---

## 21. [v11 実装済み] PEP 703 (GIL-free Python) 対応設計

> **ステータス**: spec_v11.md §6.3 で設計確定。**対応完了。**

### 21.1 GIL 依存度分析

MFS は `threading.RLock` + `ReadWriteLock` による明示的ロックを使用しており、GIL への直接的依存は限定的。

| 箇所 | GIL 依存の性質 | 対応状況 |
|---|---|---|
| `_nodes` の `dict` 操作 | GIL 下でスレッドセーフ | `_global_lock` で保護済み |
| `export_as_bytesio()` エントリ参照 | GIL 下でアトミック | `_global_lock` 保護追加済み（v10） |
| `wb` truncate の読み取りハンドル競合 | 複数属性変更は GIL 下で順次 | ロック取得後に移動済み（v10） |
| `QuotaManager._used` 更新 | `int` 加算は GIL 下でアトミック | `threading.Lock` で保護済み |
| `ReadWriteLock` 内の `Condition` 操作 | GIL 非依存 | 正しく実装済み |
| `FileNode` 属性の直接読み取り | GIL 下でアトミック | ファイルロック下で保護 |
| `bytearray` スライス操作 | GIL 下でアトミック | ファイルロック下で保護 |
| `walk()`/`glob()` の dict イテレーション | GIL 下でアトミック | `list()` スナップショットで保護（v12） |

### 21.2 安全マージン

MFS のロック設計は GIL を性能最適化（ロック回避）のために利用していない。全スレッドセーフティは明示的ロック機構に依存。GIL フリー環境への移行は理論上追加コード変更なしで動作するが、free-threaded テストで実証が必要。

---

## 22. [v11 実装済み] async/await ラッパー層

> **ステータス**: spec_v11.md §6.4 で設計確定。**実装完了。**

### 22.1 設計原則

1. コア同期API への変更はゼロ
2. `asyncio.to_thread()` によるオフロード
3. `dmemfs/_async.py` に配置
4. ゼロ依存の維持（`asyncio` は標準ライブラリ）

### 22.2 `AsyncMemoryFileSystem` 実装

```python
# dmemfs/_async.py
import asyncio
import io
from typing import AsyncIterator
from ._fs import MemoryFileSystem
from ._typing import MFSStats, MFSStatResult


class AsyncMemoryFileHandle:
    """Async wrapper for a single open-file handle."""

    def __init__(self, _sync_handle) -> None:
        self._h = _sync_handle

    async def read(self, size: int = -1) -> bytes:
        return await asyncio.to_thread(self._h.read, size)

    async def write(self, data: bytes) -> int:
        return await asyncio.to_thread(self._h.write, data)

    async def seek(self, offset: int, whence: int = 0) -> int:
        return await asyncio.to_thread(self._h.seek, offset, whence)

    async def tell(self) -> int:
        return self._h.tell()  # 同期で十分（メモリアクセスのみ）

    async def close(self) -> None:
        await asyncio.to_thread(self._h.close)

    async def __aenter__(self) -> "AsyncMemoryFileHandle":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


class AsyncMemoryFileSystem:
    """
    MemoryFileSystem の非同期ラッパー。
    全操作を asyncio.to_thread() 経由で実行し、イベントループをブロックしない。
    """

    def __init__(
        self,
        max_quota: int = 256 * 1024 * 1024,
        chunk_overhead_override: int | None = None,
    ) -> None:
        self._sync = MemoryFileSystem(
            max_quota=max_quota,
            chunk_overhead_override=chunk_overhead_override,
        )

    async def open(self, path: str, mode: str = "rb",
                   preallocate: int = 0, lock_timeout: float | None = None
    ) -> AsyncMemoryFileHandle:
        h = await asyncio.to_thread(self._sync.open, path, mode, preallocate, lock_timeout)
        return AsyncMemoryFileHandle(h)

    async def mkdir(self, path: str, exist_ok: bool = False) -> None:
        await asyncio.to_thread(self._sync.mkdir, path, exist_ok)

    async def rename(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.rename, src, dst)

    async def move(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.move, src, dst)

    async def remove(self, path: str) -> None:
        await asyncio.to_thread(self._sync.remove, path)

    async def rmtree(self, path: str) -> None:
        await asyncio.to_thread(self._sync.rmtree, path)

    async def listdir(self, path: str) -> list[str]:
        return await asyncio.to_thread(self._sync.listdir, path)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync.exists, path)

    async def is_dir(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync.is_dir, path)

    async def stat(self, path: str) -> MFSStatResult:
        return await asyncio.to_thread(self._sync.stat, path)

    async def stats(self) -> MFSStats:
        return await asyncio.to_thread(self._sync.stats)

    async def get_size(self, path: str) -> int:
        return await asyncio.to_thread(self._sync.get_size, path)

    async def export_as_bytesio(self, path: str, max_size: int | None = None) -> io.BytesIO:
        return await asyncio.to_thread(self._sync.export_as_bytesio, path, max_size)

    async def export_tree(self, prefix: str = "/", only_dirty: bool = False) -> dict[str, bytes]:
        return await asyncio.to_thread(self._sync.export_tree, prefix, only_dirty)

    async def import_tree(self, tree: dict[str, bytes]) -> None:
        await asyncio.to_thread(self._sync.import_tree, tree)

    async def copy(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.copy, src, dst)

    async def copy_tree(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.copy_tree, src, dst)

    async def walk(self, path: str = "/") -> list[tuple[str, list[str], list[str]]]:
        """walk() の結果を一括取得して返す（リスト化）。"""
        return await asyncio.to_thread(lambda: list(self._sync.walk(path)))

    async def glob(self, pattern: str) -> list[str]:
        return await asyncio.to_thread(self._sync.glob, pattern)
```

### 22.3 設計上の注意事項

- **`to_thread()` オーバーヘッド**: 各呼び出しに数十μs のスレッドプール切替コスト。パフォーマンス重視なら同期API を直接使用すべき。
- **`walk()` のリスト化**: 同期版はジェネレータだが、スレッドをまたぐジェネレータ管理が複雑なためリスト化。
- **`iter_export_tree()` 非提供**: 同様の理由。`export_tree()` で代替。
- **`tell()` 同期実行**: カーソル位置読み取りのみでロック不要のため、`to_thread()` 不使用。
- **遅延インポート**: `__init__.py` では `__getattr__` + `TYPE_CHECKING` ガードにより `AsyncMemoryFileSystem` の遅延インポートを実現。asyncio 未使用環境でのインポートコスト回避。

### 22.4 使用例

```python
import asyncio
from dmemfs import AsyncMemoryFileSystem

async def main():
    mfs = AsyncMemoryFileSystem(max_quota=64 * 1024 * 1024)
    await mfs.mkdir("/data")

    async with await mfs.open("/data/output.bin", "wb") as f:
        await f.write(b"async write!")

    async with await mfs.open("/data/output.bin", "rb") as f:
        data = await f.read()
        print(data)  # b"async write!"

asyncio.run(main())
```

---

## 23. v11 対応確認チェックリスト

| spec_v11.md の項目 | 本書の対応箇所 | 実装状態 |
|---|---|---|
| §6.1 ファイルタイムスタンプ（`FileNode` に `created_at`/`modified_at`） | §7.1, §19 | ✅ 実装済み |
| §6.1 `stat()` API | §10.9, §19.3 | ✅ 実装済み |
| §6.1 `MFSStatResult` 型定義 | §3 | ✅ 実装済み |
| §6.2 `bytearray` shrink 機構 | §6.4, §20 | ✅ 実装済み |
| §6.3 PEP 703 対応設計 | §21 | ✅ 実装済み |
| §6.4 `AsyncMemoryFileSystem` ラッパー | §22 | ✅ 実装済み |
| §6.4 `AsyncMemoryFileHandle` ラッパー | §22.2 | ✅ 実装済み |
| §6.4 `_async.py` モジュール追加 | §1 | ✅ 実装済み |
| §6.5 `metadata_tree_lock` 分離 | 設計書範囲外（将来検討） | — |

---

## 24. [v12 実装済み] Opus評価レポート対応

> **ステータス**: spec_v12.md のフィードバック反映。**全項目実装完了。**

### 24.1 `_NoOpQuotaManager` 削除

`_fs.py` に定義されていた `_NoOpQuotaManager` クラスを削除。未使用コードであり、クォータバイパスの誤用リスクを排除するための措置。

> **注**: v12 で完全に削除済み。`contextmanager` インポートも同時に除去。

### 24.2 `AsyncMemoryFileSystem` の遅延インポート

`__init__.py` で `__getattr__` + `TYPE_CHECKING` ガードにより `AsyncMemoryFileSystem` の遅延インポートを実現（spec_v12.md §6.4 準拠）。`asyncio` 未使用環境でのインポートコスト増を回避しつつ、`isinstance()` チェック、IDE補完、`help()` が正常に動作する。

### 24.3 `_force_reserve()` 使用制約の明記

`QuotaManager._force_reserve(size)` は上限チェックを行わない内部専用メソッド。使用条件:

1. `_global_lock` 保持下でのみ呼び出し可能
2. 呼び出し前に `free` との比較によるクォータ事前チェックが完了していること
3. 使用箇所: `import_tree()` および `copy_tree()` のみ

### 24.4 `copy()` API仕様の補完

`copy(src, dst)` の完全な引数仕様・例外仕様を §10.13 および §11（エラーハンドリング網羅表）に明記。

### 24.5 `get_size()` / `listdir()` のロック保護

GILフリー環境での安全性確保のため、ノード解決時の保護を確認。現行実装では `get_size()` / `listdir()` は `_global_lock` 下でノード解決を行っており、`_resolve_path()` による `_nodes` 辞書の読み取りは構造変更と競合しない。v12 の方針に沿い対応済みである。

### 24.6 `walk()` / `glob()` の GILフリースナップショット安全性

`_walk_dir()` および `_glob_match()` において、`DirNode.children` のイテレーション前に `list()` でスナップショットを取得する設計を適用済み。GILフリー環境（PEP 703, Python 3.13t）での `RuntimeError: dictionary changed size during iteration` を防止する。

---

## 25. v12 対応確認チェックリスト

| spec_v12.md の項目 | 本書の対応箇所 | 実装状態 |
|---|---|---|
| `_NoOpQuotaManager` 削除 | §24.1 | ✅ 削除済み |
| `AsyncMemoryFileSystem` 遅延インポート | §1, §24.2 | ✅ 実装済み（`__getattr__` + `TYPE_CHECKING` 方式） |
| `_force_reserve()` 使用制約の明記 | §5, §24.3 | ✅ 実装済み |
| `copy()` API仕様の補完 | §10.13, §11 | ✅ 実装済み |
| `get_size()`/`listdir()` のロック保護 | §10.8, §24.5 | ✅ 対応済み（注記あり） |
| `walk()`/`glob()` のGILフリースナップショット安全性 | §10.14, §24.6 | ✅ 実装済み |
| `_global_lock` 保持中のファイルロック待機（注意事項強化） | §10.4 | ✅ 注記済み |

---

## 付録A：v9 からの変更サマリ

| 項目 | v9 | v10 | v11 | v12 | 変更根拠 |
|---|---|---|---|---|---|
| 内部ストレージ構造 | `_tree: dict[str, IMemoryFile]` | `DirNode/FileNode` + `_nodes: dict[int, Node]` | 同左 | 同左 | listdir $O(N)$ → $O(\text{children})$ 改善 |
| ロック階層 | 2層（global → rw） | 3層（global → quota → rw） | 同左 | 同左 | ディレクトリインデックス層との親和性 |
| `wb` truncate 順序 | ロック取得**前** | ロック取得**後** | 同左 | 同左 | PEP 703 対応 |
| `walk()` 整合性 | 暗黙的 | 弱整合性を**明記** | 同左 | `list()` スナップショット追加 | GILフリー安全性 |
| `glob()` パターン | `fnmatch.fnmatch` | `*` は `/` 以外、`**` で再帰マッチ | 同左 | 同左 | 標準glob挙動との整合 |
| `export_as_bytesio()` | `_global_lock` なし | `_global_lock` で保護 | 同左 | 同左 | GILフリー対応 |
| `__del__` stacklevel | `stacklevel=2` | `stacklevel=1` | 同左 | 同左 | GCから呼ばれるため |
| `stats()` chunk_count | 暗黙的 | SequentialMemoryFile のみと**明記** | 同左 | 同左 | ドキュメント品質向上 |
| 新規API (v10) | — | `copy_tree()`, `move()`, `glob("**")` | 同左 | 同左 | ツリー操作の充実 |
| `is_dir`等の所在 | `IMemoryFile` 内 | `DirNode`/`FileNode` に分離 | 同左 | 同左 | 関心の分離 |
| **タイムスタンプ** | なし | ロードマップのみ | `FileNode` に追加、`stat()` API | 同左 | 差分処理判定、アーカイブ対応 |
| **bytearray shrink** | なし | ロードマップのみ | `truncate()` に shrink 機構 | 同左 | メモリ効率の改善 |
| **PEP 703 対応** | なし | ロードマップのみ | 対応設計の詳細化 | 同左 | free-threaded Python への備え |
| **async/await** | なし | ロードマップのみ | `AsyncMemoryFileSystem` ラッパー | 同左 | asyncio アプリとの統合 |
| **`_NoOpQuotaManager`** | — | — | — | **削除** | 未使用コード除去 |
| **`AsyncMemoryFileSystem` 公開** | なし | なし | `__getattr__` 遅延インポート | 同左（遅延インポート確認） | `asyncio` コスト回避 |
| **`copy()` API仕様** | — | — | — | **引数仕様・例外仕様を明記** | ドキュメント品質 |
| **`_force_reserve()` 制約** | — | — | — | **使用条件を明記** | 安全性・保守性 |
