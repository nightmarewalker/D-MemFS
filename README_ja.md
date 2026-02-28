# D-MemFS

**Python向け、プロセス内ハードクォータ付き仮想ファイルシステム**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero dependencies (runtime)](https://img.shields.io/badge/runtime_deps-none-brightgreen.svg)]()

言語: [英語（デフォルト）](./README.md) | [日本語](./README_ja.md)

---

## なぜ MFS なのか

`MemoryFileSystem` は、Pythonプロセス内に完全に隔離された filesystem-like ワークスペースを提供します。

- ハードクォータ（`MFSQuotaExceededError`）で OOM 前に過大書き込みを拒否
- ディレクトリ階層と複数ファイル操作（`import_tree`, `copy_tree`, `move`）
- ファイル単位RWロック + 構造用グローバルロックでスレッドセーフ
- フリースレッド Python 対応（`PYTHON_GIL=0`）— 50スレッド競合下でのストレステスト済み
- `asyncio.to_thread` ベースの Async ラッパー（`AsyncMemoryFileSystem`）
- ランタイム依存ゼロ（標準ライブラリのみ）

`io.BytesIO` が単一バッファで不足する場合や、OSレベルのRAMディスク/tmpfsが使いにくい環境（権限制約、コンテナポリシー、Windowsの運用負荷）で有効です。

---

## インストール

```bash
pip install D-MemFS
```

要件: Python 3.11+

---

## クイックスタート

```python
from dmemfs import MemoryFileSystem, MFSQuotaExceededError

mfs = MemoryFileSystem(max_quota=64 * 1024 * 1024)

mfs.mkdir("/data")
with mfs.open("/data/hello.bin", "wb") as f:
    f.write(b"hello")

with mfs.open("/data/hello.bin", "rb") as f:
    print(f.read())  # b"hello"

print(mfs.listdir("/data"))
print(mfs.is_file("/data/hello.bin"))  # True

try:
    with mfs.open("/huge.bin", "wb") as f:
        f.write(bytes(512 * 1024 * 1024))
except MFSQuotaExceededError as e:
    print(e)
```

---

## API ハイライト

### `MemoryFileSystem`

- `open(path, mode, *, preallocate=0, lock_timeout=None)`
- `mkdir`, `remove`, `rmtree`, `rename`, `move`, `copy`, `copy_tree`
- `listdir`, `exists`, `is_dir`, `is_file`, `walk`, `glob`
- `stat`, `stats`, `get_size`
- `export_as_bytesio`, `export_tree`, `iter_export_tree`, `import_tree`

**コンストラクタパラメータ:**
- `max_quota`（デフォルト `256 MiB`）: ファイルデータのバイトクォータ
- `max_nodes`（デフォルト `None`）: ノード数の上限（ファイル＋ディレクトリ）。超過時は `MFSNodeLimitExceededError`
- `default_storage`（デフォルト `"auto"`）: 新規ファイルのストレージバックエンド — `"auto"` / `"sequential"` / `"random_access"`
- `promotion_hard_limit`（デフォルト `None`）: Sequential→RandomAccess 自動昇格を抑制するバイト閾値（`None` は内蔵の 512 MiB 上限を使用）
- `chunk_overhead_override`（デフォルト `None`）: クォータ計算に使うチャンクオーバーヘッド見積もりの上書き値

> **注意:** `export_as_bytesio()` が返す `BytesIO` オブジェクトはクォータ管理の対象外です。
> 大きなファイルのエクスポートでは、設定されたクォータ上限を超えるプロセスメモリを消費する可能性があります。

対応するバイナリモード: `rb`, `wb`, `ab`, `r+b`, `xb`

### `MemoryFileHandle`

- `read`, `write`, `seek`, `tell`, `truncate`, `flush`, `close`
- file-like 能力判定: `readable`, `writable`, `seekable`

`flush()` は互換性確保のための no-op 実装です。

### `stat()` の戻り値（`MFSStatResult`）

`size`, `created_at`, `modified_at`, `generation`, `is_dir`

- ファイルとディレクトリの両方に対応
- ディレクトリの場合: `size=0`, `generation=0`, `is_dir=True`

---

## テキストモード

D-MemFS はネイティブではバイナリモードで動作します。テキスト I/O には `MFSTextHandle` を使用してください。

```python
from dmemfs import MemoryFileSystem, MFSTextHandle

mfs = MemoryFileSystem()
mfs.mkdir("/data")

# テキストの書き込み
with mfs.open("/data/hello.bin", "wb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    th.write("こんにちは世界\n")
    th.write("Hello, World!\n")

# テキストを1行ずつ読み込む
with mfs.open("/data/hello.bin", "rb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    for line in th:
        print(line, end="")
```

`MFSTextHandle` はバッファなしの薄いラッパーです。`write()` 時にエンコード、`read()` / `readline()` 時にデコードします。`io.TextIOWrapper` と異なり、`MemoryFileHandle` とのバッファリング問題が発生しません。

---

## ユースケースチュートリアル

### ETL ステージング

raw → processed → output のディレクトリ構成でデータを段階処理する例:

```python
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem(max_quota=16 * 1024 * 1024)
mfs.mkdir("/raw")
mfs.mkdir("/processed")

raw_data = b"id,name,value\n1,foo,100\n2,bar,200\n"
with mfs.open("/raw/data.csv", "wb") as f:
    f.write(raw_data)

with mfs.open("/raw/data.csv", "rb") as f:
    data = f.read()

with mfs.open("/processed/data.csv", "wb") as f:
    f.write(data.upper())

mfs.rmtree("/raw")  # ステージング領域をクリーンアップ
```

### アーカイブ操作

複数ファイルをツリーとして格納・一覧表示・エクスポートする例:

```python
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem()
mfs.import_tree({
    "/archive/doc1.bin": b"Document 1",
    "/archive/doc2.bin": b"Document 2",
    "/archive/sub/doc3.bin": b"Document 3",
})

print(mfs.listdir("/archive"))  # ['doc1.bin', 'doc2.bin', 'sub']

snapshot = mfs.export_tree(prefix="/archive")  # {パス: bytes} の辞書
```

### SQLite スナップショット

インメモリ SQLite DB を MFS に保存して後から復元する例:

```python
import sqlite3
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem()
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE t (id INTEGER, val TEXT)")
conn.execute("INSERT INTO t VALUES (1, 'hello')")
conn.commit()

with mfs.open("/snapshot.db", "wb") as f:
    f.write(conn.serialize())
conn.close()

with mfs.open("/snapshot.db", "rb") as f:
    raw = f.read()
restored = sqlite3.connect(":memory:")
restored.deserialize(raw)
rows = restored.execute("SELECT * FROM t").fetchall()  # [(1, 'hello')]
```

---

## 並行性とロックに関する注意

- パス/ツリー操作は `_global_lock` で保護されます
- ファイルアクセスはファイル単位 `ReadWriteLock` で保護されます
- `lock_timeout` の挙動:
  - `None`: 無期限ブロック
  - `0.0`: try-lock（即時 `BlockingIOError`）
  - `> 0`: 指定秒でタイムアウトし `BlockingIOError`
- 現在の `ReadWriteLock` は非フェア実装のため、read が連続する負荷では writer starvation が起こり得ます

運用上の推奨:

- ロック保持時間を短くする
- レイテンシに厳しい経路では `lock_timeout` を明示する
- `walk()` と `glob()` は弱一貫性を提供します: 各ディレクトリレベルは `_global_lock` 下でスナップショットを取得しますが、走査全体はアトミックではありません。並行した構造変更により、不整合な結果が返る可能性があります。

---

## Async 利用

```python
from dmemfs import AsyncMemoryFileSystem

async def run() -> None:
    mfs = AsyncMemoryFileSystem(max_quota=64 * 1024 * 1024)
    await mfs.mkdir("/a")
    async with await mfs.open("/a/f.bin", "wb") as f:
        await f.write(b"data")
    async with await mfs.open("/a/f.bin", "rb") as f:
        print(await f.read())
```

---

## ベンチマーク

最小構成の比較ベンチマークを同梱しています。

- MFS vs `io.BytesIO` vs `PyFilesystem2 (MemoryFS)` vs `tempfile`
- ケース: 小ファイル大量 read/write、ストリーム write/read
- レポートを `benchmarks/results/` へ保存可能

> **注意:** setuptools 82（2026年2月）以降、`pyfilesystem2` は既知のアップストリーム問題（[#597](https://github.com/PyFilesystem/pyfilesystem2/issues/597)）により import 不能になっています。PyFilesystem2 を含むベンチマーク結果は setuptools ≤ 81 の環境で計測したものであり、比較データとして有効ですが、現在の環境では再現できません。

実行例:

```bash
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --save-md auto --save-json auto
```

詳細は `BENCHMARK.md` を参照してください。

最新のベンチマーク結果:

- [benchmark_current_result.md](./benchmarks/results/benchmark_current_result.md)

---

## テストとカバレッジ

テスト実行と開発フローは `TESTING.md` に記載しています。

ローカルの基本実行:

```bash
uv pip compile requirements.in -o requirements.txt
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30 --cov=dmemfs --cov-report=xml --cov-report=term-missing
```

CI（`.github/workflows/test.yml`）では coverage XML を生成します。

---

## API ドキュメント生成

API ドキュメントは `pydoc-markdown`（Markdown形式、GitHub上で直接閲覧可能）で生成できます。

```bash
uvx --with pydoc-markdown --with-editable . pydoc-markdown '{
  loaders: [{type: python, search_path: [.]}],
  processors: [{type: filter, expression: "default()"}],
  renderer: {type: markdown, filename: docs/api_md/index.md}
}'
```

HTML形式（ローカルブラウザ用）:

```bash
uvx --with-requirements requirements.txt pdoc dmemfs -o docs/api
```

- [API リファレンス（Markdown）](./docs/api_md/index.md)

---

## 互換性と Non-Goals

- `open()` はバイナリ専用（`rb`, `wb`, `ab`, `r+b`, `xb`）。テキスト I/O は `MFSTextHandle` ラッパーで対応。
- シンボリックリンク/ハードリンク非対応 — パストラバーサルループや構造の複雑化を排除するため意図的に省略（`pathlib.PurePath` と同じ設計方針）。
- `pathlib.Path` / `os.PathLike` 直接対応なし — MFS のパスは仮想パスであり、ホストファイルシステムのパスと混同されてはならない。`os.PathLike` を受け入れると、サードパーティライブラリや素の `open()` 呼び出しが MFS の仮想パスを実 OS のパスと誤認し、ホストファイルシステムに対して意図しないシステムコールを発行するリスクがある。すべてのパスは POSIX 絶対表記の `str`（例: `"/data/file.txt"`）で指定すること。
- カーネルFS統合なし（意図的にプロセス内完結）

自動昇格の挙動:

- デフォルト（`default_storage="auto"`）では、新規ファイルは `SequentialMemoryFile` として作成され、ランダム書き込みが発生した時点で `RandomAccessMemoryFile` へ自動昇格する。
- 昇格は一方向（Sequential への逆戻りはしない）。
- `default_storage="sequential"` または `"random_access"` で作成時にバックエンドを固定できる。`promotion_hard_limit` を指定すると、指定バイト数以上での自動昇格を抑制できる。
- ストレージ昇格中は昇格対象ファイルのメモリ使用量が一時的に 2 倍になる。クォータシステムはこれを考慮しているが、プロセスレベルのメモリが短時間スパイクすることがある。

セキュリティに関する注意: インメモリのデータは、OSのスワップやコアダンプによって物理ディスクに書き出される可能性があります。MFS はメモリのロック（`mlock` 等）や安全な消去機能を提供しません。機密データの隔離にのみ MFS に依存しないでください。

---

## 例外リファレンス

| 例外 | 典型的な発生条件 |
|---|---|
| `MFSQuotaExceededError` | write/import/copy がクォータ超過 |
| `MFSNodeLimitExceededError` | ノード数が `max_nodes` を超過（`MFSQuotaExceededError` のサブクラス） |
| `FileNotFoundError` | パスが存在しない |
| `FileExistsError` | 作成先が既に存在 |
| `IsADirectoryError` | ファイル操作にディレクトリを渡した |
| `NotADirectoryError` | ディレクトリ操作にファイルを渡した |
| `BlockingIOError` | ロックタイムアウト / open中ファイル競合 |
| `io.UnsupportedOperation` | モード不一致 / 非対応操作 |
| `ValueError` | mode/path/seek/truncate 引数が不正 |

---

## pytest で使う

D-MemFS には pytest プラグインが同梱されており、`mfs` フィクスチャを提供します:

```python
# conftest.py — プラグインを明示的に登録する
pytest_plugins = ["dmemfs._pytest_plugin"]
```

> **注意:** プラグインは自動検出されません。利用するには `conftest.py` での宣言が必要です。

```python
# test_example.py
def test_write_read(mfs):
    mfs.mkdir("/tmp")
    with mfs.open("/tmp/hello.txt", "wb") as f:
        f.write(b"hello")
    with mfs.open("/tmp/hello.txt", "rb") as f:
        assert f.read() == b"hello"
```

---

## 開発メモ

設計書:

- [アーキテクチャ仕様 v13](./docs/design/spec_v13.md) — API 設計・内部構造・CI マトリクス
- [詳細設計書](./docs/design/DetailedDesignSpec.md) — コンポーネント設計と実装意図
- [テスト詳細設計書](./docs/design/DetailedDesignSpec_test.md) — テストケース一覧と疑似コード

---

## パフォーマンスサマリー

同梱ベンチマークの主要結果（小ファイル300個×4KiB、16MiBストリーム、2GiB大容量ストリーム）:

| ケース | MFS (ms) | BytesIO (ms) | tempfile (ms) |
|---|---:|---:|---:|
| small_files_rw | 34 | 5 | 164 |
| stream_write_read | 64 | 51 | 17 |
| random_access_rw | **24** | 53 | 27 |
| large_stream_write_read | **1 438** | 7 594 | 1 931 |
| many_files_random_read | 777 | 163 | 4 745 |

MFS は小ファイルワークロードでわずかなオーバーヘッドがありますが、大容量ストリームやランダムアクセスパターンでは `BytesIO` と比べて大幅に高速です。詳細は `BENCHMARK.md` および [benchmark_current_result.md](./benchmarks/results/benchmark_current_result.md) を参照してください。

> **注意:** 上記の `tempfile` の結果は、システムの TEMP ディレクトリが RAM ディスク上にある環境で計測したものです。物理 SSD/HDD 環境では `tempfile` の数値は大幅に遅くなります。

---

## ライセンス

MIT License
