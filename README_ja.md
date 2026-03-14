# D-MemFS

**Python向け、プロセス内ハードクォータ付き仮想ファイルシステム**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/nightmarewalker/D-MemFS/actions/workflows/test.yml/badge.svg)](https://github.com/nightmarewalker/D-MemFS/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/nightmarewalker/D-MemFS/blob/main/LICENSE)
[![Zero dependencies (runtime)](https://img.shields.io/badge/runtime_deps-none-brightgreen.svg)]()
[![PyPI version](https://img.shields.io/pypi/v/D-MemFS.svg)](https://pypi.org/project/D-MemFS/)
[![Socket Badge](https://socket.dev/api/badge/pypi/package/D-MemFS)](https://socket.dev/pypi/package/D-MemFS)

言語: [英語（デフォルト）](https://github.com/nightmarewalker/D-MemFS/blob/main/README.md) | [日本語](https://github.com/nightmarewalker/D-MemFS/blob/main/README_ja.md)

---

## 実績

| 指標 | 実績 |
|---|---|
| 🧪 **堅牢性** | 369テスト、カバレッジ97% |
| 🔒 **安全性の検証** | 98, 100×4 — 全セキュリティカテゴリでトップスコア（Socket.dev） |
| 🌟 **コミュニティ** | [`r/Python` にて議論され、高い評価を獲得](https://www.reddit.com/r/Python/comments/1rrqr8z/i_built_an_inmemory_virtual_filesystem_for_python/) |
---

## なぜ MFS なのか

`MemoryFileSystem` は、Pythonプロセス内に完全に隔離された filesystem-like ワークスペースを提供します。

- ハードクォータ（`MFSQuotaExceededError`）で OOM 前に過大書き込みを拒否
- メモリーガードで物理メモリ枯渇による OOM キルを事前に検知
- **完全なファイルシステムセマンティクス (Full FS Semantics)**: ディレクトリ階層と複数ファイル操作（`import_tree`, `copy_tree`, `move`）
- ファイル単位RWロック + 構造用グローバルロックでスレッドセーフ
- フリースレッド Python 対応（`PYTHON_GIL=0`）— 50スレッド競合下でのストレステスト済み
- `asyncio.to_thread` ベースの Async ラッパー（`AsyncMemoryFileSystem`）
- ランタイム依存ゼロ（標準ライブラリのみ）
- **管理者権限不要** — OS レベルの RAM ディスクが使えない CI ランナー、コンテナ、共有マシンでもそのまま動作
- **369テスト、カバレッジ97%** — 3 OS（Linux / Windows / macOS）× 3 Python バージョン（3.11〜3.13、フリースレッド 3.13t 含む）で検証済み

`io.BytesIO` が単一バッファで不足する場合や、OSレベルのRAMディスク/tmpfsが使いにくい環境（権限制約、コンテナポリシー、Windowsの運用負荷）で有効です。**CI パイプラインの高速化**にも最適——インフラ変更なしにテストやデータ処理からディスク I/O を排除できます。

**アーキテクチャの境界に関する注意:** 本ライブラリは完全にプロセス内のツールです。外部のサブプロセス（CLIツールなど）は、標準的なOSのパスを経由してこれらのファイルにアクセスすることはできません。外部バイナリへのファイル受け渡しを多用するパイプラインの場合は、OSレベルのRAMディスク（`tmpfs`）が適しています。D-MemFSは、Pythonネイティブなテストスイートや内部データパイプラインの高速化において真価を発揮します。

---

### アーカイブのインメモリ解凍
巨大なZIPやTARアーカイブをすべてメモリ上で解凍し、オンザフライで内容を処理します。ディスクの摩耗（TBW）を防ぎ、ゴミファイルが残るリスクを排除します。
* 📝 **チュートリアル:** [`examples/archive_extraction.md`](examples/archive_extraction.md)

### CI/CDパイプラインとテストのデバッグ
重いファイルI/Oを伴うテストをすべてメモリ上で実行し、パイプラインを高速化します。テストが失敗した場合は、仮想ファイルシステム全体の状態を物理ディレクトリに書き出し（`export_tree`）、事後デバッグを容易にします。
* 📝 **チュートリアル:** [`examples/ci_debug_export.md`](examples/ci_debug_export.md)

### 高速なSQLiteテストフィクスチャ
データベースのテストスイートにおけるディスクI/Oのボトルネックを解消します。マスターとなるSQLiteデータベースの状態を一度だけ生成してD-MemFSに保存し、各テストで瞬時にロードします。ディスク摩耗ゼロ・クリーンアップ不要で、完璧なテストの独立性を保証します。
* 📝 **チュートリアル:** [`examples/sqlite_test_fixtures.md`](examples/sqlite_test_fixtures.md)

### マルチスレッドでのデータステージング（ETL）
ETLパイプラインにおける揮発性の高速なステージング領域としてD-MemFSを使用します。スレッドセーフなファイルロック機構を内蔵しており、安全な並行データ処理を保証します。
* 📝 **チュートリアル:** [`examples/etl_staging_multithread.md`](examples/etl_staging_multithread.md)

### 安全な巨大ファイルの処理（サーバーレス/サンドボックス）
メモリガード（Memory Guard）を使用し、巨大なファイルをチャンク単位で処理します。OSレベルのRAMディスクが使えない環境において、ホストOSがメモリ不足（OOM）でクラッシュする*前に*安全に例外を送出します。
* 📝 **チュートリアル:** [`examples/memory_guard_streaming.md`](examples/memory_guard_streaming.md)

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
- `default_lock_timeout`（デフォルト `30.0`）: `open()` 時のファイルロック取得に使う既定タイムアウト秒数。`None` を指定すると無期限待機
- `memory_guard`（デフォルト `"none"`）: 物理メモリ保護モード — `"none"` / `"init"` / `"per_write"`
- `memory_guard_action`（デフォルト `"warn"`）: ガード発火時の動作 — `"warn"`（`ResourceWarning`） / `"raise"`（`MemoryError`）
- `memory_guard_interval`（デフォルト `1.0`）: OS メモリ問い合わせの最小間隔秒数（`"per_write"` のみ）

> **注意:** `export_as_bytesio()` が返す `BytesIO` オブジェクトはクォータ管理の対象外です。
> 大きなファイルのエクスポートでは、設定されたクォータ上限を超えるプロセスメモリを消費する可能性があります。

> **注意 — クォータとフリースレッド Python:**
> クォータ計算に使うチャンクオーバーヘッド推定値は、インポート時に `sys.getsizeof()` で
> 実測されます。フリースレッド Python（3.13t、`PYTHON_GIL=0`）は通常ビルドよりオブジェクト
> ヘッダが大きいため、`CHUNK_OVERHEAD_ESTIMATE` が増加します（CPython 3.13 で約 93 バイト
> → 約 117 バイト）。そのため、同じ `max_quota` でもフリースレッドビルドでは実効容量がやや
> 減少します。特に小さなファイルや小さな追記を大量に扱うワークロードで顕著です。
> これはバグではなく、実際のメモリ消費を正しく反映した動作です。
> ビルド間で一貫した動作が必要な場合は、`chunk_overhead_override` で値を固定するか、
> 実行時に `stats()["overhead_per_chunk_estimate"]` を確認してください。

対応するバイナリモード: `rb`, `wb`, `ab`, `r+b`, `xb`

## Memory Guard

MFS は論理クォータを強制しますが、その値を現在の物理 RAM より大きく設定することはできます。
`memory_guard` は、そのギャップを埋めるためのオプションの安全装置です。

```python
from dmemfs import MemoryFileSystem

# 初期化時に max_quota と物理 RAM の関係を警告
mfs = MemoryFileSystem(max_quota=8 * 1024**3, memory_guard="init")

# 書き込み前に RAM 不足なら MemoryError を送出
mfs = MemoryFileSystem(
    max_quota=8 * 1024**3,
    memory_guard="per_write",
    memory_guard_action="raise",
)
```

| モード | 初期化時 | 各書き込み時 | オーバーヘッド |
|---|---|---|---|
| `"none"` | なし | なし | ゼロ |
| `"init"` | 1回だけ確認 | なし | ごく小さい |
| `"per_write"` | 1回だけ確認 | キャッシュ付き確認 | おおむね 1 秒あたり 1 回の OS 問い合わせ |

`memory_guard_action="warn"` では `ResourceWarning` を出したうえで処理を継続します。
`memory_guard_action="raise"` では、実際のメモリ確保に入る前に `MemoryError` で拒否します。

`AsyncMemoryFileSystem` も同じコンストラクタパラメータを受け取り、同期版へそのまま転送します。

### `MemoryFileHandle`

- `io.RawIOBase` 互換のバイナリハンドル
- `read`, `write`, `seek`, `tell`, `truncate`, `flush`, `close`
- `readinto`
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

`MFSTextHandle` はバッファなしの薄いラッパーです。`write()` 時にエンコード、`read()` / `readline()` 時にデコードします。`read(size)` はバイト数ではなく文字数で扱われるため、マルチバイト文字も途中で壊さずに読み取れます。`io.TextIOWrapper` と異なり、`MemoryFileHandle` とのバッファリング問題が発生しません。

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

## ベンチマーク

最小構成の比較ベンチマークを同梱しています。

- D-MemFS vs `io.BytesIO` vs `PyFilesystem2 (MemoryFS)` vs `tempfile(RAMDisk)` / `tempfile(SSD)`
- ケース: 小ファイル大量 read/write、ストリーム write/read、ランダムアクセス、大容量ストリーム、深いツリー
- レポートを `benchmarks/results/` へ保存可能

> **注意:** setuptools 82（2026年2月）以降、`pyfilesystem2` は既知のアップストリーム問題（[#597](https://github.com/PyFilesystem/pyfilesystem2/issues/597)）により import 不能になっています。PyFilesystem2 を含むベンチマーク結果は setuptools ≤ 81 の環境で計測したものであり、比較データとして有効ですが、現在の環境では再現できません。

実行例:

```bash
# RAMディスクとSSDのディレクトリを指定して tempfile を比較する場合:
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --ramdisk-dir R:\Temp --ssd-dir C:\TempX --save-md auto --save-json auto
```

詳細は `BENCHMARK.md` を参照してください。

最新のベンチマーク結果:

- [benchmark_current_result.md](https://github.com/nightmarewalker/D-MemFS/blob/main/benchmarks/results/benchmark_current_result.md)

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

- [API リファレンス（Markdown）](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/api_md/index.md)

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

- [アーキテクチャ仕様 v13](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/spec_v13.md) — API 設計・内部構造・CI マトリクス
- [アーキテクチャ仕様 v14](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/spec_v14.md) — MemoryGuard 統合後の最新アーキテクチャ仕様
- [詳細設計書 v2](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/DetailedDesignSpec_v2.md) — コンポーネント設計と実装意図
- [テスト詳細設計書 v2](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/DetailedDesignSpec_test_v2.md) — テストケース一覧と疑似コード

---

## パフォーマンスサマリー

同梱ベンチマークの主要結果（小ファイル300個×4KiB、16MiBストリーム、512MiB大容量ストリーム）:

| ケース | D-MemFS (ms) | BytesIO (ms) | tempfile(RAMDisk) (ms) | tempfile(SSD) (ms) |
|---|---:|---:|---:|---:|
| small_files_rw | 51 | 6 | 207 | 267 |
| stream_write_read | 81 | 62 | 20 | 21 |
| random_access_rw | **34** | 82 | 37 | 35 |
| large_stream_write_read | **529** | 2 258 | 514 | 541 |
| many_files_random_read | 1 280 | 212 | 6 310 | 8 601 |
| deep_tree_read | 224 | 3 | 346 | 361 |

D-MemFS は小ファイルワークロードでわずかなオーバーヘッドがありますが、大容量ストリームやランダムアクセスパターンでは `BytesIO` と比べて大幅に高速です。詳細は `BENCHMARK.md` および [benchmark_current_result.md](https://github.com/nightmarewalker/D-MemFS/blob/main/benchmarks/results/benchmark_current_result.md) を参照してください。

> **注意:** `tempfile(RAMDisk)` の結果は RAM ディスク上の TEMP ディレクトリで計測、`tempfile(SSD)` は物理 SSD 上で計測したものです。`--ramdisk-dir` / `--ssd-dir` オプションで両パターンを一度に再現できます。

---

## 開発支援
D-MemFS がお役に立てましたら、[GitHub Sponsors](https://github.com/sponsors/nightmarewalker) を通じた継続的な開発へのご支援を検討いただければ幸いです。

---

## ライセンス

MIT License

