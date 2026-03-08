# テスト実行ガイド

## 前提条件

[uv](https://github.com/astral-sh/uv) がインストールされていること。

```bash
# uv のインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
# または
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows
```

---

## テストの実行

### 全テストを実行する（基本）

```bash
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30
```

### サマリーのみ表示（簡潔）

```bash
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -q --timeout=30
```

---

## 依存パッケージの管理

`requirements.txt` は `requirements.in` から生成されます。依存バージョンを更新・再生成する場合：

```bash
uv pip compile requirements.in -o requirements.txt
```

| ファイル | 役割 |
|----------|------|
| `requirements.in` | 依存ライブラリの定義（バージョン制約のみ） |
| `requirements.txt` | `uv pip compile` が生成するピン留め済みロックファイル |

---

## テスト構成

```
tests/
├── unit/               # 各モジュールの局所仕様テスト
│   ├── test_lock.py
│   ├── test_quota.py
│   ├── test_path_normalize.py
│   ├── test_files_sequential.py
│   ├── test_files_randomaccess.py
│   ├── test_handle_io.py
│   ├── test_fs_coverage.py         # v11: FS 公開 API の網羅テスト
│   ├── test_timestamp.py           # v11: タイムスタンプ / stat() API
│   ├── test_default_storage.py
│   ├── test_text_handle.py
│   ├── test_package_metadata.py
│   ├── test_memory_info.py         # v14: OS 依存メモリ検出
│   └── test_memory_guard.py        # v14: MemoryGuard 戦略
├── integration/        # MemoryFileSystem 公開 API の結合テスト
│   ├── test_open_modes.py
│   ├── test_mkdir_listdir.py
│   ├── test_rename_move.py       # v10: move() / copy_tree() 追加
│   ├── test_remove_rmtree.py
│   ├── test_export_import.py
│   ├── test_stats.py
│   ├── test_concurrency.py
│   ├── test_async.py             # v11: AsyncMemoryFileSystem
│   └── test_memory_guard_integration.py  # v14: MemoryGuard 統合テスト
├── scenarios/          # 代表ユースケースのシナリオテスト
│   ├── test_usecase_sqlite_snapshot.py
│   ├── test_usecase_etl_staging.py
│   ├── test_usecase_archive_like.py
│   └── test_usecase_restricted_env.py
├── stress/             # 負荷・ストレステスト
│   └── test_threaded_stress.py
├── property/           # Hypothesis プロパティベーステスト
│   └── test_hypothesis.py
└── helpers/            # テスト共通ユーティリティ
    ├── fixtures.py
    ├── concurrency.py
    └── asserts.py
```

---

## よく使うオプション

### 特定のファイル・テストだけ実行

```bash
# ファイル指定
uvx --with-requirements requirements.txt --with-editable . pytest tests/unit/test_lock.py -v

# テスト関数名でフィルタ（-k オプション）
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -k "quota" -v

# 特定マーカーのみ（pytest.ini に定義: p0 / p1 / p2）
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -m p0 -v
```

### 並列実行（pytest-xdist）

```bash
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -n auto --timeout=30
```

### 失敗時に即停止

```bash
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -x --timeout=30
```

### タイムアウトの変更

```bash
# デフォルトは 30 秒（pytest.ini で設定）
uvx --with-requirements requirements.txt --with-editable . pytest tests/ --timeout=60
```

### カバレッジ計測

```bash
# ターミナルに未カバー行を表示
uvx --with-requirements requirements.txt --with-editable . pytest tests/ --cov=dmemfs --cov-report=term-missing --timeout=30

# CI と同じ XML レポートを生成（coverage.xml）
uvx --with-requirements requirements.txt --with-editable . pytest tests/ --cov=dmemfs --cov-report=xml --cov-report=term-missing --timeout=30

# HTML レポートを生成（htmlcov/index.html）
uvx --with-requirements requirements.txt --with-editable . pytest tests/ --cov=dmemfs --cov-report=html --timeout=30
```

### フリースレッド Python（GIL 無効）でのテスト

D-MemFS のロック機構が GIL に依存せず正しく動作することを検証する。
`tests/stress/` 配下のストレステスト（50 スレッド × 1000 回の高負荷パターン）を
free-threaded Python 3.13t で実行する。

```powershell
# 1. free-threaded Python のインストール（未インストールの場合）
uv python install cpython-3.13+freethreaded

# 2. ストレステストのみ実行（GIL=0 で free-threaded ビルドを使用）
$env:PYTHON_GIL = "0"
uvx --python cpython-3.13+freethreaded --with-requirements requirements.txt --with-editable . pytest tests/stress/ -v --timeout=30

# 3. 全テストを free-threaded Python で実行（任意・推奨）
uvx --python cpython-3.13+freethreaded --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30
```

> ⚠️ `$env:PYTHON_GIL = "0"` は GIL を明示的に無効化する環境変数。free-threaded ビルドではデフォルトで無効だが、明示的に設定することが推奨される。

### APIドキュメント生成（pdoc）

```bash
# HTML API ドキュメントを生成（docs/api 配下）
uvx --with-requirements requirements.txt pdoc dmemfs -o docs/api
```

---

## テストファイル対応表

全テスト（369件）のファイル別内訳:

| ファイルパス | テスト数 | カバー領域 |
|---|---:|---|
| `tests/unit/test_lock.py` | 14 | `ReadWriteLock` の基本動作・タイムアウト・再入・スレッド競合 |
| `tests/unit/test_quota.py` | 12 | `QuotaManager` の reserve/release・クォータ超過 |
| `tests/unit/test_path_normalize.py` | 12 | パス正規化・不正パス検出 |
| `tests/unit/test_files_sequential.py` | 15 | `SequentialMemoryFile` の read/write・昇格トリガー |
| `tests/unit/test_files_randomaccess.py` | 17 | `RandomAccessMemoryFile` の seek/truncate・random write |
| `tests/unit/test_handle_io.py` | 30 | `MemoryFileHandle` のモード別 I/O・flush/close |
| `tests/unit/test_fs_coverage.py` | 19 | FS 公開 API の網羅テスト（v12 追加） |
| `tests/unit/test_timestamp.py` | 16 | `stat()` / タイムスタンプ / generation |
| `tests/unit/test_default_storage.py` | 9 | デフォルトストレージ設定・切り替え |
| `tests/unit/test_text_handle.py` | 14 | `MFSTextHandle` のエンコード/デコード・readline・イテレーション |
| `tests/unit/test_package_metadata.py` | 1 | パッケージメタデータの整合性 |
| `tests/unit/test_memory_info.py` | 8 | v14: `get_available_memory_bytes()` OS 依存メモリ検出 |
| `tests/unit/test_memory_guard.py` | 8 | v14: `NullGuard`/`InitGuard`/`PerWriteGuard` 戦略パターン |
| `tests/integration/test_open_modes.py` | 21 | `open()` モード（rb/wb/ab/r+b/xb）の動作 |
| `tests/integration/test_mkdir_listdir.py` | 32 | `mkdir`・`listdir`・`exists`・`is_dir`・`glob`・`walk` |
| `tests/integration/test_rename_move.py` | 34 | `rename`・`move`・`copy`・`copy_tree` |
| `tests/integration/test_remove_rmtree.py` | 11 | `remove`・`rmtree` |
| `tests/integration/test_export_import.py` | 19 | `export_tree`・`import_tree`・`export_as_bytesio` |
| `tests/integration/test_stats.py` | 10 | `stats()`・`get_size()` |
| `tests/integration/test_concurrency.py` | 7 | マルチスレッド並行アクセス |
| `tests/integration/test_async.py` | 22 | `AsyncMemoryFileSystem` 非同期 API |
| `tests/integration/test_memory_guard_integration.py` | 12 | v14: MemoryGuard 統合テスト・MemoryError メッセージ |
| `tests/scenarios/test_usecase_etl_staging.py` | 4 | ETL ステージング・増分更新・並行書き込み |
| `tests/scenarios/test_usecase_archive_like.py` | 5 | アーカイブ操作・import_tree/export_tree ラウンドトリップ |
| `tests/scenarios/test_usecase_sqlite_snapshot.py` | 3 | SQLite serialize/deserialize・クォータ制限 |
| `tests/scenarios/test_usecase_restricted_env.py` | 3 | クォータ制限環境でのユースケース |
| `tests/stress/test_threaded_stress.py` | 6 | マルチスレッド負荷テスト |
| `tests/property/test_hypothesis.py` | 5 | Hypothesis プロパティベーステスト |
| **合計** | **369** | |


GitHub Actions の設定は `.github/workflows/test.yml` を参照。  
ローカルで CI と同じ環境を再現したい場合：

```bash
# requirements.txt を再生成してからテスト実行
uv pip compile requirements.in -o requirements.txt
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30

# API ドキュメント生成の再現
uvx --with-requirements requirements.txt pdoc dmemfs -o docs/api
```
