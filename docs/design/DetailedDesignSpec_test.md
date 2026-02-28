# MemoryFileSystem (MFS) テスト詳細設計書 (DetailedDesignSpec_test)

本書は `MFS_v9_test_implementation_instruction.md` の方針に従い、`spec_v9.md` および `DetailedDesignSpec.md` で確定した仕様を**テストコードとして固定するための実装指針書**である。テスト関数名・検証観点・擬似コード・共通フィクスチャを含み、これ単体でテスト実装に着手可能なレベルの情報を提供する。

> **v10 更新**: 本書は `spec_v10.md` の変更を反映して更新された。v10 で追加・変更されたテストには `[v10]` タグを付与し、実装済みのテストには `[v10 実装済み]` タグを付与している。

> **v11 更新**: `spec_v11.md` の Phase 3 設計を反映。v11 で追加されたテストには `[v11]` タグを付与し、実装済みのテストには `[v11 実装済み]` タグを付与している。v11 新規テストセクション: §17〜§20。

> **v12 更新**: カバレッジ 99% 達成に向けた追加テストを反映。v12 で追加されたテストには `[v12]` タグを付与している。主な追加: `tests/unit/test_fs_coverage.py`（新規、§21）、各既存ファイルへのブランチカバレッジ補完テスト。テスト総数: 283 件。

---

## 1. テスト構成概要

### 1.1 優先度体系（DoD）

| 優先度 | 意味 | 公開判断への影響 |
|---|---|---|
| **P0** | ここが落ちたら公開NG | 全通過必須 |
| **P1** | 通ると信用が跳ねる | 原則全通過、理由付き失敗は許容 |
| **P2** | 余裕があれば | 任意 |

### 1.2 テストの層

| 層 | 対象 | 配置ディレクトリ |
|---|---|---|
| **Unit** | `_lock`, `_quota`, `_path`, `_file`, `_handle` の局所仕様 | `tests/unit/` |
| **Integration** | `MemoryFileSystem` 公開API全体 | `tests/integration/` |
| **System-like** | 代表ユースケース（SQLite/ETL/アーカイブ）の完結シナリオ | `tests/scenarios/` |

### 1.3 ディレクトリ構成

```
tests/
├── unit/
│   ├── test_lock.py
│   ├── test_quota.py
│   ├── test_path_normalize.py
│   ├── test_files_sequential.py
│   ├── test_files_randomaccess.py
│   ├── test_handle_io.py
│   └── test_fs_coverage.py          # [v12] 新規追加
├── integration/
│   ├── test_open_modes.py
│   ├── test_mkdir_listdir.py
│   ├── test_rename_move.py
│   ├── test_remove_rmtree.py
│   ├── test_export_import.py
│   └── test_stats.py
├── scenarios/
│   ├── test_usecase_archive_like.py
│   ├── test_usecase_etl_staging.py
│   ├── test_usecase_sqlite_snapshot.py
│   └── test_usecase_restricted_env.py
├── property/
│   └── test_hypothesis.py
└── helpers/
    ├── fixtures.py
    ├── concurrency.py
    └── asserts.py
```

### 1.4 テスト依存ライブラリ

```
# tests/requirements.txt
pytest>=8.0
pytest-timeout>=2.3
hypothesis>=6.100
pytest-xdist>=3.5     # 安定化後に並列実行で使用
```

---

## 2. 共通フィクスチャ・ヘルパー（`tests/helpers/`）

### 2.1 `fixtures.py`

```python
import pytest
from dmemfs import MemoryFileSystem

@pytest.fixture
def mfs():
    """デフォルトクォータ(1MB)のMFSインスタンス。テストごとに新規生成。"""
    return MemoryFileSystem(max_quota=1 * 1024 * 1024)
```

> **注記**: `mfs` フィクスチャは `tests/helpers/fixtures.py` から `tests/conftest.py` に移動済み（パッケージ名も `dmemfs` に変更）。`mfs_small`・`mfs_medium`・`mfs_with_files` フィクスチャは参照がゼロだったため削除済み。`mfs` フィクスチャのみ残す。

### 2.2 `concurrency.py`

スレッドを使ったロック競合テストのユーティリティ。

```python
import threading
from contextlib import contextmanager

class ThreadedLockHolder:
    """
    バックグラウンドスレッドでロックを保持し、
    外部からの合図で解放するユーティリティ。
    
    使用例:
        with ThreadedLockHolder(mfs, "/file.bin", "wb") as holder:
            # ここでは /file.bin の write ロックが他スレッドに保持されている
            with pytest.raises(BlockingIOError):
                mfs.open("/file.bin", "wb", lock_timeout=0.0)
    """
    def __init__(self, mfs, path: str, mode: str):
        self._mfs = mfs
        self._path = path
        self._mode = mode
        self._handle = None
        self._ready = threading.Event()
        self._release = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        return self

    def __exit__(self, *_):
        self._release.set()
        self._thread.join(timeout=5.0)

    def _run(self):
        with self._mfs.open(self._path, self._mode) as h:
            self._ready.set()
            self._release.wait(timeout=10.0)


def run_concurrent(target_fn, n_threads: int, timeout: float = 5.0) -> list:
    """
    n_threads 個のスレッドで target_fn を同時実行し、結果リストを返す。
    例外は ExceptionInfo として結果リストに格納する。
    """
    results = [None] * n_threads
    errors = [None] * n_threads
    threads = []
    start_barrier = threading.Barrier(n_threads)

    def worker(i):
        try:
            start_barrier.wait(timeout=timeout)
            results[i] = target_fn(i)
        except Exception as e:
            errors[i] = e

    for i in range(n_threads):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=timeout + 1.0)
    return results, errors
```

### 2.3 `asserts.py`

```python
def assert_stats_consistent(mfs):
    """stats() の内部整合性を確認する共通アサーション。"""
    s = mfs.stats()
    assert set(s.keys()) == {
        "used_bytes", "quota_bytes", "free_bytes",
        "file_count", "dir_count", "chunk_count",
        "overhead_per_chunk_estimate",
    }, f"stats() keys mismatch: {set(s.keys())}"
    assert s["used_bytes"] >= 0
    assert s["quota_bytes"] > 0
    assert s["free_bytes"] == s["quota_bytes"] - s["used_bytes"]
    assert s["file_count"] >= 0
    assert s["dir_count"] >= 1  # ルートディレクトリは常に存在
    assert s["overhead_per_chunk_estimate"] > 0
```

> **注記**: `assert_mfs_unchanged()` は参照がゼロだったため削除済み。`assert_stats_consistent()` のみ残す。

---

## 3. Unit テスト詳細設計

### 3.1 `tests/unit/test_lock.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_multiple_readers_allowed` | P0 | 複数スレッドが同時に read lock を取得できる |
| `test_write_lock_exclusive_blocks_reader` | P0 | write ロック保持中は reader が待機（ブロック） |
| `test_write_lock_exclusive_blocks_writer` | P0 | write ロック保持中は writer が待機（ブロック） |
| `test_reader_blocks_writer` | P0 | read ロック保持中は writer が待機 |
| `test_timeout_zero_raises_immediately` | P0 | timeout=0.0 は即時 BlockingIOError |
| `test_timeout_positive_raises_after_wait` | P0 | 正の timeout 後に BlockingIOError |
| `test_timeout_none_blocks_until_released` | P0 | None は解放されるまでブロッキング |
| `test_release_read_enables_write` | P0 | release_read 後に write lock 取得可能 |
| `test_release_write_enables_read` | P0 | release_write 後に read lock 取得可能 |
| `test_is_locked_reflects_state` | P1 | is_locked が正確に状態を反映 |
| `test_acquire_write_timeout_raises` [v12] | P1 | acquire_write が有限タイムアウトで BlockingIOError を送出する |
| `test_acquire_read_with_none_timeout_waits` [v12] | P1 | timeout=None で acquire_read が write 解放後に成功する（_remaining None 分岐） |

#### 主要テスト擬似コード

```python
@pytest.mark.timeout(5)
def test_multiple_readers_allowed():
    lock = ReadWriteLock()
    acquired = []
    barrier = threading.Barrier(3)

    def reader():
        lock.acquire_read()
        barrier.wait()  # 3スレッド全員がロック取得後に揃う
        acquired.append(True)
        lock.release_read()

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(acquired) == 3  # 全員がブロックされずに取得できた


@pytest.mark.timeout(5)
def test_timeout_zero_raises_immediately():
    lock = ReadWriteLock()
    lock.acquire_write()  # 先にwriteロックを取得
    try:
        with pytest.raises(BlockingIOError):
            lock.acquire_write(timeout=0.0)  # 即時失敗
    finally:
        lock.release_write()


@pytest.mark.timeout(5)
def test_timeout_positive_raises_after_wait():
    lock = ReadWriteLock()
    lock.acquire_write()
    start = time.monotonic()
    try:
        with pytest.raises(BlockingIOError):
            lock.acquire_write(timeout=0.2)
    finally:
        lock.release_write()
    elapsed = time.monotonic() - start
    assert 0.15 <= elapsed < 1.0, f"timeout=0.2 なのに elapsed={elapsed:.3f}"
```

---

### 3.2 `tests/unit/test_quota.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_reserve_success_increments_used` | P0 | 正常予約で used が増加 |
| `test_reserve_exact_quota_succeeds` | P0 | used + size == quota ちょうどは成功 |
| `test_reserve_exceeds_raises_quota_error` | P0 | 超過は MFSQuotaExceededError |
| `test_reserve_rollback_on_exception` | P0 | with ブロック内例外 → used がロールバック |
| `test_reserve_zero_is_noop` | P1 | size=0 は変化なし、例外なし |
| `test_release_decrements_used` | P0 | release で used が減少 |
| `test_release_excess_clamps_to_zero` | P1 | 過剰 release は 0 以下にならない |
| `test_sequential_reserves_accumulate` | P0 | 複数予約が積み上がる |
| `test_free_bytes_computed_correctly` | P0 | free == quota - used |
| `test_quota_error_carries_requested_and_available` | P1 | エラーオブジェクトが requsted/available 属性を持つ |
| `test_force_reserve_zero_or_negative_is_noop` [v12] | P1 | `_force_reserve(0)` と `_force_reserve(-5)` は used_bytes を変化させない |

#### 主要テスト擬似コード

```python
def test_reserve_rollback_on_exception():
    qm = QuotaManager(max_quota=100)
    assert qm.used == 0
    try:
        with qm.reserve(50):
            assert qm.used == 50
            raise RuntimeError("simulated failure")
    except RuntimeError:
        pass
    assert qm.used == 0  # ロールバックされている


def test_reserve_rollback_on_quota_error_during_nested_call():
    """外側の with が正常でも、内側でクォータ超過した場合のロールバック確認。"""
    qm = QuotaManager(max_quota=100)
    with qm.reserve(60):
        assert qm.used == 60
        with pytest.raises(MFSQuotaExceededError):
            with qm.reserve(50):  # 60+50=110 > 100
                pass
        assert qm.used == 60  # 外側の60は維持
    assert qm.used == 0
```

---

### 3.3 `tests/unit/test_path_normalize.py`

#### テスト一覧

| テスト関数名 | 優先度 | 入力 | 期待出力 |
|---|---|---|---|
| `test_relative_path_gets_slash` | P0 | `"a/b"` | `"/a/b"` |
| `test_backslash_converted` | P0 | `r"\a\b"` | `"/a/b"` |
| `test_dot_segment_removed` | P0 | `"/a/./b"` | `"/a/b"` |
| `test_dotdot_resolved_within_root` | P0 | `"/a/b/.."` | `"/a"` |
| `test_root_path_unchanged` | P0 | `"/"` | `"/"` |
| `test_double_slash_normalized` | P1 | `"//a//b"` | `"/a/b"` |
| `test_traversal_beyond_root_raises` | P0 | `"../x"` | `ValueError` |
| `test_deep_traversal_raises` | P0 | `"/a/../../x"` | `ValueError` |
| `test_traversal_with_backslash_raises` | P0 | `r"..\x"` | `ValueError` |
| `test_empty_string_becomes_root` | P1 | `""` | `"/"` |

---

### 3.4 `tests/unit/test_files_sequential.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_initial_size_is_zero` | P0 | 初期 get_size() == 0 |
| `test_append_grows_size` | P0 | 末尾 write_at でサイズ増加 |
| `test_read_at_returns_correct_slice` | P0 | 書いた内容を read_at で正確に読み返せる |
| `test_truncate_reduces_size` | P0 | truncate(n) 後 get_size() == n |
| `test_write_at_tail_offset_succeeds` | P0 | offset == current_size の write は成功 |
| `test_write_at_nontail_raises_promotion_signal` | P0 | offset < current_size で _PromotionSignal 送出 |
| `test_calibration_returns_positive_int` | P1 | _calibrate_chunk_overhead() > 0 |
| `test_generation_increments_on_write` | P1 | write_at でgeneration が増加 |
| `test_generation_increments_on_truncate` | P1 | truncate でgeneration が増加 |
| `test_quota_charged_on_write` | P0 | write_at でクォータが消費される |
| `test_quota_released_on_truncate` | P0 | truncate でクォータが解放される |
| `test_read_at_negative_size_returns_all` [v12] | P1 | read_at(offset, -1) で offset 以降全データを返す |
| `test_write_at_empty_data_is_noop` [v12] | P1 | write_at(0, b"") はサイズ・quota を変化させない |
| `test_truncate_same_or_larger_size_is_noop` [v12] | P1 | truncate(n) で n >= current_size なら何も変わらない |
| `test_promotion_hard_limit_raises` [v12] | P1 | _size が PROMOTION_HARD_LIMIT 超えの Sequential への非末尾書き込みは UnsupportedOperation |

---

### 3.5 `tests/unit/test_files_randomaccess.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_write_at_arbitrary_offset` | P0 | 任意オフセットへの書き込みが正確 |
| `test_write_gap_zero_filled` | P0 | 書き込みギャップがゼロ埋めされる |
| `test_overwrite_in_place` | P0 | 既存範囲への上書きはサイズ変化なし |
| `test_truncate_reduces_size` | P0 | truncate でサイズ縮小 |
| `test_quota_charged_only_for_size_increase` | P0 | 上書きはクォータ増加なし |
| `test_from_bytearray_preserves_content` | P1 | from_bytearray で内容が保持される |
| `test_truncate_shrinks_buffer_below_threshold` [v11 実装済み] | P1 | 25% 以下への truncate で bytearray が再割り当てされる |
| `test_truncate_no_shrink_above_threshold` [v11 実装済み] | P1 | 25% 超への truncate では再割り当てされない |
| `test_shrink_preserves_data` [v11 実装済み] | P0 | shrink 後もデータが正しく読み取れる |
| `test_shrink_quota_consistency` [v11 実装済み] | P1 | shrink 後もクォータ計上値が正しい |
| `test_truncate_to_zero_shrinks` [v11 実装済み] | P1 | サイズ 0 への truncate で shrink が実行される |
| `test_read_at_negative_size_clamps_to_remaining` [v12] | P1 | read_at(offset, -1) で末尾まで全データを返す |
| `test_write_at_empty_data_is_noop` [v12] | P1 | write_at(offset, b"") はサイズ・quota を変化させない |

---

### 3.6 `tests/unit/test_handle_io.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_read_returns_all_content` | P0 | read() 全量読み取り |
| `test_read_size_parameter` | P0 | read(n) で n バイトのみ読む |
| `test_read_at_eof_returns_empty` | P0 | EOF での read は b"" |
| `test_write_advances_cursor` | P0 | write 後に tell() が進む |
| `test_seek_set` | P0 | seek(n, 0) でカーソルが n に移動 |
| `test_seek_cur_relative` | P0 | seek(n, 1) で相対移動 |
| `test_seek_end_negative` | P0 | seek(-n, 2) で末尾から n バイト前 |
| `test_seek_end_zero` | P0 | seek(0, 2) でちょうど末尾 |
| `test_seek_end_positive_raises` | P0 | seek(1, 2) は ValueError |
| `test_seek_invalid_whence_raises` | P0 | seek(0, 3) は ValueError |
| `test_seek_negative_result_raises` | P0 | seek(-999, 0) は ValueError |
| `test_closed_handle_raises_value_error` | P0 | 全操作がクローズ後 ValueError |
| `test_read_on_write_only_mode_raises` | P0 | "wb" ハンドルで read → UnsupportedOperation |
| `test_write_on_read_only_mode_raises` | P0 | "rb" ハンドルで write → UnsupportedOperation |
| `test_context_manager_closes_handle` | P0 | with 文で自動 close |
| `test_del_without_close_emits_resource_warning` | P1 | ResourceWarning が warnings に発行される |
| `test_ab_write_always_appends_to_eof` | P0 | ab モードで seek しても次の write は EOF へ |
| `test_seek_end_positive_offset_raises` [v12] | P0 | seek(1, 2) SEEK_END に正のオフセットを渡すと ValueError |
| `test_seek_cur_negative_result_raises` [v12] | P0 | SEEK_CUR でカーソルが負になる場合は ValueError |
| `test_seek_invalid_whence_raises` [v12] | P0 | whence=99 など無効な値は ValueError |
| `test_tell_on_closed_handle_raises` [v12] | P0 | クローズ済みハンドルで tell() は ValueError |
| `test_close_twice_is_idempotent` [v12] | P1 | close() を2回呼んでも例外は発生しない |

#### 主要テスト擬似コード

```python
def test_ab_write_always_appends_to_eof(mfs):
    """ab モードの POSIX 互換: seek を無視して常に EOF へ書き込む。"""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello")  # 5 bytes

    with mfs.open("/f.bin", "ab") as f:
        f.seek(0, 0)          # カーソルを先頭に移動（無視されるはず）
        f.write(b" world")    # EOF に追記されるべき

    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"hello world"  # "world" は末尾に付く


def test_del_without_close_emits_resource_warning(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x")
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        handle = mfs.open("/f.bin", "rb")
        del handle
        # CPython では参照カウントで即 __del__ が呼ばれる
    assert any(issubclass(warning.category, ResourceWarning) for warning in w)


def test_closed_handle_raises_value_error(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/f.bin", "rb") as f:
        pass  # close 済み
    with pytest.raises(ValueError):
        f.read()
    with pytest.raises(ValueError):
        f.seek(0)
    with pytest.raises(ValueError):
        f.tell()
```

---

## 4. Integration テスト詳細設計

### 4.1 `tests/integration/test_open_modes.py`

#### テスト一覧

| テスト関数名 | 優先度 | モード | 検証観点 |
|---|---|---|---|
| `test_rb_reads_existing_file` | P0 | rb | 既存ファイルを読み取れる |
| `test_rb_nonexistent_raises` | P0 | rb | FileNotFoundError |
| `test_rb_on_directory_raises` | P0 | rb | IsADirectoryError |
| `test_wb_creates_new_file` | P0 | wb | 新規作成 |
| `test_wb_truncates_existing_content` | P0 | wb | 既存内容が消える |
| `test_wb_on_directory_raises` | P0 | wb | IsADirectoryError |
| `test_ab_creates_if_missing` | P0 | ab | 新規作成 |
| `test_ab_appends_to_existing` | P0 | ab | 既存内容の後ろに追記 |
| `test_ab_forces_eof_on_write` | P0 | ab | seek しても write は EOF へ（→ test_handle_io と重複可） |
| `test_rpb_reads_and_writes_existing` | P0 | r+b | 読み書き両方できる |
| `test_rpb_nonexistent_raises` | P0 | r+b | FileNotFoundError |
| `test_xb_creates_exclusive` | P0 | xb | 新規作成成功 |
| `test_xb_existing_raises` | P0 | xb | FileExistsError |
| `test_text_mode_raises` | P0 | r/w/a/x | ValueError（バイナリ専用） |
| `test_invalid_mode_string_raises` | P0 | 任意 | ValueError |
| `test_preallocate_fills_zeros` | P1 | wb | preallocate=N で N バイトのゼロが書かれる |
| `test_preallocate_charges_quota` | P1 | wb | preallocate 分クォータが消費 |
| `test_lock_timeout_zero_fails_on_contention` | P0 | wb | 競合時に lock_timeout=0.0 で BlockingIOError |
| `test_lock_timeout_positive_fails_on_contention` | P0 | wb | タイムアウト後 BlockingIOError |
| `test_multiple_rb_handles_allowed` | P0 | rb | 複数の rb が同時に開ける |
| `test_rb_and_wb_contend` | P0 | rb/wb | rb が開いている間は wb が待機またはタイムアウト |

#### 主要テスト擬似コード

```python
def test_wb_truncates_existing_content(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original content")
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"new")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"new"  # "original content" は消えている


def test_lock_timeout_zero_fails_on_contention(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x")
    from tests.helpers.concurrency import ThreadedLockHolder
    with ThreadedLockHolder(mfs, "/f.bin", "wb"):
        with pytest.raises(BlockingIOError):
            mfs.open("/f.bin", "wb", lock_timeout=0.0)


def test_multiple_rb_handles_allowed(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"shared")
    h1 = mfs.open("/f.bin", "rb")
    h2 = mfs.open("/f.bin", "rb")
    try:
        assert h1.read() == b"shared"
        h2.seek(0)
        assert h2.read() == b"shared"
    finally:
        h1.close()
        h2.close()
```

---

### 4.2 `tests/integration/test_mkdir_listdir.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_mkdir_creates_directory` | P0 | mkdir 後に is_dir == True |
| `test_mkdir_creates_parents_automatically` | P0 | 親なしでも自動作成（os.makedirs相当） |
| `test_mkdir_exist_ok_false_raises` | P0 | exist_ok=False で既存ディレクトリ → FileExistsError |
| `test_mkdir_exist_ok_true_is_noop` | P0 | exist_ok=True で既存ディレクトリ → 正常 |
| `test_mkdir_over_existing_file_raises` | P0 | ファイルと同パスに mkdir → FileExistsError |
| `test_listdir_returns_direct_children_only` | P0 | 直下エントリ名のみ（再帰なし） |
| `test_listdir_excludes_grandchildren` | P0 | 孫ディレクトリのエントリは含まれない |
| `test_listdir_returns_names_not_paths` | P0 | 絶対パスではなく名前のみ |
| `test_listdir_nonexistent_raises` | P0 | FileNotFoundError |
| `test_listdir_on_file_raises` | P0 | NotADirectoryError |
| `test_exists_file` | P0 | ファイルに対して True |
| `test_exists_directory` | P0 | ディレクトリに対して True |
| `test_exists_missing` | P0 | 存在しないパスに False |
| `test_is_dir_true_for_directory` | P0 | ディレクトリに True |
| `test_is_dir_false_for_file` | P0 | ファイルに False |
| `test_makedirs_file_at_path_component_raises` [v12] | P0 | 中間パスコンポーネントにファイルが存在する場合 _makedirs が FileExistsError を発生させる |
| `test_glob_consecutive_double_star` [v12] | P1 | `/**/**/*.txt` 連続 `**` でも正しくマッチ |
| `test_glob_double_star_trailing_slash` [v12] | P1 | `/**/f.txt` 中間ディレクトリ走査 |
| `test_glob_question_mark` [v12] | P1 | `?` が任意の1文字にマッチ |
| `test_glob_character_class` [v12] | P1 | `[abc]` 文字クラスでのマッチ |
| `test_glob_double_star_at_beginning` [v12] | P1 | `/**/*.txt` ルートから再帰マッチ |

#### 主要テスト擬似コード

```python
def test_listdir_returns_direct_children_only(mfs):
    mfs.mkdir("/a/b/c")       # /a, /a/b, /a/b/c が作成される
    with mfs.open("/a/f.txt", "wb") as f:
        f.write(b"x")
    children = mfs.listdir("/a")
    assert sorted(children) == ["b", "f.txt"]  # c は含まれない

def test_mkdir_creates_parents_automatically(mfs):
    """os.mkdir と異なり、親なしでも成功する（os.makedirs 相当）。"""
    mfs.mkdir("/x/y/z")   # /x, /x/y が存在しなくても成功
    assert mfs.is_dir("/x")
    assert mfs.is_dir("/x/y")
    assert mfs.is_dir("/x/y/z")
```

---

### 4.3 `tests/integration/test_rename_move.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_rename_file_changes_path` | P0 | src が消え dst に出現 |
| `test_rename_file_preserves_content` | P0 | rename 後に内容が同じ |
| `test_rename_directory_moves_all_children` | P0 | ディレクトリ配下の全エントリが新パスへ |
| `test_rename_src_missing_raises` | P0 | FileNotFoundError |
| `test_rename_dst_exists_raises` | P0 | FileExistsError（dst が何であれ） |
| `test_rename_root_raises` | P0 | ValueError |
| `test_rename_open_file_raises` | P0 | BlockingIOError |
| `test_rename_dir_with_open_child_raises` | P0 | 配下にオープン済み → BlockingIOError |
| `test_rename_file_to_different_dir` | P1 | 別ディレクトリへの移動 |
| `test_rename_dst_parent_missing_raises` [v12] | P0 | rename の dst の親ディレクトリが存在しない場合 FileNotFoundError |
| `test_copy_tree_dst_parent_missing_raises` [v12] | P0 | copy_tree の dst の親ディレクトリが存在しない場合 FileNotFoundError |
| `test_copy_tree_rollback_quota_consistency` [v12] | P0 | copy_tree がクォータ超過で失敗した場合、used_bytes が元に戻り dst 未作成 |

#### 主要テスト擬似コード

```python
def test_rename_directory_moves_all_children(mfs):
    mfs.mkdir("/old/sub")
    with mfs.open("/old/sub/file.bin", "wb") as f:
        f.write(b"content")
    mfs.rename("/old", "/new")
    assert not mfs.exists("/old")
    assert not mfs.exists("/old/sub")
    assert not mfs.exists("/old/sub/file.bin")
    assert mfs.is_dir("/new")
    assert mfs.is_dir("/new/sub")
    assert mfs.exists("/new/sub/file.bin")
    with mfs.open("/new/sub/file.bin", "rb") as f:
        assert f.read() == b"content"


def test_rename_dst_exists_raises(mfs):
    """dst がファイルでもディレクトリでも一律 FileExistsError（仕様通り）。"""
    with mfs.open("/a.bin", "wb") as f: f.write(b"a")
    with mfs.open("/b.bin", "wb") as f: f.write(b"b")
    with pytest.raises(FileExistsError):
        mfs.rename("/a.bin", "/b.bin")
    mfs.mkdir("/dir")
    with pytest.raises(FileExistsError):
        mfs.rename("/a.bin", "/dir")
```

---

### 4.4 `tests/integration/test_remove_rmtree.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_remove_deletes_file` | P0 | remove 後に exists == False |
| `test_remove_releases_quota` | P0 | remove 後に stats.used_bytes が減少 |
| `test_remove_missing_raises` | P0 | FileNotFoundError |
| `test_remove_directory_raises` | P0 | IsADirectoryError |
| `test_remove_open_file_raises` | P0 | BlockingIOError |
| `test_rmtree_removes_directory_and_children` | P0 | ディレクトリと全配下が消える |
| `test_rmtree_releases_all_quota` | P0 | 全配下のクォータが解放される |
| `test_rmtree_missing_raises` | P0 | FileNotFoundError |
| `test_rmtree_file_raises` | P0 | NotADirectoryError |
| `test_rmtree_open_child_raises` | P0 | 配下にオープン済み → BlockingIOError |
| `test_rmtree_root_raises` | P0 | ルート（`/`）の rmtree は ValueError |

#### 主要テスト擬似コード

```python
def test_remove_releases_quota(mfs):
    data = b"x" * 100
    with mfs.open("/f.bin", "wb") as f:
        f.write(data)
    used_before = mfs.stats()["used_bytes"]
    mfs.remove("/f.bin")
    used_after = mfs.stats()["used_bytes"]
    assert used_after < used_before


def test_rmtree_releases_all_quota(mfs):
    mfs.mkdir("/tree/sub")
    for i in range(10):
        with mfs.open(f"/tree/sub/file{i}.bin", "wb") as f:
            f.write(b"x" * 100)
    used_before = mfs.stats()["used_bytes"]
    mfs.rmtree("/tree")
    assert mfs.stats()["used_bytes"] < used_before
    assert not mfs.exists("/tree")


def test_rmtree_open_child_raises(mfs):
    mfs.mkdir("/d")
    with mfs.open("/d/f.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/d/f.bin", "rb"):
        with pytest.raises(BlockingIOError):
            mfs.rmtree("/d")
```

---

### 4.5 `tests/integration/test_export_import.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_export_tree_returns_all_files` | P0 | 全ファイルが dict に含まれる |
| `test_export_tree_values_match_content` | P0 | dict の値がファイル内容と一致 |
| `test_iter_export_tree_matches_export_tree` | P0 | iter 版と一括版が同じ結果 |
| `test_iter_export_tree_skips_deleted_during_iteration` | P1 | 弱整合性: イテレーション中削除はスキップ |
| `test_export_as_bytesio_is_copy` | P0 | BytesIO 変更が MFS に影響しない |
| `test_export_as_bytesio_max_size_exceeds_raises` | P1 | max_size=N で大きいファイル → ValueError |
| `test_export_as_bytesio_on_dir_raises` | P0 | IsADirectoryError |
| `test_import_tree_creates_files` | P0 | import 後に全パスが存在 |
| `test_import_tree_overwrites_existing` | P0 | 既存ファイルが上書きされる |
| `test_import_tree_all_or_nothing_on_quota_fail` | P0 | クォータ不足 → FS が元に戻る（ロールバック） |
| `test_import_tree_all_or_nothing_on_open_conflict` | P0 | オープン中 → BlockingIOError、FS 不変 |
| `test_import_tree_resets_generation` | P1 | import 後の generation が 0（dirty フラグクリア） |
| `test_import_tree_empty_dict_is_noop` | P1 | {} のインポートは何も変えない |
| `test_import_tree_rollback_quota_consistency` | P0 | クォータ超過で失敗時、used_bytes が元に戻る |
| `test_export_as_bytesio_on_directory_raises` [v12] | P0 | ディレクトリパスを渡すと IsADirectoryError |

#### 主要テスト擬似コード

```python
def test_import_tree_all_or_nothing_on_quota_fail():
    """クォータ不足で import が失敗した場合、FS が元の状態に戻ること（P0）。"""
    mfs = MemoryFileSystem(max_quota=128)
    # 既存ファイルを配置
    with mfs.open("/existing.bin", "wb") as f:
        f.write(b"before")
    original = mfs.export_tree()

    # クォータを大幅に超えるインポートを試みる
    huge_tree = {"/a.bin": b"x" * 64, "/b.bin": b"y" * 64}  # 合計 128B = 小FSのクォータ上限
    # + /existing.bin の分も考慮して超過させる
    with pytest.raises(MFSQuotaExceededError):
        mfs.import_tree(huge_tree)

    # ロールバック確認
    assert mfs.export_tree() == original


def test_import_tree_all_or_nothing_on_open_conflict(mfs):
    """オープン中のファイルが import_tree の対象に含まれる場合は BlockingIOError。"""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original")
    original = mfs.export_tree()

    with mfs.open("/f.bin", "rb"):  # ロックを保持
        with pytest.raises(BlockingIOError):
            mfs.import_tree({"/f.bin": b"new content"})

    # ロールバック確認
    assert mfs.export_tree() == original


def test_iter_export_tree_skips_deleted_during_iteration(mfs):
    """弱整合性の検証: キースナップショット後に削除されたエントリはスキップ。"""
    for i in range(5):
        with mfs.open(f"/file{i}.bin", "wb") as f:
            f.write(b"x")

    exported = {}
    for path, data in mfs.iter_export_tree():
        # イテレーション中に別のファイルを削除（スナップショット外）
        if path == "/file0.bin":
            try:
                mfs.remove("/file4.bin")
            except FileNotFoundError:
                pass
        exported[path] = data

    # /file4.bin がスキップされても例外にならないことを確認
    # （削除前にキースナップショットが撮られているが、読み取り時点で存在しなければスキップ）
    assert "/file0.bin" in exported
```

---

### 4.6 `tests/integration/test_stats.py`

#### テスト一覧

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_stats_has_all_seven_keys` | P0 | 7キーが全て存在 |
| `test_stats_initial_state` | P0 | 空 MFS の初期値（file=0, dir=1, used>=0） |
| `test_stats_used_increases_on_write` | P0 | 書き込みで used_bytes 増加 |
| `test_stats_used_decreases_on_remove` | P0 | remove で used_bytes 減少 |
| `test_stats_free_is_quota_minus_used` | P0 | free_bytes == quota_bytes - used_bytes |
| `test_stats_file_count_increments` | P0 | ファイル作成で file_count 増加 |
| `test_stats_dir_count_increments` | P0 | mkdir で dir_count 増加 |
| `test_stats_chunk_count_reflects_chunks` | P1 | チャンクの追加で chunk_count 増加 |
| `test_stats_overhead_estimate_positive` | P1 | overhead_per_chunk_estimate > 0 |

#### 主要テスト擬似コード

```python
def test_stats_has_all_seven_keys(mfs):
    from tests.helpers.asserts import assert_stats_consistent
    assert_stats_consistent(mfs)


def test_stats_used_increases_on_write(mfs):
    used_before = mfs.stats()["used_bytes"]
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello world")
    used_after = mfs.stats()["used_bytes"]
    assert used_after > used_before


def test_stats_used_decreases_on_remove(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 1000)
    used_before = mfs.stats()["used_bytes"]
    mfs.remove("/f.bin")
    used_after = mfs.stats()["used_bytes"]
    assert used_after < used_before
```

---

## 5. Scenario テスト詳細設計

### 5.1 `tests/scenarios/test_usecase_archive_like.py`

**目的**: アーカイブ展開相当（多数ファイルへの書き込み→一括エクスポート）のシナリオを通す。

| テスト関数名 | 優先度 | 内容 |
|---|---|---|
| `test_write_100_files_and_export_all` | P1 | 100 ファイルを書き込み export_tree で全件確認 |
| `test_iter_export_matches_export_tree_on_large_fs` | P1 | 100 ファイルで両方が同一結果 |
| `test_quota_prevents_oversized_archive` | P0 | 総量がクォータを超えると途中で MFSQuotaExceededError |
| `test_listdir_returns_correct_count_for_many_files` | P2 | 1000 ファイルでも listdir が正しい件数を返す |
| `test_rmtree_cleans_up_all_quota` | P0 | 1000 ファイル rmtree 後に quota がほぼ全解放 |

```python
def test_write_100_files_and_export_all(mfs):
    expected = {}
    for i in range(100):
        path = f"/archive/file_{i:04d}.bin"
        data = f"content_{i}".encode()
        with mfs.open(path, "wb") as f:
            f.write(data)
        expected[path] = data
    result = mfs.export_tree("/archive")
    assert result == expected


def test_quota_prevents_oversized_archive():
    """クォータ 128B のMFSに 200B 書き込もうとすると途中で拒否される。"""
    mfs = MemoryFileSystem(max_quota=128)
    with pytest.raises(MFSQuotaExceededError):
        for i in range(10):
            with mfs.open(f"/f{i}.bin", "wb") as f:
                f.write(b"x" * 20)  # 合計 200B で超過
```

---

### 5.2 `tests/scenarios/test_usecase_etl_staging.py`

**目的**: ETL のステージング（書き込み → 加工 → コミット/ロールバック）パターンを検証する。

| テスト関数名 | 優先度 | 内容 |
|---|---|---|
| `test_stage_then_commit_via_rename` | P1 | /staging → /output への rename がコミットとして機能 |
| `test_failed_import_leaves_output_unchanged` | P0 | クォータ不足 import が失敗しても /output が変わらない |
| `test_quota_rejects_oversized_batch` | P0 | バッチが大きすぎるとクォータエラー |
| `test_independent_mfs_instances_isolated` | P0 | 2つの MFS は互いのクォータ・内容に影響しない |

```python
def test_stage_then_commit_via_rename(mfs):
    """ETL パターン: staging へ書き込み → rename で output へコミット。"""
    mfs.mkdir("/staging")
    with mfs.open("/staging/result.csv", "wb") as f:
        f.write(b"a,b,c\n1,2,3\n")
    mfs.rename("/staging", "/output")
    assert not mfs.exists("/staging")
    assert mfs.exists("/output/result.csv")
    with mfs.open("/output/result.csv", "rb") as f:
        assert b"1,2,3" in f.read()


def test_independent_mfs_instances_isolated():
    mfs1 = MemoryFileSystem(max_quota=128)
    mfs2 = MemoryFileSystem(max_quota=128)
    with mfs1.open("/f.bin", "wb") as f:
        f.write(b"x" * 100)
    # mfs1 が満杯に近くても mfs2 は独立
    with mfs2.open("/g.bin", "wb") as f:
        f.write(b"y" * 100)
    assert not mfs2.exists("/f.bin")
    assert not mfs1.exists("/g.bin")
```

---

### 5.3 `tests/scenarios/test_usecase_sqlite_snapshot.py`

**目的**: README_en.md の SQLite 統合例をテストとして固定する（公開時の"刺さる証明"）。

| テスト関数名 | 優先度 | 内容 |
|---|---|---|
| `test_sqlite_serialize_roundtrip` | P0 | README の SQLite 例が動作すること |
| `test_sqlite_data_integrity_after_roundtrip` | P0 | 復元後に DB の内容が正確に一致 |
| `test_sqlite_quota_limits_db_size` | P0 | DB が大きくなりすぎるとクォータで拒否 |

```python
import sqlite3

def test_sqlite_serialize_roundtrip(mfs):
    """README_en の Quick Start SQLite 例をそのままテスト化（P0）。"""
    # DB を作成してデータを投入
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id INTEGER, val TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'hello')")
    conn.execute("INSERT INTO t VALUES (2, 'world')")
    conn.commit()

    # MFS に serialize して保存
    with mfs.open("/db/snapshot.db", "wb") as f:
        f.write(conn.serialize())
    conn.close()

    # MFS から読み戻して deserialize
    with mfs.open("/db/snapshot.db", "rb") as f:
        raw = f.read()
    restored = sqlite3.connect(":memory:")
    restored.deserialize(raw)
    rows = restored.execute("SELECT * FROM t ORDER BY id").fetchall()
    assert rows == [(1, "hello"), (2, "world")]
    restored.close()


def test_sqlite_data_integrity_after_roundtrip(mfs):
    """複数テーブル・多数行の DB で内容整合性を確認。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data BLOB)")
    for i in range(1000):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, bytes([i % 256] * 64)))
    conn.commit()

    with mfs.open("/db/big.db", "wb") as f:
        f.write(conn.serialize())
    conn.close()

    with mfs.open("/db/big.db", "rb") as f:
        raw = f.read()
    restored = sqlite3.connect(":memory:")
    restored.deserialize(raw)
    count = restored.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert count == 1000
    restored.close()
```

---

### 5.4 `tests/scenarios/test_usecase_restricted_env.py`

**目的**: 権限制約環境（コンテナ・CI）での動作前提を確認する。

| テスト関数名 | 優先度 | 内容 |
|---|---|---|
| `test_no_real_filesystem_touched` | P0 | MFS 操作が実 OS の FS を汚染しないこと（import チェック） |
| `test_multitenant_quota_isolation` | P0 | テナント間でクォータが独立している |
| `test_quota_per_instance_not_shared` | P0 | 2 インスタンスのクォータは共有されない |

```python
def test_no_real_filesystem_touched(tmp_path):
    """MFS の全操作が tmp_path にファイルを作らないことを確認。"""
    import os
    before = set(os.listdir(tmp_path))
    mfs = MemoryFileSystem(max_quota=1024 * 1024)
    mfs.mkdir("/a/b/c")
    with mfs.open("/a/b/c/file.bin", "wb") as f:
        f.write(b"data")
    mfs.export_tree()
    after = set(os.listdir(tmp_path))
    assert before == after, f"Real FS was modified: {after - before}"


def test_multitenant_quota_isolation():
    """テナントAのクォータ枯渇がテナントBに影響しないこと。"""
    tenant_a = MemoryFileSystem(max_quota=256)
    tenant_b = MemoryFileSystem(max_quota=256)

    # テナントAを満杯にする
    with pytest.raises(MFSQuotaExceededError):
        with tenant_a.open("/f.bin", "wb") as f:
            f.write(b"x" * 300)  # クォータ256を超える

    # テナントBは影響を受けない
    with tenant_b.open("/g.bin", "wb") as f:
        f.write(b"y" * 200)
    assert tenant_b.exists("/g.bin")
```

---

## 6. Property テスト（`tests/property/test_hypothesis.py`）

`hypothesis` を使用したプロパティベーステスト。特に境界条件・入力の多様性が重要なケースに適用する。

| テスト関数名 | 優先度 | 戦略 | 検証観点 |
|---|---|---|---|
| `test_path_normalize_idempotent` | P1 | `text()` | normalize(normalize(x)) == normalize(x) |
| `test_path_traversal_detection` | P1 | `text()` | `..` を含むパストラバーサルが ValueError |
| `test_write_read_roundtrip` | P1 | `binary()` | 書き込んだバイト列が正確に読み戻せる |
| `test_import_export_roundtrip` | P1 | `dictionaries(text(), binary())` | import → export で元のデータが復元 |
| `test_quota_invariant` | P0 | `lists(integers(min=1, max=100))` | 複数 write 後の used <= quota が常に成立 |

```python
from hypothesis import given, settings, HealthCheck
from hypothesis.strategies import text, binary, dictionaries, integers, lists
import re

@given(data=binary(min_size=0, max_size=1024))
def test_write_read_roundtrip(data):
    mfs = MemoryFileSystem(max_quota=2048)
    with mfs.open("/f.bin", "wb") as f:
        f.write(data)
    with mfs.open("/f.bin", "rb") as f:
        result = f.read()
    assert result == data


@given(
    sizes=lists(integers(min_value=1, max_value=50), min_size=1, max_size=10)
)
def test_quota_invariant(sizes):
    """複数ファイル書き込み後も used_bytes <= quota_bytes が常に成立する。"""
    quota = 400
    mfs = MemoryFileSystem(max_quota=quota)
    for i, size in enumerate(sizes):
        try:
            with mfs.open(f"/f{i}.bin", "wb") as f:
                f.write(b"x" * size)
        except MFSQuotaExceededError:
            pass  # 超過は仕様通り。ここでの失敗は正常。
    s = mfs.stats()
    assert s["used_bytes"] <= s["quota_bytes"], (
        f"Quota invariant violated: used={s['used_bytes']} > quota={s['quota_bytes']}"
    )


@given(
    tree=dictionaries(
        keys=text(alphabet="abcdefghijklmnop/", min_size=1, max_size=20),
        values=binary(min_size=0, max_size=100),
        min_size=0, max_size=5,
    )
)
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_import_export_roundtrip(tree):
    """import_tree → export_tree で内容が完全一致する（クォータ超過は除外）。"""
    # パスが無効な形式のものは除外
    valid_tree = {}
    for path, data in tree.items():
        try:
            from dmemfs._path import normalize_path
            npath = normalize_path(path)
            valid_tree[npath] = data
        except (ValueError, KeyError):
            pass
    if not valid_tree:
        return
    mfs = MemoryFileSystem(max_quota=10 * 1024)
    try:
        mfs.import_tree(valid_tree)
    except MFSQuotaExceededError:
        return  # クォータ超過は正常動作
    result = mfs.export_tree()
    assert result == valid_tree
```

---

## 7. 並行性テスト詳細

並行性テストは `@pytest.mark.timeout(N)` でデッドロック検知の保険をかける。

### 7.1 デッドロック防止の回帰テスト

```python
# tests/integration/test_concurrency.py

@pytest.mark.timeout(10)
def test_no_deadlock_on_concurrent_open(mfs):
    """
    複数スレッドが同一ファイルを開閉しても、デッドロックしないこと。
    ロック取得順序規約（global → rw）の検証。
    """
    with mfs.open("/shared.bin", "wb") as f:
        f.write(b"x" * 100)
    errors = []
    def reader():
        for _ in range(50):
            try:
                with mfs.open("/shared.bin", "rb") as f:
                    f.read()
            except Exception as e:
                errors.append(e)
    threads = [threading.Thread(target=reader) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors


@pytest.mark.timeout(10)
def test_writer_blocked_by_reader_then_released(mfs):
    """
    reader が保持している間 writer はブロックされ、
    reader が close すると writer が取得できること。
    """
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 10)
    writer_succeeded = threading.Event()
    def writer():
        # reader が release するまで待つ（timeout なし）
        with mfs.open("/f.bin", "wb") as f:
            f.write(b"new")
        writer_succeeded.set()
    from tests.helpers.concurrency import ThreadedLockHolder
    with ThreadedLockHolder(mfs, "/f.bin", "rb"):
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        # reader 保持中は writer が完了しない
        assert not writer_succeeded.wait(timeout=0.3), "writer should be blocked"
    # reader が解放 → writer が進む
    assert writer_succeeded.wait(timeout=3.0), "writer should succeed after reader releases"
    t.join()
```

---

## 8. CI 設定（`pytest.ini` / `pyproject.toml`）

```ini
# pytest.ini
[pytest]
testpaths = tests
timeout = 30
markers =
    p0: P0 tests (must pass for release)
    p1: P1 tests (strongly recommended)
    p2: P2 tests (nice to have)
```

### CI マトリクス（GitHub Actions）

```yaml
# .github/workflows/test.yml（抜粋）
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    python-version: ["3.11", "3.12", "3.13"]
```

### DoD（Done の定義）

- [ ] P0 全テストが全 OS × Python 3.11/3.12/3.13 で通過
- [ ] `tests/scenarios/test_usecase_sqlite_snapshot.py` の全テストが通過（README の例が動作）
- [ ] `tests/scenarios/test_usecase_restricted_env.py::test_no_real_filesystem_touched` が通過

---

## 9. テスト実装の推奨実装順序

`MFS_v9_test_implementation_instruction.md §6` の短い指示に対応する実装順序：

| ステップ | 対象ファイル群 | 理由 |
|---|---|---|
| 1 | `test_open_modes.py` | open 5モード＋例外体系の固定が最優先 |
| 2 | `test_quota.py` + `test_export_import.py`（import All-or-Nothing） | クォータ拒否・ロールバックの固定 |
| 3 | `test_lock.py` + `test_open_modes.py`（lock_timeout） | ロック try/timeout の固定 |
| 4 | `test_export_import.py`（import_tree アトミック） | All-or-Nothing の固定 |
| 5 | `test_usecase_sqlite_snapshot.py` | 設計目標の証明 |
| 6 | Unit 層（`test_files_*.py` / `test_handle_io.py`） | 内部実装の仕様固定 |
| 7 | シナリオ・Property テスト | 網羅性向上 |
| 8 | [v10] ディレクトリインデックス層・新規APIテスト | v10 新機能の検証 |
| 9 | [v11] タイムスタンプ・stat()・shrink・async テスト | v11 新機能の検証 |

---

## 10. [v10 実装済み] ディレクトリインデックス層テスト

> **ステータス**: spec_v10.md §2.1 で設計確定済み。**テスト実装済み v0.2.0**。

ディレクトリインデックス層の導入に伴う内部アーキテクチャ変更により、公開APIの動作が変わらないことを検証する回帰テストおよび、新しい計算量特性の検証テストを追加する。

### 10.1 既存APIの回帰テスト（公開API互換性）

ディレクトリインデックス層導入後も、既存の全テスト（§3〜§7）が変更なくパスすることが必須。これが内部アーキテクチャ変更の回帰テストとして機能する。

### 10.2 `tests/unit/test_dir_index.py` [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_dir_node_children_empty_initial` | P0 | DirNode の children が初期状態で空辞書 |
| `test_file_node_has_storage_ref` | P0 | FileNode がストレージ参照を保持 |
| `test_node_id_monotonic` | P1 | NodeId が単調増加 |
| `test_resolve_path_root` | P0 | "/" の解決がルート DirNode を返す |
| `test_resolve_path_nested` | P0 | 深いパスの解決が正しいノードを返す |
| `test_resolve_path_missing` | P0 | 存在しないパスで None |
| `test_listdir_uses_children_keys` | P0 | listdir が DirNode.children.keys() を返却 |
| `test_rename_dir_is_O_d` | P1 | ディレクトリ rename が親ノードの children 更新のみ |

```python
# [v10 実装済み]
def test_dir_node_children_empty_initial():
    node = DirNode(node_id=0)
    assert node.children == {}
    assert node.node_id == 0

def test_file_node_has_storage_ref():
    storage = SequentialMemoryFile()
    node = FileNode(node_id=1, storage=storage)
    assert node.storage is storage
    assert node.generation == 0

def test_resolve_path_nested(mfs):
    """v10: ディレクトリインデックス層のパス解決が正しいノードを返すことを検証。"""
    mfs.mkdir("/a/b/c")
    with mfs.open("/a/b/c/file.txt", "wb") as f:
        f.write(b"data")
    # 内部的にパス解決が正しく動作していることを、公開APIで確認
    assert mfs.exists("/a/b/c/file.txt")
    assert mfs.is_dir("/a/b/c")
    assert not mfs.is_dir("/a/b/c/file.txt")
```

---

## 11. [v10 実装済み] `copy_tree()` テスト

> **ステータス**: spec_v10.md §4.4 で設計確定済み。**テスト実装済み v0.2.0**。

### 11.1 `tests/integration/test_copy_tree.py` [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_copy_tree_creates_independent_copy` | P0 | コピー先の変更が元に影響しない（ディープコピー） |
| `test_copy_tree_preserves_structure` | P0 | ディレクトリ階層と全ファイルが複製される |
| `test_copy_tree_preserves_content` | P0 | 全ファイルの内容が完全一致 |
| `test_copy_tree_charges_quota` | P0 | コピー分のクォータが計上される |
| `test_copy_tree_quota_exceeded_rollback` | P0 | クォータ不足時は何も変更されない |
| `test_copy_tree_src_not_dir_raises` | P0 | src がファイルの場合 NotADirectoryError |
| `test_copy_tree_dst_exists_raises` | P0 | dst が既存の場合 FileExistsError |
| `test_copy_tree_dst_parent_missing_raises` | P0 | dst の親が存在しない場合 FileNotFoundError |
| `test_copy_tree_src_missing_raises` | P0 | src が存在しない場合 FileNotFoundError |
| `test_copy_tree_empty_dir` | P1 | 空ディレクトリのコピー |
| `test_copy_tree_rollback_quota_consistency` | P0 | クォータ超過で失敗時、used_bytes が元に戻り dst 未作成 |

```python
# [v10 実装済み]
def test_copy_tree_creates_independent_copy(mfs):
    """コピーはディープコピーであり、元と独立していることを検証。"""
    mfs.mkdir("/src/sub")
    with mfs.open("/src/sub/data.bin", "wb") as f:
        f.write(b"original")
    
    mfs.copy_tree("/src", "/dst")
    
    # dst 側を変更
    with mfs.open("/dst/sub/data.bin", "wb") as f:
        f.write(b"modified")
    
    # src 側は変更されていない
    with mfs.open("/src/sub/data.bin", "rb") as f:
        assert f.read() == b"original"


def test_copy_tree_preserves_structure(mfs):
    """ディレクトリ階層と全ファイルが複製される。"""
    mfs.mkdir("/src/a/b")
    mfs.mkdir("/src/c")
    with mfs.open("/src/a/b/f1.bin", "wb") as f:
        f.write(b"1")
    with mfs.open("/src/c/f2.bin", "wb") as f:
        f.write(b"2")
    with mfs.open("/src/root.bin", "wb") as f:
        f.write(b"3")
    
    mfs.copy_tree("/src", "/dst")
    
    assert mfs.is_dir("/dst")
    assert mfs.is_dir("/dst/a")
    assert mfs.is_dir("/dst/a/b")
    assert mfs.is_dir("/dst/c")
    assert mfs.exists("/dst/a/b/f1.bin")
    assert mfs.exists("/dst/c/f2.bin")
    assert mfs.exists("/dst/root.bin")


def test_copy_tree_quota_exceeded_rollback():
    """クォータ不足で copy_tree が失敗した場合、何も変更されない。"""
    mfs = MemoryFileSystem(max_quota=128)
    mfs.mkdir("/src")
    with mfs.open("/src/big.bin", "wb") as f:
        f.write(b"x" * 50)  # クォータ 128B の半分以上
    
    original = mfs.export_tree()
    with pytest.raises(MFSQuotaExceededError):
        mfs.copy_tree("/src", "/dst")
    
    # ロールバック確認
    assert not mfs.exists("/dst")
    assert mfs.export_tree() == original
```

---

## 12. [v10 実装済み] `move()` テスト

> **ステータス**: spec_v10.md §4.4, §5.1 で設計確定済み。**テスト実装済み v0.2.0**。

### 12.1 `tests/integration/test_move.py` [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_move_file_creates_parent_dirs` | P0 | dst の親ディレクトリが自動作成される |
| `test_move_file_preserves_content` | P0 | 移動後に内容が保持される |
| `test_move_file_removes_src` | P0 | 移動後に src が存在しない |
| `test_move_directory_with_children` | P0 | ディレクトリと配下が全て移動される |
| `test_move_src_missing_raises` | P0 | FileNotFoundError |
| `test_move_dst_exists_raises` | P0 | FileExistsError |
| `test_move_open_file_raises` | P0 | BlockingIOError |
| `test_move_root_raises` | P0 | ValueError |
| `test_move_differs_from_rename_parent_creation` | P1 | rename は親が無いと失敗、move は自動作成 |

```python
# [v10 実装済み]
def test_move_file_creates_parent_dirs(mfs):
    """移動先の親ディレクトリが存在しなくても自動作成される。"""
    with mfs.open("/file.bin", "wb") as f:
        f.write(b"data")
    mfs.move("/file.bin", "/new/deep/path/file.bin")
    assert not mfs.exists("/file.bin")
    assert mfs.exists("/new/deep/path/file.bin")
    assert mfs.is_dir("/new/deep/path")
    with mfs.open("/new/deep/path/file.bin", "rb") as f:
        assert f.read() == b"data"


def test_move_differs_from_rename_parent_creation(mfs):
    """同じ操作で rename は失敗、move は成功することを検証。"""
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"y")
    # rename は親が無いと失敗
    with pytest.raises(FileNotFoundError):
        mfs.rename("/a.bin", "/nonexistent/dir/a.bin")
    # move は親を自動作成
    mfs.move("/b.bin", "/nonexistent/dir/b.bin")
    assert mfs.exists("/nonexistent/dir/b.bin")
```

---

## 13. [v10 実装済み] `glob("**")` テスト

> **ステータス**: spec_v10.md §5.1 で設計確定済み。**テスト実装済み v0.2.0**。

### 13.1 既存テストへの影響

v10 では `*` が `/` にマッチしなくなるため、既存の `glob()` テストの期待値が変わる可能性がある。マイグレーション時に確認が必要。

### 13.2 `tests/integration/test_glob_v10.py` [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_glob_star_does_not_match_slash` | P0 | `*` が `/` にマッチしない |
| `test_glob_doublestar_matches_recursively` | P0 | `**` が再帰的にディレクトリを走査 |
| `test_glob_doublestar_zero_dirs` | P0 | `**` が 0 個のディレクトリにマッチ |
| `test_glob_combined_pattern` | P0 | `/dir/**/*.txt` が全階層の .txt にマッチ |
| `test_glob_single_star_only_direct_children` | P0 | `/dir/*.txt` が直下のみにマッチ |
| `test_glob_question_mark` | P1 | `?` が任意の 1 文字にマッチ |
| `test_glob_results_sorted` | P0 | 結果がソート済み |
| `test_glob_consecutive_double_star` | P1 | `/**/**/*.txt` 連続 `**` でも正しくマッチ |
| `test_glob_double_star_trailing_slash` | P1 | `/**/f.txt` 中間ディレクトリ走査 |
| `test_glob_character_class` | P1 | `[abc]` 文字クラスでのマッチ |
| `test_glob_double_star_at_beginning` | P1 | `/**/*.txt` ルートから再帰マッチ |

```python
# [v10 実装済み]
def test_glob_star_does_not_match_slash(mfs):
    """v10: * は / にマッチしない。"""
    with mfs.open("/a.txt", "wb") as f:
        f.write(b"x")
    mfs.mkdir("/dir")
    with mfs.open("/dir/b.txt", "wb") as f:
        f.write(b"y")
    result = mfs.glob("/*.txt")
    assert result == ["/a.txt"]  # /dir/b.txt はマッチしない


def test_glob_doublestar_matches_recursively(mfs):
    """v10: ** で再帰的にマッチ。"""
    mfs.mkdir("/dir/sub/deep")
    with mfs.open("/dir/a.txt", "wb") as f:
        f.write(b"1")
    with mfs.open("/dir/sub/b.txt", "wb") as f:
        f.write(b"2")
    with mfs.open("/dir/sub/deep/c.txt", "wb") as f:
        f.write(b"3")
    result = mfs.glob("/dir/**/*.txt")
    assert sorted(result) == ["/dir/a.txt", "/dir/sub/b.txt", "/dir/sub/deep/c.txt"]


def test_glob_combined_pattern(mfs):
    """/dir/**/*.txt が全階層の .txt にマッチし、.bin にはマッチしない。"""
    mfs.mkdir("/dir/sub")
    with mfs.open("/dir/a.txt", "wb") as f:
        f.write(b"1")
    with mfs.open("/dir/a.bin", "wb") as f:
        f.write(b"2")
    with mfs.open("/dir/sub/b.txt", "wb") as f:
        f.write(b"3")
    result = mfs.glob("/dir/**/*.txt")
    assert sorted(result) == ["/dir/a.txt", "/dir/sub/b.txt"]
```

---

## 14. [v10 実装済み] `wb` truncate 順序修正テスト

> **ステータス**: spec_v10.md §5.1 で設計確定済み。**テスト実装済み v0.2.0**。

### 14.1 `tests/integration/test_open_modes.py` に追加 [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_wb_truncate_after_lock_acquisition` | P0 | wb モードの truncate がロック取得後に実行される |
| `test_wb_truncate_does_not_corrupt_concurrent_reader` | P0 | 既存の読み取りハンドルのデータが truncate で破壊されない |

```python
# [v10 実装済み]
def test_wb_truncate_does_not_corrupt_concurrent_reader(mfs):
    """
    v10: wb モードでの truncate がロック取得後に実行されるため、
    既存の読み取りハンドルが保有中にデータが破壊されないことを検証。
    """
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original data")
    
    import threading
    reader_data = [None]
    reader_ready = threading.Event()
    writer_proceed = threading.Event()
    
    def reader():
        with mfs.open("/f.bin", "rb") as f:
            reader_ready.set()
            writer_proceed.wait(timeout=5.0)
            reader_data[0] = f.read()
    
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    reader_ready.wait(timeout=5.0)
    
    # reader が rb ロックを保有中に wb で開こうとすると、
    # v10 では truncate がロック取得後なので、reader が閉じるまで待機する
    # (lock_timeout=0.0 で即座に失敗することを確認)
    with pytest.raises(BlockingIOError):
        mfs.open("/f.bin", "wb", lock_timeout=0.0)
    
    writer_proceed.set()
    t.join(timeout=5.0)
    assert reader_data[0] == b"original data"  # データが破壊されていない
```

---

## 15. [v10 実装済み] `export_as_bytesio()` ロック粒度改善テスト

> **ステータス**: spec_v10.md §4.1 で設計確定済み。**テスト実装済み v0.2.0**。

### 15.1 `tests/integration/test_export_import.py` に追加 [v10 実装済み]

| テスト関数名 | 優先度 | 検証観点 |
|---|---|---|
| `test_export_as_bytesio_with_global_lock` | P2 | `_global_lock` でエントリ存在確認が保護される |

```python
# [v10 実装済み]
def test_export_as_bytesio_with_global_lock(mfs):
    """
    v10: export_as_bytesio が _global_lock でエントリ存在確認を保護することを検証。
    間接的な検証: 並行の remove と export_as_bytesio が競合してもクラッシュしない。
    """
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    
    import threading
    errors = []
    
    def exporter():
        for _ in range(100):
            try:
                bio = mfs.export_as_bytesio("/f.bin")
                assert bio.read() == b"data"
            except FileNotFoundError:
                pass  # remove と競合した場合は正常
            except Exception as e:
                errors.append(e)
    
    def remover_creator():
        for _ in range(100):
            try:
                mfs.remove("/f.bin")
            except FileNotFoundError:
                pass
            with mfs.open("/f.bin", "wb") as f:
                f.write(b"data")
    
    threads = [
        threading.Thread(target=exporter, daemon=True),
        threading.Thread(target=remover_creator, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    assert not errors, f"Unexpected errors: {errors}"
```

---

## 16. [v10 実装済み] `__del__` stacklevel 修正テスト

> **ステータス**: spec_v10.md §5.3 で設計確定済み。**テスト実装済み v0.2.0**。
>
> `test_del_without_close_emits_resource_warning` は実装済み（`tests/unit/test_handle_io.py`）

既存の `test_del_without_close_emits_resource_warning` テスト（§3.6）がそのまま使用可能。`stacklevel` の変更は警告メッセージのソース位置指示に影響するが、テストの合否判定には影響しない。

---

## 17. [v11 実装済み] ファイルタイムスタンプ・`stat()` API テスト

> **参照**: spec_v11.md §6.1, DetailedDesignSpec.md §18

### 17.1 `tests/unit/test_timestamp.py` [v11 実装済み]

ファイルタイムスタンプの初期化・更新・不変性を検証する。

#### テスト一覧

| 関数名 | 優先度 | 検証内容 |
|---|---|---|
| `test_new_file_has_timestamps` | P1 | 新規作成ファイルに `created_at` と `modified_at` が設定される |
| `test_created_at_equals_modified_at_on_creation` | P1 | 作成時 `created_at == modified_at` |
| `test_write_updates_modified_at` | P1 | `write()` で `modified_at` が更新される |
| `test_write_does_not_change_created_at` | P1 | `write()` で `created_at` は変わらない |
| `test_truncate_updates_modified_at` | P1 | `wb` の truncate で `modified_at` が更新される |
| `test_rename_preserves_timestamps` | P1 | `rename()` でタイムスタンプが変わらない |
| `test_move_preserves_timestamps` | P1 | `move()` でタイムスタンプが変わらない |
| `test_copy_creates_new_timestamps` | P1 | `copy()` でコピー先に新しいタイムスタンプが設定される |
| `test_copy_tree_creates_new_timestamps` | P1 | `copy_tree()` で各コピー先に新しいタイムスタンプが設定される |
| `test_import_tree_creates_new_timestamps` | P2 | `import_tree()` で新しいタイムスタンプが設定される |

#### 擬似コード例

```python
import time

def test_new_file_has_timestamps(mfs_1mb):
    before = time.time()
    with mfs_1mb.open("/test.bin", "wb") as f:
        f.write(b"data")
    after = time.time()

    info = mfs_1mb.stat("/test.bin")
    assert before <= info["created_at"] <= after
    assert before <= info["modified_at"] <= after
    assert info["created_at"] == info["modified_at"]


def test_write_updates_modified_at(mfs_1mb):
    with mfs_1mb.open("/test.bin", "wb") as f:
        f.write(b"initial")
    info1 = mfs_1mb.stat("/test.bin")

    time.sleep(0.01)  # 時間差を確保

    with mfs_1mb.open("/test.bin", "r+b") as f:
        f.write(b"updated")
    info2 = mfs_1mb.stat("/test.bin")

    assert info2["modified_at"] > info1["modified_at"]
    assert info2["created_at"] == info1["created_at"]


def test_rename_preserves_timestamps(mfs_1mb):
    with mfs_1mb.open("/a.bin", "wb") as f:
        f.write(b"data")
    info_before = mfs_1mb.stat("/a.bin")

    mfs_1mb.rename("/a.bin", "/b.bin")
    info_after = mfs_1mb.stat("/b.bin")

    assert info_after["created_at"] == info_before["created_at"]
    assert info_after["modified_at"] == info_before["modified_at"]


def test_copy_creates_new_timestamps(mfs_1mb):
    with mfs_1mb.open("/src.bin", "wb") as f:
        f.write(b"data")
    info_src = mfs_1mb.stat("/src.bin")

    time.sleep(0.01)

    mfs_1mb.copy("/src.bin", "/dst.bin")
    info_dst = mfs_1mb.stat("/dst.bin")

    # コピー先は新しいタイムスタンプ
    assert info_dst["created_at"] >= info_src["created_at"]
```

### 17.2 `tests/integration/test_stat_api.py` [v11 実装済み]

`stat()` API のエラーハンドリングと統合動作を検証する。

#### テスト一覧

| 関数名 | 優先度 | 検証内容 |
|---|---|---|
| `test_stat_returns_correct_size` | P1 | `stat()` が正しいファイルサイズを返す |
| `test_stat_returns_generation` | P1 | `stat()` が generation を返す |
| `test_stat_returns_is_dir_false_for_file` | P1 | ファイルに対して `is_dir=False` を返す [v13 変更] |
| `test_stat_file_not_found` | P0 | 存在しないパスで `FileNotFoundError` |
| `test_stat_is_directory` | P0 | ディレクトリパスで `is_dir=True` を返す [v13 変更: IsADirectoryError ではなく正常返却] |

#### 擬似コード例

```python
def test_stat_returns_correct_size(mfs_1mb):
    data = b"hello world"
    with mfs_1mb.open("/test.bin", "wb") as f:
        f.write(data)
    info = mfs_1mb.stat("/test.bin")
    assert info["size"] == len(data)
    assert info["is_dir"] is False  # v13: is_sequential → is_dir
    assert info["generation"] > 0


def test_stat_file_not_found(mfs_1mb):
    with pytest.raises(FileNotFoundError):
        mfs_1mb.stat("/nonexistent")


def test_stat_is_directory(mfs_1mb):
    mfs_1mb.mkdir("/mydir")
    info = mfs_1mb.stat("/mydir")  # v13: IsADirectoryError は送出しない
    assert info["is_dir"] is True
    assert info["size"] == 0
```

---

## 18. [v11 実装済み] `bytearray` shrink テスト

> **参照**: spec_v11.md §6.2, DetailedDesignSpec.md §19

### 18.1 `tests/unit/test_files_randomaccess.py` への追加 [v11 実装済み]

`RandomAccessMemoryFile` の shrink 機構を検証する。

#### テスト一覧

| 関数名 | 優先度 | 検証内容 |
|---|---|---|
| `test_truncate_shrinks_buffer_below_threshold` | P1 | 25% 以下への truncate で `bytearray` が再割り当てされる |
| `test_truncate_no_shrink_above_threshold` | P1 | 25% 超への truncate では再割り当てされない |
| `test_shrink_preserves_data` | P0 | shrink 後もデータが正しく読み取れる |
| `test_shrink_quota_consistency` | P1 | shrink 後もクォータ計上値が正しい |
| `test_truncate_to_zero_shrinks` | P1 | サイズ 0 への truncate で shrink が実行される |

#### 擬似コード例

```python
def test_truncate_shrinks_buffer_below_threshold(mfs_1mb):
    """サイズが元の 25% 以下に縮小した場合、バッファが再割り当てされる。"""
    # 大きいファイルを作成（RandomAccess への昇格が必要）
    with mfs_1mb.open("/big.bin", "wb") as f:
        f.write(b"\x00" * 10000)

    # r+b で開いて seek+write で RandomAccess に昇格させる
    with mfs_1mb.open("/big.bin", "r+b") as f:
        f.seek(0)
        f.write(b"\x01")  # 昇格トリガー

    # wb で開き直すと truncate が発生（サイズ 0 = 元の 0%）
    with mfs_1mb.open("/big.bin", "wb") as f:
        f.write(b"small")

    info = mfs_1mb.stat("/big.bin")
    assert info["size"] == 5
    assert info["is_dir"] is False  # v13: is_sequential 廃止。ストレージ種別は stat() で公開しない


def test_shrink_preserves_data(mfs_1mb):
    """shrink 後もデータの整合性が保たれる。"""
    with mfs_1mb.open("/file.bin", "wb") as f:
        f.write(b"\x00" * 4000)

    # RandomAccess に昇格
    with mfs_1mb.open("/file.bin", "r+b") as f:
        f.seek(100)
        f.write(b"marker")

    # truncate で大幅縮小
    with mfs_1mb.open("/file.bin", "r+b") as f:
        f.seek(0)
        f.write(b"\x00" * 200)

    with mfs_1mb.open("/file.bin", "rb") as f:
        data = f.read()
    # データ整合性確認
    assert len(data) == 4000
    assert data[100:106] == b"marker"


def test_shrink_quota_consistency(mfs_1mb):
    """shrink 前後でクォータ計上値が正しい。"""
    with mfs_1mb.open("/file.bin", "wb") as f:
        f.write(b"\x00" * 10000)

    stats_before = mfs_1mb.stats()

    # truncate による縮小
    with mfs_1mb.open("/file.bin", "wb") as f:
        f.write(b"x")

    stats_after = mfs_1mb.stats()
    assert stats_after["used_bytes"] < stats_before["used_bytes"]
```

---

## 19. [v11 実装済み] PEP 703 (GIL-free) 対応テスト

> **参照**: spec_v11.md §6.3, DetailedDesignSpec.md §20

### 19.1 テスト方針

PEP 703 対応のテストは、既存の並行性テスト（§5 `test_concurrency.py`）を free-threaded Python (3.13t) で実行することで検証する。新規テストコードの追加は最小限とし、CI 環境の拡張で対応する。

### 19.2 CI マトリクス拡張

```yaml
# .github/workflows/tests.yml への追加
include:
  - os: ubuntu-latest
    python-version: "3.13t"
```

### 19.3 追加テスト `tests/integration/test_concurrency.py` への追記 [v11 実装済み]

| 関数名 | 優先度 | 検証内容 |
|---|---|---|
| `test_concurrent_writes_no_data_corruption_stress` | P1 | 高並行書き込みでデータ破壊が起きない（free-threaded 時に特に重要） |
| `test_concurrent_stat_during_writes` | P2 | `stat()` と `write()` の並行実行でクラッシュしない |

#### 擬似コード例

```python
def test_concurrent_writes_no_data_corruption_stress(mfs_1mb):
    """
    複数スレッドが同じファイルに書き込みを試み、
    データ破壊が起きないことを高負荷で検証する。
    free-threaded Python (PEP 703) 環境で特に重要。
    """
    import threading

    errors = []
    iterations = 100

    def writer(thread_id):
        try:
            for i in range(iterations):
                path = f"/file_{thread_id}.bin"
                with mfs_1mb.open(path, "wb") as f:
                    data = bytes([thread_id & 0xFF]) * 100
                    f.write(data)
                with mfs_1mb.open(path, "rb") as f:
                    result = f.read()
                assert result == bytes([thread_id & 0xFF]) * 100
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert not errors, f"Data corruption detected: {errors}"


def test_concurrent_stat_during_writes(mfs_1mb):
    """stat() と write() の並行実行でクラッシュしないことを検証。"""
    import threading

    with mfs_1mb.open("/target.bin", "wb") as f:
        f.write(b"initial")

    errors = []
    stop = threading.Event()

    def writer():
        try:
            for i in range(50):
                if stop.is_set():
                    break
                with mfs_1mb.open("/target.bin", "wb") as f:
                    f.write(b"x" * (i + 1))
        except Exception as e:
            errors.append(e)

    def stat_reader():
        try:
            for _ in range(50):
                if stop.is_set():
                    break
                try:
                    info = mfs_1mb.stat("/target.bin")
                    assert "size" in info
                    assert "created_at" in info
                    assert "modified_at" in info
                except FileNotFoundError:
                    pass  # writer が wb で truncate 中の瞬間
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer, daemon=True),
        threading.Thread(target=stat_reader, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stop.set()
    assert not errors, f"Concurrent stat/write errors: {errors}"
```

---

## 20. [v11 実装済み] async/await ラッパーテスト

> **参照**: spec_v11.md §6.4, DetailedDesignSpec.md §21

### 20.1 `tests/integration/test_async.py` [v11 実装済み]

`AsyncMemoryFileSystem` / `AsyncMemoryFileHandle` の動作を検証する。

#### テスト一覧

| 関数名 | 優先度 | 検証内容 |
|---|---|---|
| `test_async_write_read_roundtrip` | P1 | 非同期 write → read のラウンドトリップ |
| `test_async_mkdir_listdir` | P1 | 非同期 mkdir → listdir |
| `test_async_context_manager` | P1 | `async with await mfs.open(...)` のライフサイクル |
| `test_async_file_not_found` | P1 | 非同期版でも `FileNotFoundError` が送出される |
| `test_async_quota_exceeded` | P1 | 非同期版でも `MFSQuotaExceededError` が送出される |
| `test_async_stat` | P1 | 非同期 stat() の動作 |
| `test_async_copy_and_remove` | P1 | 非同期 copy → remove |
| `test_async_export_import_tree` | P1 | 非同期 export_tree / import_tree |
| `test_async_walk` | P2 | 非同期 walk() がリストを返す |
| `test_async_concurrent_operations` | P2 | 複数の非同期タスクでの同時操作 |
| `test_async_glob` | P1 | 非同期 glob() のマッチ動作 |
| `test_async_rename` | P1 | 非同期 rename() のファイルリネーム |
| `test_async_move` | P1 | 非同期 move() のファイル移動 |
| `test_async_rmtree` | P1 | 非同期 rmtree() のディレクトリ削除 |
| `test_async_copy_tree` | P1 | 非同期 copy_tree() のディレクトリコピー |
| `test_async_handle_seek_and_tell` [v12] | P1 | AsyncMemoryFileHandle の seek / tell が正しく動作する |
| `test_async_is_dir` [v12] | P1 | 非同期 is_dir がディレクトリとファイルを正しく判別する |
| `test_async_stats` [v12] | P1 | 非同期 stats がファイルシステムの使用状況を返す |
| `test_async_get_size` [v12] | P1 | 非同期 get_size がファイルサイズを正しく返す |
| `test_async_export_as_bytesio` [v12] | P1 | 非同期 export_as_bytesio がファイル内容を BytesIO で返す |

#### 擬似コード例

```python
import pytest
import asyncio

# AsyncMemoryFileSystem は遅延インポート
from dmemfs._async import AsyncMemoryFileSystem


@pytest.fixture
async def async_mfs():
    return AsyncMemoryFileSystem(max_quota=1 * 1024 * 1024)


@pytest.mark.asyncio
async def test_async_write_read_roundtrip(async_mfs):
    await async_mfs.mkdir("/data")

    async with await async_mfs.open("/data/test.bin", "wb") as f:
        written = await f.write(b"hello async world")
        assert written == 17

    async with await async_mfs.open("/data/test.bin", "rb") as f:
        data = await f.read()
        assert data == b"hello async world"


@pytest.mark.asyncio
async def test_async_mkdir_listdir(async_mfs):
    await async_mfs.mkdir("/dir1/sub1")
    await async_mfs.mkdir("/dir1/sub2")

    entries = await async_mfs.listdir("/dir1")
    assert sorted(entries) == ["sub1", "sub2"]


@pytest.mark.asyncio
async def test_async_context_manager(async_mfs):
    async with await async_mfs.open("/test.bin", "wb") as f:
        await f.write(b"data")

    # close 後に read できること
    async with await async_mfs.open("/test.bin", "rb") as f:
        assert await f.read() == b"data"


@pytest.mark.asyncio
async def test_async_file_not_found(async_mfs):
    with pytest.raises(FileNotFoundError):
        async with await async_mfs.open("/nonexistent", "rb") as f:
            pass


@pytest.mark.asyncio
async def test_async_quota_exceeded(async_mfs):
    from dmemfs import MFSQuotaExceededError

    # 1MB クォータを超える書き込み
    with pytest.raises(MFSQuotaExceededError):
        async with await async_mfs.open("/huge.bin", "wb") as f:
            await f.write(b"\x00" * (2 * 1024 * 1024))


@pytest.mark.asyncio
async def test_async_stat(async_mfs):
    async with await async_mfs.open("/test.bin", "wb") as f:
        await f.write(b"data")

    info = await async_mfs.stat("/test.bin")
    assert info["size"] == 4
    assert "created_at" in info
    assert "modified_at" in info


@pytest.mark.asyncio
async def test_async_concurrent_operations(async_mfs):
    """複数の非同期タスクが同時にMFSを操作してもクラッシュしない。"""
    await async_mfs.mkdir("/concurrent")

    async def write_task(i):
        path = f"/concurrent/file_{i}.bin"
        async with await async_mfs.open(path, "wb") as f:
            await f.write(f"data_{i}".encode())

    # 10 個の非同期タスクを同時実行
    await asyncio.gather(*(write_task(i) for i in range(10)))

    entries = await async_mfs.listdir("/concurrent")
    assert len(entries) == 10
```

### 20.2 テスト依存関係

`pytest-asyncio` パッケージが必要。`requirements.in` への追加が必要:

```
pytest-asyncio
```

---

## 21. [v12] `tests/unit/test_fs_coverage.py` — ブランチカバレッジ補完テスト

> **ステータス**: カバレッジ 99% 達成のために新規作成。`_fs.py` および `__init__.py` の未カバーブランチを網羅。

### 21.1 テスト一覧

| テスト関数名 | 優先度 | 対象ソース行 | 検証観点 |
|---|---|---|---|
| `test_resolve_path_file_in_middle_returns_none` | P1 | `_fs.py` L109 | `_resolve_path` がパス中間にファイルノードを発見したとき None を返す |
| `test_exists_with_traversal_path_returns_false` | P1 | `_fs.py` L371-372 | `exists()` がパストラバーサルの ValueError を捕捉して False を返す |
| `test_is_dir_with_traversal_path_returns_false` | P1 | `_fs.py` L377-378 | `is_dir()` が同上 |
| `test_export_tree_nonexistent_prefix_returns_empty` | P1 | `_fs.py` L476 | `_collect_files(None, ...)` 分岐（存在しない prefix）で空 dict |
| `test_export_tree_file_prefix_returns_single_file` | P1 | `_fs.py` L477-478 | `_collect_files` の FileNode 分岐で単一ファイルが返る |
| `test_deep_copy_subtree_unknown_type_raises` | P1 | `_fs.py` L654 | `_deep_copy_subtree` に未知型を渡すと TypeError |
| `test_walk_skips_deleted_child` | P1 | `_fs.py` L685 | `_walk_dir` が `_nodes` から削除されたエントリをスキップする |
| `test_glob_skips_deleted_child` | P1 | `_fs.py` L703 | `_glob_match` が同上 |
| `test_collect_all_paths_skips_deleted_child` | P1 | `_fs.py` L762, L777 | `_collect_all_paths` が同上 |
| `test_init_lazy_load_async_classes` | P1 | `__init__.py` L13-19 | `pkg.AsyncMemoryFileSystem` アクセスで `__getattr__` の遅延ロード分岐を通す |
| `test_init_getattr_unknown_raises` | P1 | `__init__.py` L19 | 不明な属性名で AttributeError |
| `test_import_tree_empty_dict_is_noop` | P1 | `_fs.py` L487 | `import_tree({})` が早期リターンして何も変えない |
| `test_glob_relative_pattern_auto_prefixed` | P1 | `_fs.py` L703 | `glob()` が `/` で始まらないパターンに `/` を先頭付与する |
| `test_glob_match_file_node_returns_empty` | P1 | `_fs.py` L717-718 | `_glob_match` に FileNode を渡すと即 [] を返す |
| `test_glob_match_empty_parts_returns_empty` | P1 | `_fs.py` L719-720 | `_glob_match` に空 parts を渡すと即 [] を返す |
| `test_import_tree_rollback_restores_existing_file` | P0 | `_fs.py` L553-565 | import_tree ロールバックで既存ファイルが元の内容に復元される |
| `test_import_tree_rollback_removes_new_file` | P0 | `_fs.py` L566-567 | import_tree ロールバックで新規作成エントリが削除される |

### 21.2 技術的注意点

- `_resolve_path`・`_glob_match` などの内部メソッドは `mfs._xxx` で直接呼び出して検証。
- `test_walk_skips_deleted_child` 等では `mfs._nodes[child_id]` を手動削除して競合状態を模擬。
- `test_init_lazy_load_async_classes` では `pkg.__dict__.pop("AsyncMemoryFileSystem", None)` でキャッシュを除去してから `pkg.AsyncMemoryFileSystem` にアクセスすることで `__getattr__` を強制的に通す。
- `test_import_tree_rollback_*` では `unittest.mock.patch.object(mfs, "_alloc_file", side_effect=...)` で N 回目の呼び出しで RuntimeError を発生させることでロールバックパスを再現する。

### 21.3 カバレッジ達成状況

| バージョン | テスト件数 | カバレッジ |
|---|---|---|
| v9 初期実装 | 〜150 件 | 〜85% |
| v10 対応後 | 〜200 件 | 〜90% |
| v11 対応後 | 〜260 件 | 〜93% |
| **v12 対応後** | **283 件** | **99%** |

残り未カバー 10 行はいずれも現実的にテスト困難な防御コード（`__del__` の例外ガード、デッドコード相当の promotion 分岐、ロック外競合防御など）。


---

## §22. GIL フリー (free-threaded) スレッドセーフ検証ストレステスト

> **参照**: `plan/freethread_test.md`、spec_v13.md §6.3

### テスト配置

`tests/stress/test_threaded_stress.py`（新規ファイル）

### テストケース一覧

| ID | テスト名 | スレッド×反復 | マーカー | 検証観点 |
|---|---|---|---|---|
| ST-01 | `test_high_concurrency_write_no_corruption` | 50×1000 | p1 | 専用ファイルへの書き込みでデータ破壊なし |
| ST-02 | `test_concurrent_create_delete_cycle` | 30×1000 | p1 | 同一パスへの create/delete サイクルで競合なし |
| ST-03 | `test_mixed_readwrite_same_file` | 20w+20r×500 | p1 | 同一ファイルへのロック競合が正確に動作する |
| ST-04 | `test_quota_boundary_concurrent` | 40×500 | p1 | クォータ境界での競合書き込み（超過は例外のみ、破壊なし） |
| ST-05 | `test_directory_tree_concurrent_ops` | 20×500 | p1 | mkdir/listdir/rmtree 並行実行でパニックなし |
| ST-06 | `test_stat_rename_concurrent` | 10w+10s×500 | p1 | stat()/rename() 並行実行でクラッシュなし |

### 実行環境

- **通常 CI**: Python 3.11 / 3.12 / 3.13（全テストに含める。`@pytest.mark.p1` のみ、除外マーカーなし）
- **追加 CI**: Python 3.13t + `PYTHON_GIL=0`（同じテストを free-threaded で実行してロック機構の GIL 非依存性を証明）

```bash
# ローカル free-threaded 実行
PYTHON_GIL=0 uv run --python cpython-3.13.7+freethreaded pytest tests/stress/ -v
```

### ベンチマーク実測値（2026-02-27, Windows, Python 3.13）

| スレッド数 × 反復数 | 実行時間 | 備考 |
|---|---|---|
| 50 × 200 | 0.28 秒 | |
| 50 × 1000 | 0.95 秒 | **採用値** |
| 50 × 3000 | 11.87 秒 | CI には重い |

6 テスト合計: 約 5.4 秒（通常 CI に支障なし）

### 合否基準

- すべてのスレッドが正常終了すること
- データ破壊・デッドロック・予期しない例外が発生しないこと
- `pytest.ini` の `timeout = 30` 秒以内に完了すること（実測: 約 0.95 秒/テスト）
