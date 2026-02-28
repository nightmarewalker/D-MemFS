# MemoryFileSystem (MFS) v13 アーキテクチャ＆実装マスター設計書 (完全防弾・網羅版)

## 変更履歴
| バージョン | 変更概要 |
|---|---|
| v9 | 初版マスター設計書 |
| v10 | ディレクトリインデックス層の導入、`glob("**")` 対応、`copy_tree()` / `move()` API追加、`wb` truncate 順序修正、`walk()` スレッドセーフティ注記、`export_as_bytesio()` ロック粒度改善、`__del__` stacklevel修正、将来ロードマップの追加 |
| **v11** | Phase 3 設計の詳細化：ファイルタイムスタンプ（`stat()` API）、メモリ使用量の最適化（`bytearray` shrink）、PEP 703 対応設計、async/await ラッパー層設計。ロードマップ項目を正式な設計セクションに昇格 |
| **v12** | Opus評価レポート（v3）フィードバック反映：`open()` 内 `_global_lock` 長期保持リスクの注意事項強化、`walk()`/`glob()` のGILフリー安全性対応、`get_size()`/`listdir()` のロック保護追加、`_NoOpQuotaManager` 削除、`AsyncMemoryFileSystem` 公開方式変更（`__getattr__` 遅延インポート）、`_force_reserve()` 使用制約の明記、`copy()` API仕様の補完 |
| **v13** | mfs_eval_report_opus_v6+v5 フィードバック反映：`MFSStatResult.is_sequential` 削除・`is_dir` 追加、`stat()` のディレクトリ対応（`IsADirectoryError` 廃止）、`MemoryFileSystem.__init__()` に `default_storage`/`max_nodes`/`promotion_hard_limit` パラメータ追加、`MFSNodeLimitExceededError` 例外新設（`MFSQuotaExceededError` のサブクラス）、`MFSTextHandle` テキストI/Oヘルパー追加（§5.6）、pytest プラグイン（`mfs` フィクスチャ）追加（§5.7）、`IMemoryFile._bulk_load()` インターフェース追加、`SequentialMemoryFile` の `allow_promotion`/`DEFAULT_PROMOTION_HARD_LIMIT` 追加、`export_as_bytesio()` TOCTOU修正（グローバルロック内でファイルロックを取得）、`truncate()` ゼロ埋め拡張対応（POSIX準拠）、パッケージ名 `dmemfs` に変更 |

---

## 第1部：ライブラリの本質と設計思想 (Philosophy & Non-Goals)

本ライブラリは、Pythonプロセス内に完全に閉じた「揮発性の仮想ファイルシステム・エミュレータ」である。開発者が自身のプログラム内で、既存のファイル操作パラダイムを維持したまま、安全かつ高スループットなオンメモリ処理を実装するための「箱庭」を提供する。

### 1.1 「非目標 (Non-Goals)」とカーネル隔離の必然性
* **汎用仮想ファイルシステム(VFS)ではない**
  OS（Windows/Linux等）からマウントポイントとして認識されるFUSEライクなVFSの構築は明確にスコープ外とする。
* **`os.PathLike` の意図的排除**
  標準の `os.PathLike` プロトコル（`__fspath__`）は構造的に非対応とする。サードパーティ製ライブラリや `open()` が仮想パスを物理パスと誤認し、OSへシステムコールを発行して物理ディスクを汚染（誤爆）する致命的リスクを完全に遮断するためである。
* **シンボリックリンク・ハードリンクの非サポート**
  構造の複雑化とパストラバーサル・ループのリスクを排除するため、リンク機能は一切サポートしない。

### 1.2 既存技術（tmpfs / io.BytesIO）との本質的差異と存在意義
「OS標準のRAMディスク（tmpfs/ramfs）で十分ではないか」「io.BytesIOのリストでよいのではないか」という指摘に対する、本ライブラリの明確な回答は以下の通りである。

* **vs. OS標準RAMディスク (tmpfs / ramfs)**
  速度面での比較は本質ではない。MFSは単なる「速い箱」ではなく、クォータと階層を備えた **in-process ワークスペース**である。OSのRAMディスク（tmpfs等）は、メモリ逼迫時にページングやOOMを通じてシステム全体へ影響を及ぼし得る。一方MFSは **プロセス内部のクォータ（中央銀行）**により、許容量を超える操作を開始前に拒否し、暴走を未然に抑止する。さらにWindows環境において、管理者権限やサードパーティ製ドライバ（ImDisk等）を要求せず、**ドライバレス／レジストリ無使用**で安全なインメモリ作業領域を即座に構築できる点は、ポータビリティ面で大きな優位性となる。
  > ※メモリが逼迫してOSがスワップを開始する環境では、クォータ設定の適切な見積もりが重要となる。

* **vs. `io.BytesIO`**
  `io.BytesIO` は単一ファイルのシミュレートに過ぎない。MFSは数千の微細なファイル群（ソース、ヘッダ、バイナリ等）を展開し、それらのディレクトリ階層構造を正確に維持・管理・検索するための「ファイルシステムとしてのオーケストレーション機能」を提供する。

### 1.3 防弾仕様（Bulletproof）の3原則
1. **絶対的リソース保護 (Bulletproof Quota)**: 中央銀行（Quota）がアロケーションを「書く前に拒否」し、プロセスをOOM（メモリ枯渇）から物理的に守る。
2. **ゼロ依存 (Zero-dependency)**: Python 3.11以上の標準ライブラリのみで構成し、バイナリコンパイルを必要とする外部依存を排除する。
   > **Python 3.11+ 要件の根拠**: `typing.Self`（PEP 673）による正確な戻り値型アノテーション（`__enter__() -> Self` 等）の利用、および Python 3.11 の CPython パフォーマンス改善を前提とした設計のため。なお `sqlite3.serialize` / `deserialize` は Python 3.8+ で利用可能であり、バージョン要件の根拠ではない。
3. **関心の分離 (Separation of Concerns)**: MFSは「純粋なバイト列の仮想階層管理とリソース制御」に徹する。テキストエンコーディングや暗号化、物理永続化は上位の境界コントローラーへ委譲する。

### 1.4 想定ユースケースと他手段では代替困難なメリット

#### 【主要ユースケース】

**UC-1: 巨大アーカイブの展開→加工→再パック**
zipやtarに格納された大量のファイルをMFS上に展開し、変換・フィルタリングを行ったうえで再パックする。物理ディスクへのI/Oを挟まないため、CIやサンドボックス環境における処理速度の向上と、中断時のゴミファイル残留リスクを同時に解消できる。

**UC-2: マルチステップETL/変換パイプラインのステージング領域**
パイプラインの各ステージが生成する中間成果物（変換済みCSV、正規化済みJSON、生成コード等）を、ステージ別・ジョブ別のディレクトリ構造でMFS上に保持する。ステージ間の受け渡しは `export_tree` / `import_tree` で完結し、失敗時はプロセス終了で中間ファイルが自動回収される。`Dirty` 差分エクスポートにより、変更分のみを後段へ引き渡すことも可能。`copy_tree()` によるステージ間のディレクトリ一括複製も利用可能。

**UC-3: 機密・一時データのプロセス内隔離処理**
復号後のバイナリ、生成コード、個人情報を含む中間ファイルなど「ディスクに落としたくないデータ」をMFS上で処理する。プロセス終了時に自動消去されるため、一時ファイルの手動削除やセキュアイレース処理が不要になる（スワップ・メモリダンプへの対策は別途必要）。

**UC-4: 権限制約環境での"プロセス内RAMディスク相当"**
企業PC・VDI・CI/CD Windowsランナーなど、管理者権限がなくOSレベルのRAMディスク（ImDisk等）を導入できない環境で、Pythonのみで即座に高速なインメモリ一時領域を構築できる。導入コストはゼロ（pip install のみ）。

**UC-5: MFS上のSQLite管理**
`sqlite3` の `serialize` / `deserialize`（非対応環境は互換目的で `iterdump` にフォールバック）を介してSQLiteデータベースをMFS上のファイルとして管理する。「SQLiteをMFSの管理下に置く」ことで以下が成立する：クォータによるDB肥大化の事前阻止、ジョブ単位の複数DBの階層管理、`export_tree` によるDBスナップショットとrollbackが統一インターフェースで実現可能。詳細は§4.3を参照。

---

#### 【他手段では代替困難なメリット】

| メリット | 詳細 | 代替手段の限界 |
|---|---|---|
| **ハードクォータによるOOM事前拒否** | 書き込み前にメモリ枯渇を検出し拒否。プロセスをOOMキラーから守る | `BytesIO`・tmpfs・`tempfile` はすべて「書いてから死ぬ」設計 |
| **大量ファイル＋階層構造をプロセス内で管理** | ディレクトリ構造を維持したまま数千ファイルを高速に作成・検索・移動できる | `BytesIO` は単一ファイル。辞書管理では空ディレクトリ・パス正規化・再帰削除が未解決 |
| **All-or-Nothing のアトミックインポート** | `import_tree` はクォータ超過時に全体をロールバック。データの部分書き込みが発生しない | 他のメモリFSライブラリにはアトミシティの概念がない |
| **差分スナップショット（Dirty flag）** | 変更ファイルのみを $O(1)$ で検出し、差分エクスポートが可能 | pyfakefs・PyFilesystem2 MemoryFS には差分エクスポートの仕組みがない |
| **実ディスク誤爆の構造的排除** | `os.PathLike` 非対応により、仮想パスが物理パスに渡ることを型レベルで防ぐ | tmpfsはPythonコードの誤操作でディスクを汚染するリスクが残る |
| **Windowsドライバレス展開** | 管理者権限・ドライバ・レジストリ変更なしに動作。`pip install` のみで導入可能 | OS RAMディスクはWindows環境で管理者権限またはサードパーティドライバを必要とする |
| **SSDへの大量テンポラリ書き込み回避** | 中間ファイルをプロセス内で完結させることで、SSDの書き込み量（TBW）消費低減に寄与し得る | tmpfs/ramfsはOSが存在する環境に限定。CI環境では利用不可なケースが多い |
| **ディレクトリツリーの一括複製** | `copy_tree()` でサブツリー全体をディープコピーし、独立した作業領域を即座に作成可能 | 他のメモリFSライブラリには一括ツリー操作のAPIがない |

---

## 第2部：アーキテクチャの全体像と並行性スタンス

MFSは、以下の主要コンポーネントによる階層構造を持つ。

### 2.0 全体構成

```
MemoryFileSystem (オーケストレータ + クォータ銀行)
    ├── ディレクトリインデックス層 (Directory Index Layer)
    │     ├── DirNode (名前 → NodeId のマッピング)
    │     └── FileNode (ストレージ参照 + RWロック + メタデータ + タイムスタンプ)
    ├── IMemoryFile (ストレージ抽象)
    │     ├── SequentialMemoryFile (list[bytes], 追記最適化)
    │     └── RandomAccessMemoryFile (bytearray, ランダムアクセス, shrink対応)
    ├── MemoryFileHandle (ストリームI/O)
    └── AsyncMemoryFileSystem (非同期ラッパー, v11)
```

### 2.1 ディレクトリインデックス層 (Directory Index Layer)

v9 までの MFS は `_tree: dict[str, IMemoryFile]` というフラットな辞書構造でファイルツリーを管理していた。v10 では、ファイル実体（データストレージ）とディレクトリ構造（メタデータツリー）を明確に分離する **ディレクトリインデックス層** を導入する。

#### 【導入目的】
- **`listdir` / `walk` / `glob` / `exists` の高速化**: フラット辞書のプレフィックススキャン $O(N)$ を、子ノードの直接参照 $O(\text{children\_count})$ に改善する。
- **`move` / `copy_tree` の仕様単純化**: ノード参照の付け替えのみで構造操作が完結する。
- **パス解決コストの削減**: ツリー走査による直接的な名前解決。
- **実体データと構造情報の分離**: ストレージ層とメタデータ層の関心が明確に分離され、保守性が向上する。

#### 【基本思想】
- ディレクトリは「名前 → ノードID」のみを保持し、ファイル内容データは一切持たない。
- ファイルの内容データは既存の `IMemoryFile`（Sequential / RandomAccess）に保持される。
- 本層は **インデックス（名前解決ツリー）** に専用であり、クォータ管理・データストレージとは独立する。

#### 【ノードモデル】

**NodeId**:
- `int` 型（単調増加ID）。グローバル一意。

**DirNode**:
```python
class DirNode:
    node_id: int
    children: dict[str, int]  # 子エントリ名 → NodeId
```
- フォルダ名から子ノードIDへのマッピングのみを保持する。
- ファイル本文やサイズ情報は持たない。
- 空ディレクトリは `children` が空辞書の `DirNode` として正確に表現される。

**FileNode** (v11 更新):
```python
class FileNode:
    node_id: int
    storage: IMemoryFile          # 実体データへの参照（Sequential or RandomAccess）
    _rw_lock: ReadWriteLock       # ファイル単位RWロック
    generation: int               # 変更検知用ID
    created_at: float             # [v11] 作成日時（time.time()）
    modified_at: float            # [v11] 最終更新日時（time.time()）
```
- `IMemoryFile` への参照を保持し、実際のデータ読み書きはストレージ層に委譲する。
- `_rw_lock` および `generation` はファイル単位のメタデータとしてここに帰属する。
- `created_at` と `modified_at` はファイル作成時に `time.time()` で初期化され、データ変更操作時に `modified_at` が更新される。

**グローバルノード管理**:
```python
_nodes: dict[int, DirNode | FileNode]  # NodeId → ノード
_next_node_id: int  # 次に割り振るNodeId（単調増加）
_root: DirNode      # ルートディレクトリ（NodeId=0）
```
グローバルな `_nodes` 辞書により、NodeIDから即座にノードを引ける。

#### 【パス解決】
- パス文字列は常に `/` で分割し、ルート `DirNode` からツリーを走査して解決する。
- フルパスをキーとするキャッシュは **禁止** する。理由は、`rename` / `move` 時にキャッシュの大量無効化が必要となり、整合性管理が複雑化するため。
- パス解決は常にツリー構造を正（Single Source of Truth）とする。

#### 【メモリモデル】
- `DirNode`: `children` 辞書のみ。巨大ディレクトリでなければオーバーヘッドは軽微。
- `FileNode`: ストレージ参照 + ロック + generation + タイムスタンプ。v9 の `IMemoryFile` が直接保持していたメタデータを分離したものであり、新規のオーバーヘッドはノードID管理分 + `float` × 2（タイムスタンプ）のみ。
- 通常のユースケース（数百〜数千ファイル）において、メタデータオーバーヘッドは実データに対して無視できる程度である。

#### 【v9 からの移行互換性】
ディレクトリインデックス層の導入は**内部実装の変更**であり、公開APIの互換性には影響しない。`MemoryFileSystem` クラスの全ての公開メソッド（`open`, `mkdir`, `rename`, `remove`, `rmtree`, `listdir`, `exists`, `is_dir`, `stats`, `export_tree`, `import_tree` 等）のシグネチャと動作セマンティクスは変更しない。

### 2.2 非同期処理 (asyncio) へのアーキテクチャ的スタンス

#### 【コアAPIの完全同期化】
MFS内部は待機時間ゼロのメモリアクセスであるため、コアAPIは純粋な同期API（`def`）とする。

#### 【外部I/Oとの連携】
ネットワークからの流入待ち等は、呼び出し側が外部I/Oの待機のみを `asyncio` で処理し、取得したチャンクをMFSの同期APIへ直接渡す設計を標準とする。巨大アーカイブの展開等、イベントループをブロックする処理は `asyncio.to_thread()` によるオフロードを推奨する。

#### 【v11 追加：AsyncMemoryFileSystem ラッパー】
v11 では、同期APIの上に薄い非同期ラッパー層 `AsyncMemoryFileSystem` を提供する（§6.4 で詳細設計）。コア同期APIへの変更は一切行わず、`asyncio.to_thread()` を使用してイベントループのブロッキングを回避する。

### 2.3 スレッドセーフと排他制御 (Readers-Writer Lock)

#### 【ロック種別と構造】

v10 では、ディレクトリインデックス層の導入に伴い、ロック種別は以下の4層構造となる。

| ロック | 種別 | 保護対象 | 実装 |
|---|---|---|---|
| `_global_lock` | FS全体ロック | 高レベルの構造変更の直列化（`rename`, `rmtree`, `import_tree` 等） | `threading.RLock` |
| `_quota._lock` | クォータロック | `_used` の排他的更新 | `threading.Lock`（QuotaManager 内部） |
| `_global_lock`（兼用） | メタデータツリーロック | ノードツリー構造の変更（ノード追加・削除・移動） | `threading.RLock`（`_global_lock` で兼用） |
| `FileNode._rw_lock` | ファイル単位ロック | ファイルデータの読み書き排他 | `ReadWriteLock`（独自実装） |

> **設計判断**: d-mfs 概要設計では `metadata_tree_lock` を独立したロックとして提案しているが、v10 では `_global_lock`（`threading.RLock`）がメタデータツリーロックを兼務する。理由は現時点の実用規模（数百〜数千ファイル）において、ロック競合によるスループット低下が顕著にならないためである。将来的に高並行性要件が発生した場合、`_global_lock` からメタデータツリーロックを分離することで段階的にスケーラビリティを向上できる設計拡張余地を残す。

#### 【PEP 703 (GIL-free Python) への対応方針】

v11 では、Python 3.13t（free-threaded build）での動作を見据え、以下の設計方針を定める（§6.3 で詳細設計）。

- **原則**: MFS の既存ロック設計は GIL に依存しない設計（`threading.RLock` + `ReadWriteLock`）であり、GIL フリー環境でも**基本的なスレッドセーフティは維持される**。
- **v10 での先行対応**: `wb` truncate 順序修正、`export_as_bytesio()` の `_global_lock` 保護は GIL フリー環境への布石として完了済み。
- **v11 での追加対応**: GIL フリー環境で顕在化し得る残存リスクの特定と対策を §6.3 で設計する。

#### 【ロック獲得順序（デッドロック防止規約）】

複合操作時のデッドロック防止のため、ロック取得順序を以下に**固定**する。全ての操作はこの順序を厳守しなければならない。

```
1. _global_lock（FS全体ロック / メタデータ兼務）
2. _quota._lock（QuotaManager 内部、通常は reserve() コンテキストマネージャ経由で自動取得）
3. FileNode._rw_lock（ファイル単位 Readers-Writer ロック）
```

* `_global_lock` は `threading.RLock`（再入可能ロック）であるため、同一スレッドが自動昇格とFS構造変更を同時に行う再帰ケースでもデッドロックしない。
* **逆順の取得は一切行ってはならない。**

#### 【ロック獲得タイミング】
* ロックは **`open()` 呼び出し時に取得し、`close()` まで一貫して保持する**。個々の `read()`/`write()` 呼び出しごとには取得しない。この設計により、ハンドルの生存期間中はロック状態が安定し、操作間のTOCTOU（Time-of-Check-Time-of-Use）競合を構造的に排除する。
* **読取専用モード (`rb`)**: 読み取りロック（共有）を取得。他スレッドの `rb` ハンドルと共存可能。
* **書込可能モード (`wb`/`ab`/`xb`/`r+b`)**: 書き込みロック（排他）を取得。既存のすべてのロック（読み取り・書き込み問わず）が解放されるまで待機する。

#### 【ブロッキング挙動と `lock_timeout`】
* デフォルト（`lock_timeout=None`）は、ロックが解放されるまで **無期限ブロッキング** で待機する。
* `open()` の `lock_timeout: float | None = None` パラメータにより挙動を制御する:
  - `None`（デフォルト）: 無期限待機（ブロッキング）。
  - `0.0`: ノンブロッキング（即時try-lock）。取得できなければ直ちに `BlockingIOError` を送出。
  - 正の浮動小数点数: 指定秒数まで待機。タイムアウト時に `BlockingIOError` を送出。

> **⚠️ 運用上の注意（ロックスコープ）**: ロックは `open()` から `close()` まで保持されるため、**ハンドルの長期保持は他スレッドとの競合を招く**。マルチスレッド環境では、ハンドルを短いスコープで使用し `with` 文で即座にクローズすることを強く推奨する。長時間の処理が必要な場合は `lock_timeout` による明示的なタイムアウト制御を検討すること。

> **⚠️ 運用上の注意（`_global_lock` 保持中のファイルロック待機）**: `open()` メソッドは `_global_lock` を保持した状態で `FileNode._rw_lock` のロック取得を試みる。これはロック順序規約の遵守およびTOCTOU回避のためのトレードオフである。`lock_timeout=None`（デフォルト）でファイルの書き込みロック取得に時間がかかる場合（例: 他スレッドが長時間読み取り中）、ファイルシステム全体が一時的にブロックされ得る。高並行性環境では `lock_timeout` を明示的に設定し、他のFS操作への影響を最小化することを推奨する。

> **v12 追記**: この制約は現行設計のトレードオフとして許容する。中期的な改善案として、`_global_lock` 下でのノード解決のみを行い、ロック解放後に `_rw_lock` を取得する設計への変更を検討する（TOCTOU 対策として、ロック取得後にノードの有効性を再チェックする）。ただし v12 時点では、`lock_timeout` の明示的設定による運用回避を推奨パターンとする。

#### 【v12 追加：GIL フリー環境での dict イテレーション安全性】

`walk()` および `glob()` は、`DirNode.children` を `list()` でスナップショット化してからイテレートする設計であるが、`list(dict.items())` 自体が GIL フリー環境でアトミックである保証は Python 仕様上存在しない。v12 では以下の対応方針を定める：

1. **`_walk_dir()` のスナップショット取得を `_global_lock` 下で実施**: 子ノードの一覧取得時に `_global_lock` を短期間取得し、`list(node.children.items())` を保護する。ロックは再帰呼び出しの前に解放する。
2. **`_glob_match()` においても同様に `_global_lock` 下でスナップショットを取得する。

これにより、GIL フリー環境（PEP 703, Python 3.13t）での `RuntimeError: dictionary changed size during iteration` を防止する。

> **パフォーマンスへの影響**: `_global_lock` の保持時間は `list()` コピーのみ（子ノード数に比例する $O(\text{children\_count})$）であり、深いツリーの再帰走査自体はロック外で実行されるため、影響は限定的。

---

## 第3部：堅牢な構造管理と外部インターフェース仕様

### 3.1 開発者向けインターフェース (OSError 準拠)
MFS独自の操作例外はPython標準の組み込み例外にマッピングし、直感的なエラーハンドリングを提供する。

| 例外クラス | 発生条件 |
|---|---|
| `FileNotFoundError` | 対象パスが存在しない |
| `FileExistsError` | 排他操作（`xb` / `mkdir(exist_ok=False)` / `rename` のdst衝突）で既存パスが障害 |
| `IsADirectoryError` | ファイル操作（`open`, `remove` 等）にディレクトリパスを指定した |
| `NotADirectoryError` | ディレクトリ操作（`listdir`, `rmtree` 等）にファイルパスを指定した |
| `BlockingIOError` | `lock_timeout` で指定した時間内にロックを取得できなかった |
| `MFSQuotaExceededError` | `OSError` のサブクラス。クォータ上限到達時 |
| `MFSNodeLimitExceededError` | `MFSQuotaExceededError` のサブクラス。`max_nodes` 上限到達時 [v13 追加] |
| `io.UnsupportedOperation` | モード違反（`rb` ハンドルへの `write()` 等）、または自動昇格のハードリミット超過 |
| `ValueError` | パストラバーサル検出、`seek` の不正 `whence`/負オフセット、テキストモード指定等 |

> **注**: MFSにはOSレベルのユーザー権限（rwx）モデルは存在しないため、`PermissionError` はMFSの通常操作では送出しない。

### 3.2 パス正規化とトラバーサル防止
* **正規化**: 入力されたパスはすべて `posixpath.normpath(path.replace('\\', '/'))` によってPOSIX形式に正規化される。Windows環境特有のバックスラッシュも透過的に吸収し、一貫した内部表現を保証する。
* **トラバーサル防止**: 仮想ルート（`/`）を超える遡上（`../`）は `ValueError("Path traversal attempt detected")` として即座に遮断し、ツリー構造を保護する。

### 3.3 世代ID (Generation ID) によるDirtyフラグ管理
各ファイルは `FileNode` 内に変更検知用ID（`generation`）を持ち、更新時・確定時にカウントアップされる。これにより、ロード時から変更があったファイル（Dirty）だけを$O(1)$で判定可能にする。

---

## 第4部：拡張機能とサードパーティ統合 (The Bridge)

`os.PathLike` を排除したことによるトレードオフを、安全な専用APIによって解決する。

### 4.1 BytesIO ブリッジ API
指定パスのデータを標準の `io.BytesIO` として提供し、`pandas.read_csv()` や `PIL` 等の外部エコシステムとシームレスに連携する。

* **セマンティクス（明確化）**: 本APIが返却する `BytesIO` は、内部データの「**ディープコピー**」である。そのため、返却後にMFS上のファイルが変更されても `BytesIO` 側には反映されない。コピー実行中はファイルの読み取りロックを取得し、コピー完了後に解放する（他スレッドによる書き込みでコピーデータが不整合になることを防ぐ）。
* **メモリ消費の注意**: コピーに伴う一時的なメモリ増加はMFSのクォータ管理外（Python標準のヒープ領域）で発生する。巨大ファイルでの使用は計画的に行うこと。
* **`max_size` ガード**: `max_size: int | None = None` パラメータにより、指定バイト数を超えるファイルのエクスポートを `ValueError` で事前に拒否できる。クォータ外のメモリ増大を呼び出し側が予防的に制御するためのオプション機構として提供する。
* **`_global_lock` によるエントリ保護**: `_global_lock` でエントリの存在を確認してからファイルロックを取得する。GILフリーPython（PEP 703）環境においても、エントリ参照の競合を回避する。

### 4.2 スナップショット＆エクスポート API
上位層と効率的にデータをやり取りするため、ツリー全体の一括入出力を提供する。

* **`export_tree`（一括エクスポート）**: `dict[str, bytes]` でFS全体を返却する。FSサイズが小さい場合や、辞書全体を即時必要とするケースに適する。`only_dirty=True` による差分エクスポートで2回目以降のピークメモリを削減可能。初回フルエクスポートでは実質2倍のメモリを消費することを呼び出し側は認識すること。

* **`iter_export_tree`（ストリーミングエクスポート）**: `Iterator[tuple[str, bytes]]` として遅延評価でエントリを逐次返却するジェネレータAPI。FS全体を一度にメモリへ展開しないため、大規模FSや外部ストリームへの書き出しに適する。`only_dirty=True` にも対応する。
  - **スレッド安全性**: イテレーション開始時に `_global_lock` 下でパスキーのスナップショットを取得する。各エントリのデータ読み取りは個別にファイルの読み取りロックを取得して行う。イテレーション中に他スレッドがファイルを削除した場合は当該エントリをスキップする（弱整合性: キーセットはイテレーション開始時点で確定、データは読み取り時点での最新値）。

  ```python
  # 使用例（ストリーミング書き出し）
  for path, data in mfs.iter_export_tree():
      archive.write(path, data)
  ```

* **`import_tree`（アトミックインポート）**: 「All-or-Nothing」を完全に保証する。実行中にクォータ超過（`MFSQuotaExceededError`）が発生した場合、処理全体がロールバックされインポート開始前のMFS状態が維持される。インポート対象パスにオープン済みのハンドルが存在する場合は `lock_timeout=0.0` 相当でフェイルファスト（`BlockingIOError`）とし、部分書き込みが発生しないようアトミシティを保護する。

### 4.3 SQLite 統合 / プラガブル・アーカイブ展開

#### SQLite 統合
SQLiteはVFS拡張を用いず、**`sqlite3.Connection.serialize()` / `deserialize()`** によりDB内容をMFS上のバイト列ファイルとして管理する。これにより、DBもクォータ管理・階層管理・スナップショット/exportの枠組みに自然に乗る。

**標準フロー（コード例）**:
```python
import sqlite3

# ── DB → MFS へ保存（クォータ超過なら開始前に拒否）──────────────
conn = sqlite3.connect(":memory:")
# ... DBを操作 ...
data: bytes = conn.serialize()
with mfs.open("/jobs/job1/state.db", "wb") as f:
    f.write(data)

# ── MFS → DB へ復元 ──────────────────────────────────────────────
with mfs.open("/jobs/job1/state.db", "rb") as f:
    data = f.read()
conn2 = sqlite3.connect(":memory:")
conn2.deserialize(data)
```

**フォールバック（互換環境向け）**: `sqlite3.Connection.serialize()` が利用できない環境（Python 3.7 以前等、ただし本ライブラリの動作要件外）では `iterdump` によるSQLテキストダンプを使用する。パフォーマンス目的ではなく **互換性確保**が唯一の目的であり、バイナリ直列化より低速であることに注意すること。

#### アーカイブ展開
`zipfile` 等を用い、MFSに対してチャンク単位で直接解凍する共通IFを提供する。

### 4.4 ツリー操作 API

ディレクトリインデックス層の導入により、ディレクトリ単位の一括操作を効率的かつ安全に提供する。

* **`copy_tree(src: str, dst: str) -> None`**: ディレクトリツリー全体のディープコピーを実行する。
  - `src` 配下のサブツリーを再帰走査し、`dst` に新しいノードとして複製する。
  - `NodeId` はすべて新規生成される（独立したコピー）。
  - ファイルの実体データ（`IMemoryFile`）は**ディープコピー**（バイト列の完全複製）を行う。参照共有（CoW）ではない。
  - コピーによるデータ増分のクォータ予約はコピー前に事前チェックされ、不足時は `MFSQuotaExceededError` を送出して何も変更しない。
  - `src` が存在しない場合は `FileNotFoundError`。
  - `src` がディレクトリでない場合は `NotADirectoryError`。
  - `dst` が既に存在する場合は `FileExistsError`。
  - `dst` の親ディレクトリが存在しない場合は `FileNotFoundError`。

* **`move(src: str, dst: str) -> None`**: ファイルまたはディレクトリの移動。`rename()` と異なり、`dst` の親ディレクトリが存在しない場合は中間ディレクトリを自動作成する。
  - `src` が存在しない場合は `FileNotFoundError`。
  - `dst` が既に存在する場合は `FileExistsError`。
  - ファイルの場合: ノードの親を変更するだけで $O(1)$。内容データのコピーは発生しない。
  - ディレクトリの場合: サブツリー全体の参照を新しい親に付け替える。
  - `src` またはその配下にオープン済みハンドルが存在する場合は `BlockingIOError`（フェイルファスト）。

---

## 第5部：クラス構成と詳細API仕様 (Detailed Interface Specification)

### 5.1 MFS本体：`MemoryFileSystem` クラス

#### 【プロパティ / 内部状態】

* `_root: DirNode`: ルートディレクトリノード（NodeId=0）。
* `_nodes: dict[int, DirNode | FileNode]`: NodeId から各ノードへの参照辞書。
* `_next_node_id: int`: 次に割り振るNodeId（単調増加）。
* `_max_quota: int`, `_used_quota: int`: 利用可能な最大/使用済みメモリ量。
* `_global_lock: threading.RLock`: FS全体の構造変更を保護するロック。
* `_max_nodes: int | None` [v13 追加]: ノード数上限（`None` は無制限）。超過時は `MFSNodeLimitExceededError`。
* `_default_storage: str` [v13 追加]: ファイル生成時のストレージ種別。`"auto"` (デフォルト) / `"sequential"` / `"random_access"`。
* `_promotion_hard_limit: int | None` [v13 追加]: Sequential→RandomAccess 自動昇格のバイト上限。`None` の場合は `SequentialMemoryFile.DEFAULT_PROMOTION_HARD_LIMIT` (512MB) を使用。

#### 【計算量特性（v9 からの改善）】

ディレクトリインデックス層の導入により、以下の操作の計算量が改善される。

| 操作 | v9 (フラット辞書) | v10 (ディレクトリインデックス) |
|---|---|---|
| `listdir(path)` | $O(N)$ — 全キーのプレフィックススキャン | $O(\text{children\_count})$ — `DirNode.children` の直接参照 |
| `exists(path)` | $O(1)$ — 辞書ルックアップ | $O(d)$ — パス深度 $d$ でのツリー走査 |
| `rename(src, dst)` (ファイル) | $O(1)$ | $O(d)$ — 親ノードの `children` 更新 |
| `rename(src, dst)` (ディレクトリ) | $O(N)$ — 配下全キー書き換え | $O(d)$ — 親ノードの `children` 更新のみ |
| `walk(path)` | $O(N)$ — 毎階層でプレフィックススキャン | $O(\text{subtree\_size})$ — ツリー走査 |
| `glob(pattern)` | $O(N)$ — 全キーマッチング | $O(\text{subtree\_size})$ — ツリー走査 |
| `rmtree(path)` | $O(N)$ — プレフィックスでフィルタ | $O(\text{subtree\_size})$ — サブツリー走査 |

> $N$: FS全体のエントリ数、$d$: パスの深度（平均的に小さい定数）、$\text{children\_count}$: 直下の子ノード数、$\text{subtree\_size}$: サブツリー内のノード数

#### 【リソース管理・トランザクションAPI (内部向け)】
* `reserve_quota(size: int) -> ContextManager`:
  - `with` ブロック突入時に上限超過を判定（超過時 `MFSQuotaExceededError`）。例外で抜けた場合（ロールバック）は枠を解放、正常終了で確定する。
* `_release_quota(size: int) -> None`: 削除や縮小時に即座に枠を返却する。

#### 【内部API制約：`_force_reserve()` の使用条件】[v12 追加]

`QuotaManager._force_reserve(size)` は、上限チェックを行わずに `_used` を加算する内部専用メソッドである。以下の使用条件を厳守する：

1. **`_global_lock` 保持下でのみ呼び出し可能**: 他スレッドからの干渉を防ぐため。
2. **呼び出し前に `free` との比較によるクォータ事前チェックが完了していること**: `_force_reserve` 自体は上限チェックを行わないため、呼び出し元が責任を持つ。
3. **使用箇所**: `import_tree()` および `copy_tree()` のみ。通常のファイル操作では `reserve()` コンテキストマネージャを使用すること。

> **設計理由**: `import_tree()` / `copy_tree()` では、データコピーの完了後にクォータを一括加算する必要がある。`reserve()` コンテキストマネージャは「確保→操作→確定 or ロールバック」のパターンだが、これらの一括操作ではデータコピーが完了するまでクォータを確定できないため、事前チェック + `_force_reserve` のパターンを採用している。

> **v12 変更**: `_NoOpQuotaManager` クラス（`_fs.py` に定義されていた未使用のクォータバイパスクラス）を削除した。対応する `from contextlib import contextmanager` のインポートも `_fs.py` からは削除する。

#### 【ファイル操作API (公開)】
* `open(path: str, mode: str = 'rb', preallocate: int = 0, lock_timeout: float | None = None) -> MemoryFileHandle`:
  - `preallocate`: バイト単位で事前クォータを確保し、ファイルをNullバイト（ゼロ）で該当サイズまで埋める。**事前確保された領域内への `write()` では追加のクォータ予約は不要**（すでに計上済み）。事前確保サイズを超えて書き込む場合のみ、超過分のクォータ予約が新たに発生する。
  - `lock_timeout`: §2.3「ブロッキング挙動と `lock_timeout`」参照。
  - **モード仕様の厳密定義**: テキストモード（`r`, `w` 等、バイナリ接尾辞 `b` を持たない形式）は `ValueError`。
    - `rb` (読取専用): 存在しない場合は `FileNotFoundError`。読み取りロック（共有）を取得。
    - `wb` (書込専用): 非存在時は新規作成、存在時は**書き込みロック（排他）を取得した後に**サイズ0に `truncate`（縮小分のクォータは即時返却）。
    - `ab` (追記): 非存在時は新規作成、存在時は初期シーク位置を末尾へ。書き込みロック（排他）を取得。
    - `r+b` (読書両用): 存在しない場合は `FileNotFoundError`。truncateは行わず先頭から上書き可能。書き込みロック（排他）を取得。
    - `xb` (排他作成): 非存在時は新規作成、存在時は `FileExistsError`。書き込みロック（排他）を取得。

  > **v10 変更**: `wb` モードにおける `truncate()` の実行タイミングを、書き込みロック取得**後**に移動した。v9 ではロック取得前に `truncate()` を実行していたが、既にオープン済みの読み取りハンドルが存在する場合に `truncate()` がそのハンドルの読み取り対象データを破壊する理論的リスクがあった。GILフリーPython（PEP 703）への備えとしても、この修正は必須である。

* `mkdir(path: str, exist_ok: bool = False) -> None`: 対象パスと、存在しない全ての中間ディレクトリを作成する（`os.makedirs(parents=True)` 相当の動作）。
  - ディレクトリインデックス層の `DirNode` を新規作成し、親ノードの `children` に登録する。
  - **互換注意**: `os.mkdir` は中間ディレクトリが存在しない場合に `FileNotFoundError` を送出するが、本メソッドは常に親を暗黙作成する。`os.mkdir` 互換の厳密動作が必要な場合は、呼び出し前に `exists()` で親の存在を確認すること。

* `rename(src: str, dst: str) -> None`: ファイルまたはディレクトリを `src` から `dst` へ改名・移動する。
  - `_global_lock` を取得（構造変更）。
  - `src` が存在しない場合は `FileNotFoundError`。
  - `dst` がすでに存在する場合は `FileExistsError`。
  - `dst` の親ディレクトリが存在しない場合は `FileNotFoundError`。
  - ディレクトリインデックス層では、親ノードの `children` を更新するだけで完了する（ファイル、ディレクトリ問わず $O(d)$）。ノードのIDや内容データは変更されない。
  - ルート（`/`）の改名は `ValueError`。
  - `src` またはその配下にオープン済みハンドルが存在する場合は `BlockingIOError`（フェイルファスト）。
  - **タイムスタンプ**: `rename` はメタデータ操作であり、ファイルの `modified_at` は更新しない（POSIX 準拠: `rename(2)` はファイルの ctime を更新するが mtime は変更しない）。

* `move(src: str, dst: str) -> None`: ファイルまたはディレクトリを `src` から `dst` へ移動する。`rename()` との違いは、`dst` の親ディレクトリが存在しない場合に中間ディレクトリを自動作成する点。
  - `src` が存在しない場合は `FileNotFoundError`。
  - `dst` がすでに存在する場合は `FileExistsError`。
  - `src` またはその配下にオープン済みハンドルが存在する場合は `BlockingIOError`（フェイルファスト）。
  - ルート（`/`）の移動は `ValueError`。

* `remove(path: str) -> None`: ファイルを削除する。削除分のクォータを `_release_quota()` へ通知する。対象がディレクトリの場合は `IsADirectoryError`。オープン済みハンドルが存在する場合は `BlockingIOError`（フェイルファスト）。ディレクトリインデックス層では、親ノードの `children` からエントリを削除し、`_nodes` から `FileNode` を除去する。

* `rmtree(path: str) -> None`: ディレクトリとその配下を再帰的に削除する。削除分のクォータを確実に `_release_quota()` へ通知する。ルート（`/`）の削除は `ValueError`。配下のいずれかにオープン済みハンドルが存在する場合は `BlockingIOError`（フェイルファスト）。ディレクトリインデックス層では、サブツリーを再帰走査し、全ノードを `_nodes` から除去する。

* `copy(src: str, dst: str) -> None`: ファイルの内容をバイト単位でディープコピーする。
  - `src` が存在しない場合は `FileNotFoundError`。
  - `src` がディレクトリの場合は `IsADirectoryError`。
  - `dst` が既に存在する場合は `FileExistsError`。
  - `dst` の親ディレクトリが存在しない場合は `FileNotFoundError`。
  - コピーにより増加するデータ分のクォータ予約を事前に行い、不足時は `MFSQuotaExceededError` を送出して何も変更しない。
  - コピー先のファイルは新規の `FileNode`（新しい NodeId、新しいタイムスタンプ）として作成される（POSIX の `cp` 相当）。

* `copy_tree(src: str, dst: str) -> None`: ディレクトリツリー全体をディープコピーする（§4.4 参照）。

* `exists(path: str) -> bool`, `is_dir(path: str) -> bool`: パスの存在確認・ディレクトリ判定。ディレクトリインデックス層ではパスをツリー走査して NodeId を解決する。

* `listdir(path: str) -> list[str]`: **ディレクトリ直下のエントリ名のみ**を返す（フルパスではない）。Python標準の `os.listdir()` の挙動と一致する。ディレクトリインデックス層では `DirNode.children.keys()` をそのまま返却するため、$O(\text{children\_count})$ で完了する。
  - 例: `/dir/sub/` 配下に `file.txt` と `child/` が存在する場合、`listdir("/dir/sub")` は `["file.txt", "child"]` を返す。
  - 対象パスがファイルの場合は `NotADirectoryError`。
  - 対象パスが存在しない場合は `FileNotFoundError`。
  - **v12 変更**: `_global_lock` 下でノード解決およびスナップショット取得を行うよう変更（GIL フリー環境での安全性確保）。

* `get_size(path: str) -> int`: ファイルのサイズ（バイト数）を返す。ディレクトリの場合は `IsADirectoryError`。
  - **v12 変更**: `_global_lock` 下でノード解決を行うよう変更（GIL フリー環境での安全性確保）。

* **`stat(path: str) -> MFSStatResult`** [v11 追加]: 指定パスのファイルまたはディレクトリのメタデータを返す（§6.1 で詳細設計）。[v13 変更] ディレクトリを指定した場合も `IsADirectoryError` を送出せず、`is_dir=True` の `MFSStatResult` を返す。
  - 返却型: `MFSStatResult`（`TypedDict`）
  - ディレクトリの場合は `IsADirectoryError`。
  - パスが存在しない場合は `FileNotFoundError`。

* `walk(path: str = '/') -> Iterator[tuple[str, list[str], list[str]]]`: ディレクトリツリーを再帰的に走査し、各ディレクトリについて `(dirpath, dirnames, filenames)` を yield する。`os.walk()` のトップダウン走査と同様の挙動。ディレクトリインデックス層では `DirNode.children` を直接走査するため、フラット辞書のプレフィックススキャンに比べて効率的。
  - **⚠️ スレッドセーフティ（弱整合性）**: `walk()` は内部で `listdir()` を再帰的に呼び出すが、呼び出し間に `_global_lock` を保持しない。イテレーション中に他スレッドがディレクトリ構造を変更した場合、不整合が生じ得る（例: `listdir()` で得た子ディレクトリが次の走査で削除されている）。この場合、削除されたエントリはスキップされる（クラッシュはしない）。完全に一貫したスナップショットが必要な場合は、呼び出し側で排他制御を行うこと。

* `glob(pattern: str) -> list[str]`: パターンにマッチするパスの一覧をソートして返す。
  - **グロブパターンのセマンティクス（v10 更新）**:
    - `*`: 単一階層内の任意の文字列にマッチする（パス区切り `/` にはマッチしない）。
    - `**`: ゼロ個以上のディレクトリにマッチする（再帰ワイルドカード）。
    - `?`: 任意の1文字にマッチする（パス区切り `/` を除く）。
    - `[seq]`, `[!seq]`: 文字クラスの指定。
  - 例: `glob("/dir/**/*.txt")` は `/dir/` 配下の全階層にある `.txt` ファイルにマッチする。
  - 例: `glob("/dir/*.txt")` は `/dir/` 直下の `.txt` ファイルのみにマッチする。
  - ディレクトリインデックス層では `DirNode.children` を再帰走査することで自然に実装可能（深さ優先）。
  - **弱整合性**: `walk()` と同様、イテレーション中の構造変更に対しては弱整合性モデルを適用する。

* `stats() -> dict`: MFSの現在の使用状況を返す。クォータ計算の内訳確認やデバッグに利用する。
  - 返却キー:
    - `used_bytes: int` — クォータとして計上済みの総バイト数（実データ＋オーバーヘッド推定含む）
    - `quota_bytes: int` — 設定された最大クォータ
    - `free_bytes: int` — 残余クォータ（`quota_bytes - used_bytes`）
    - `file_count: int` — ファイルエントリ数
    - `dir_count: int` — ディレクトリエントリ数
    - `chunk_count: int` — `SequentialMemoryFile` が保持するチャンク総数。**`RandomAccessMemoryFile` に昇格済みのファイルは含まれない**（昇格後は `bytearray` の単一バッファとなりチャンクの概念が存在しないため）。
    - `overhead_per_chunk_estimate: int` — 現在の環境で使用しているチャンクあたりのオーバーヘッド推定値（§5.2参照）

#### 【境界ブリッジ・スナップショットAPI (公開)】
* `export_as_bytesio(path: str, max_size: int | None = None) -> io.BytesIO`
* `export_tree(prefix: str = "/", only_dirty: bool = False) -> dict[str, bytes]`
* `iter_export_tree(prefix: str = "/", only_dirty: bool = False) -> Iterator[tuple[str, bytes]]`
* `import_tree(tree: dict[str, bytes]) -> None`

---

### 5.2 内部ストレージ層：`IMemoryFile` (Interface)

ディレクトリインデックス層導入後も、`IMemoryFile` はファイルデータの実体ストレージとして引き続き使用される。ただし、`is_dir`・`generation`・`_rw_lock` は `FileNode` に移管される。

#### 【プロパティ / 内部状態】
* ~~`is_dir: bool`~~ → `DirNode` / `FileNode` の型で判別（v10 変更）
* ~~`generation: int`~~ → `FileNode.generation` に移管（v10 変更）
* ~~`_rw_lock: ReadWriteLock`~~ → `FileNode._rw_lock` に移管（v10 変更）

#### 【実装クラスと I/O API (内部向け)】
1. **`SequentialMemoryFile`**: `list[bytes]` 保持。追記特化型。
  - **クォータ計算（キャリブレーション方式）**: 実データサイズに加え、チャンク管理に伴うPythonオブジェクトのオーバーヘッドをクォータに計上する。理論値は `bytes` オブジェクト本体（CPython 64bit 環境で約56バイト）＋リストエントリのポインタ（約8バイト）のチャンクあたり約64バイトだが、この値はPythonのビルド・バージョン・プラットフォームによって変動する。そのため実装では、**ライブラリ初期化時に `sys.getsizeof` 等で基準値をキャリブレーションし、その観測値に安全マージン（倍率・加算定数）を乗じた推定値**を採用する。推定パラメータは利用者が上書き可能とし、過少見積もりによるクォータ超過の見逃しを防ぐことを優先する（若干の過大計上は許容）。現在の推定値は `mfs.stats()` の `overhead_per_chunk_estimate` で確認できる。
  - **O(log N) チャンク読み取り**: `_cumulative` 配列（チャンク末尾位置の累積配列）と `bisect.bisect_right` を使用し、対象チャンクを高速に特定する。
  - **`DEFAULT_PROMOTION_HARD_LIMIT: int = 512 * 1024 * 1024`** [v13 追加]: Sequential→RandomAccess 自動昇格の上限。これを超えるサイズでも昇格しない（`io.UnsupportedOperation` は送出しない）。
  - **`allow_promotion: bool`** [v13 追加]: `False` の場合、末尾以外へのランダム書き込みが要求されたとき昇格せず `io.UnsupportedOperation` を送出する。
2. **`RandomAccessMemoryFile`**: `bytearray` 保持。部分書き換え対応型。**v11 で shrink 機構を追加**（§6.2 で詳細設計）。
* `read_at(offset: int, size: int) -> bytes`
* `write_at(offset: int, data: bytes) -> tuple[int, RandomAccessMemoryFile | None, int]`: `Sequential` において末尾以外のオフセット指定時は自動昇格を発火。戻り値は `(written_bytes, promoted_file_or_None, old_data_size)` のタプル。なお、実装上は `_PromotionSignal` 例外による通知パターンも許容される（大半の呼び出しでタプル分解が不要で効率的）。現行実装では `_PromotionSignal` パターンを採用している。
* `truncate(size: int) -> None`: 縮小分は `_release_quota()` へ通知。**v11**: `RandomAccessMemoryFile` においてサイズが大幅に縮小された場合、`bytearray` の shrink（再割り当て）を実施する（§6.2 参照）。**v13**: サイズ拡張時はゼロ埋め（POSIX準拠）。
* `get_size() -> int`
* `get_quota_usage() -> int`: クォータ計算に使用する現在のメモリ使用量を返す。`SequentialMemoryFile` は `self._size + len(self._chunks) * self._chunk_overhead`、`RandomAccessMemoryFile` は `len(self._buf)` を返す。
* **`_bulk_load(data: bytes) -> None`** [v13 追加]: クォータチェックを行わずデータを一括ロードする抽象メソッド。呼び出し側（`import_tree()`、`_deep_copy_subtree()` 等）がクォータ予約済みであることを前提とする。

---

### 5.3 ストリームI/O層：`MemoryFileHandle` クラス

#### 【プロパティ / 内部状態】
* `_mfs: MemoryFileSystem`, `_file: FileNode`, `_mode: str`
* `_cursor: int`: 現在のシーク位置。
* `_is_closed: bool`: ライフサイクル管理フラグ。

#### 【I/O・ライフサイクル API (公開)】

* `read(size: int = -1) -> bytes`:
  - `size=-1` または省略時: ファイル末尾まで全読み取り。
  - 正値: 最大 `size` バイトを読み取り、カーソルを進める。要求バイト数に満たないデータしかない場合は残り全てを返す。
  - **EOF時の挙動**: カーソルがファイル末尾以降に達している場合は `b""` を返す。Python標準の `io.RawIOBase` と同等の挙動。
  - 書込専用モード（`wb`, `ab`, `xb`）で呼び出した場合は `io.UnsupportedOperation`。

* `write(data: bytes) -> int`:
  - 書き込み位置（カーソル）とデータ長から算出される新ファイルサイズが現在のファイルサイズを上回る場合、差分バイト数（`max(0, cursor + len(data) - current_size)`）のみ `reserve_quota` で予約する。既存領域への上書き（ファイルサイズ不変）はクォータ変動なし。preallocateで確保済みの領域内への書き込みもクォータ変動なし（§5.1 `preallocate` 参照）。
  - **`ab` モードの write**: `ab` モードでは、`write()` 呼び出し時に毎回カーソルを自動的にEOFへ移動してから書き込む（POSIX互換の追記保証）。`seek()` でカーソルを移動しても次の `write()` で無効化される。
  - 読取専用モード（`rb`）で呼び出した場合は `io.UnsupportedOperation`。
  - 書き込んだバイト数を返す。
  - **タイムスタンプ更新** [v11]: 書き込みが成功した場合、`FileNode.modified_at` を `time.time()` で更新する。

* `seek(offset: int, whence: int = 0) -> int`:
  - `whence` の対応値:
    - `0`（`io.SEEK_SET`）: ファイル先頭からの絶対位置。`offset` は 0 以上。
    - `1`（`io.SEEK_CUR`）: 現在位置からの相対位置。
    - `2`（`io.SEEK_END`）: ファイル末尾からの相対位置。`offset` は 0 以下のみ有効（`-n` で末尾から `n` バイト前、`0` で末尾位置）。正の `offset` は `ValueError`（ファイル末尾を超えたシークは未サポート）。
  - 上記以外の `whence` 値は `ValueError`。
  - 計算結果のカーソル位置が負になる指定は `ValueError`。
  - 新しいカーソル位置を返す。

* `tell() -> int`: 現在のカーソル位置を返す。

* `close() -> None`: コミットを実行し、`FileNode._rw_lock` を解放する。以後の操作は `ValueError` を送出する。

* `__enter__() -> Self`, `__exit__(...) -> None`: コンテキストマネージャ。`__exit__` は例外の有無にかかわらず `close()` を呼び出す。

* **`__del__() -> None`**: リソースリークに対する **最終防波堤**。GC回収時に `_is_closed` がFalseであれば、標準の `ResourceWarning` を送出し、内部的に `close()` をフォールバック実行してWriteロックと一時クォータの解放を試みる。
  - **⚠️ 重要**: `__del__` の呼び出しタイミングはPythonランタイムによって保証されない（CPython以外の実装、循環参照、プロセス終了時等）。ロックやクォータの即時解放が必要な場面では `__del__` に依存してはならない。
  - **推奨**: ハンドルは必ず `with` 文（コンテキストマネージャ）で使用すること。`__del__` はあくまで `with` 文を使い忘れた場合の安全網として機能する。
  - **`stacklevel`**: `warnings.warn()` の `stacklevel` は `1` を使用する。`__del__` はGCから呼び出されるため、`stacklevel=2` ではGC内部を指し、ユーザーコードの呼び出し元を正確に指すことは期待できない。

#### 【MFS インスタンスの生存と GC】
`MemoryFileHandle` は `_mfs` フィールドで `MemoryFileSystem` インスタンスへの強参照を保持する。そのため、オープン中のハンドルが1つでも存在する限り、`MemoryFileSystem` インスタンスはガベージコレクションされない（CPythonの参照カウント方式においては確実）。MFS側に `__del__` でのハンドル強制クローズ処理は不要であり、実装しない。

---

### 5.4 トランザクション的自動昇格の実装フロー
自動昇格は `FileNode` のストレージ参照の差し替えであり、ディレクトリインデックス層のノード構造変更を伴わない。したがって **`_global_lock` は不要**であり、`open()` 時に取得済みの書き込みロックが保護を担う。

1. `write_at` 時、オフセットが末尾以外であれば昇格を発火。
2. ハードリミット超過判定（超過時は `io.UnsupportedOperation` を送出）。
3. `with mfs.reserve_quota(current_size):` にて一時的な2倍メモリの枠を確保。
4. 新しい `bytearray` を生成しデータをディープコピー。
5. `FileNode.storage` の参照先を新しい `RandomAccessMemoryFile` に差し替え（既存書き込みロック下で安全に実行可能）。
6. コピー完了後、`mfs._release_quota(current_size)` で旧バッファ枠を即座に解放。

---

### 5.5 整合性モデル

以下の操作には**弱整合性（Weak Consistency）**を適用する。

| 操作 | 整合性モデル |
|---|---|
| `walk()` | 弱整合 — イテレーション中の構造変更に対して、クラッシュはしないが完全なスナップショットは保証しない |
| `glob()` | 弱整合 — 同上 |
| `iter_export_tree()` | 弱整合 — キーセットはイテレーション開始時点のスナップショット、データは読み取り時点の最新値 |

**保証する事項**:
- これらの操作中に他スレッドが構造変更を行ってもクラッシュ（例外の送出、データ破壊）しない。
- 削除されたエントリはスキップされる。

**保証しない事項**:
- 完全に一貫したスナップショットの提供。
- イテレーション中に追加されたエントリの包含。

完全に一貫したスナップショットが必要な場合は、呼び出し側で排他制御（例: `_global_lock` の外部公開、または `import_tree` → `export_tree` による複製）を使用すること。

### 5.6 テキストI/Oヘルパー：`MFSTextHandle` クラス [v13 追加]

#### 【設計判断】

§1.3 の設計原則第3条「MFSは純粋なバイト列の仮想階層管理に徹する」に基づき、`MemoryFileSystem.open()` のモード仕様は **バイナリモードのみ**（`rb`, `wb`, `ab`, `r+b`）を維持する。テキストモード（`r`, `w` 等）は引き続き `ValueError` を送出する。

`MFSTextHandle` は `MemoryFileSystem` の外に位置する**オプショナルなユーティリティクラス**であり、ファイルシステム層のAPIには一切侵入しない。ユーザーが明示的にインポートして使用する。

標準の `io.TextIOWrapper` を採用しない理由は以下の通り：

1. **`readinto()` の要求**: `TextIOWrapper` はラップ対象に `readinto()` を要求するが、`MemoryFileHandle` は提供しない。追加はバッファプロトコルとの密結合を招く。
2. **バッファリングとクォータの衝突**: `TextIOWrapper` の内部バッファにより、`flush()` までクォータ計上が遅延する。ハードクォータの「書く前に拒否する」契約と矛盾する。
3. **`seek` の cookie 問題**: `TextIOWrapper` の `seek()` はバイトオフセットではなく不透明な cookie を使用し、`MemoryFileHandle` のバイト単位 seek と噛み合わない。

#### 【クラス定義】

```python
class MFSTextHandle:
    def __init__(
        self,
        handle: MemoryFileHandle,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> None: ...
```

#### 【プロパティ】

| プロパティ | 型 | 説明 |
|---|---|---|
| `encoding` | `str` | テキストエンコーディング（読み取り専用） |
| `errors` | `str` | デコードエラーハンドリング（読み取り専用） |

#### 【API】

* `write(text: str) -> int`: テキストをエンコードしてバイナリハンドルに書き込む。戻り値は**文字数**（バイト数ではない）。書き込みは即座にバイナリハンドルに委譲され、クォータチェックはリアルタイムで実行される（バッファなし）。

* `read(size: int = -1) -> str`: バイナリハンドルからバイト列を読み取り、デコードして返す。`size=-1` はファイル全体を読み取る。`size >= 0` の場合、`size` は**バイト数の近似値**として扱われる（文字数ではない）。マルチバイト文字（UTF-8 の日本語等）では、要求した文字数より少ない文字が返される可能性がある。

* `readline(limit: int = -1) -> str`: 1行を読み取る。改行コードは `\n`、`\r\n`、`\r`（ベア）の3種を認識する。`limit` はバイト数上限（`-1` は無制限）。実装は1バイトずつ読み取る方式（バッファなし）。メモリ上の操作のため、1バイト読みの性能影響は実用上無視できる。

* `__iter__() -> Iterator[str]`, `__next__() -> str`: 行イテレータ。内部で `readline()` を呼び出す。

* `__enter__() -> MFSTextHandle`, `__exit__(...) -> None`: コンテキストマネージャ。`__exit__` はハンドルのクローズを**行わない**。ハンドルのライフサイクル管理は `MemoryFileHandle` 側の `with mfs.open(...)` が担当する。

#### 【使用例】

```python
from dmemfs import MemoryFileSystem, MFSTextHandle

mfs = MemoryFileSystem(max_quota=10 * 1024 * 1024)
with mfs.open("/config.json", "wb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    th.write('{"key": "値"}\n')

with mfs.open("/config.json", "rb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    for line in th:
        print(line, end="")
```

### 5.7 pytest プラグイン [v13 追加]

#### 【目的】

D-MemFS を使用するプロジェクトのテストで、MFS インスタンスのセットアップを簡素化する。

#### 【提供方式】

`dmemfs/_pytest_plugin.py` にフィクスチャを定義する。プラグインは **自動検出されない**。利用するプロジェクトの `conftest.py` で明示的に登録する必要がある：

```python
# conftest.py
pytest_plugins = ["dmemfs._pytest_plugin"]
```

#### 【フィクスチャ】

* `mfs() -> MemoryFileSystem`: テストごとに新規の `MemoryFileSystem` インスタンスを提供する。クォータは `1 MiB`（`1_048_576` バイト）。スコープは `function`（テスト関数ごとに独立）。

#### 【使用例】

```python
def test_write_and_read(mfs):
    with mfs.open("/hello.txt", "wb") as f:
        f.write(b"Hello, World!")
    with mfs.open("/hello.txt", "rb") as f:
        assert f.read() == b"Hello, World!"
```

---

## 第6部：Phase 3 設計 — 中長期機能拡張

v10 では将来ロードマップとして概要のみを記載していた拡張機能群を、v11 で具体的に設計する。これらは全て v10 までの設計と矛盾しない追加設計である。

### 6.1 ファイルタイムスタンプとファイル情報 API

#### 【目的】
ファイルの作成日時・最終更新日時をメタデータとして管理し、`stat()` API で個別ファイルの詳細情報を取得可能にする。ETLパイプラインでの差分処理判定や、アーカイブ生成時のタイムスタンプ付与に有用。

#### 【タイムスタンプの保持場所】
タイムスタンプは `FileNode` に保持する（§2.1 ノードモデル参照）。

```python
class FileNode:
    # ... 既存フィールド ...
    created_at: float     # ファイル作成時に time.time() で初期化
    modified_at: float    # データ変更時に time.time() で更新
```

**`DirNode` にはタイムスタンプを持たせない。** 理由：
- MFS におけるディレクトリは純粋な名前空間コンテナであり、実データを持たない。
- ディレクトリのタイムスタンプ（子の追加・削除による更新）は、POSIX セマンティクスとの整合性を保つために複雑な管理が必要となり、投資対効果が低い。
- 必要が生じた場合は将来バージョンで `DirNode` にも拡張可能。

#### 【タイムスタンプの更新タイミング】

| 操作 | `created_at` | `modified_at` |
|---|---|---|
| ファイル新規作成（`open(wb/xb)` で新規作成） | `time.time()` で初期化 | `created_at` と同値で初期化 |
| `write()` による書き込み | 変更なし | `time.time()` で更新 |
| `truncate()` による縮小 | 変更なし | `time.time()` で更新 |
| `rename()` / `move()` | 変更なし | 変更なし（メタデータ操作のみ） |
| `copy()` | コピー先は新規作成として `time.time()` | コピー先は `created_at` と同値で初期化 |
| `copy_tree()` | 各コピー先ファイルは新規 `time.time()` | 各コピー先は `created_at` と同値で初期化 |
| `import_tree()` | 新規作成として `time.time()` | `created_at` と同値で初期化 |

> **設計判断**: `copy()` でコピー元のタイムスタンプを保持するオプション（`preserve_timestamps=True`）の追加は、将来の拡張として検討するが、v11 時点ではシンプルさを優先し、コピー先は常に新しいタイムスタンプで作成する。

#### 【`stat()` API】

```python
class MFSStatResult(TypedDict):
    size: int           # ファイルサイズ（バイト数）。ディレクトリの場合は 0
    created_at: float   # 作成日時（time.time() の戻り値と同形式）
    modified_at: float  # 最終更新日時
    generation: int     # 変更検知用世代ID
    is_dir: bool        # True: ディレクトリ, False: ファイル [v13: is_sequential から変更]
```

```python
def stat(self, path: str) -> MFSStatResult:
    """
    指定パスのファイル/ディレクトリメタデータを返す。

    Returns:
        MFSStatResult: パスの詳細情報。ディレクトリの場合は size=0, is_dir=True

    Raises:
        FileNotFoundError: パスが存在しない
    """
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
```

#### 【既存API への影響】
- `stats()`: 変更なし。`stats()` はFS全体の集計情報、`stat()` は個別ファイルのメタデータであり、用途が明確に異なる。
- `export_tree()` / `import_tree()`: タイムスタンプは `dict[str, bytes]` 形式に含めない（既存の互換性を維持）。タイムスタンプ付きのエクスポート/インポートが必要な場合は、`stat()` と組み合わせて呼び出し側で管理する。

#### 【メモリオーバーヘッド】
`float` × 2 = 16 バイト / ファイル。1万ファイルでも約 160 KB であり、実データに対して無視可能。

---

### 6.2 メモリ使用量の最適化 (bytearray shrink)

#### 【問題の特定】
`RandomAccessMemoryFile` の内部バッファ `bytearray` は、`truncate()` でファイルサイズが大幅に縮小された場合でも、CPython の `bytearray` 実装は**バッファをそのまま保持する場合がある**（内部的な realloc の挙動は実装依存）。これにより、クォータ上は解放済みだが実際のメモリ消費が削減されない状況が発生し得る。

#### 【shrink 方針】

**戦略: 閾値ベースの再割り当て**

`truncate()` 実行後、新しいサイズが現在のバッファ容量の一定割合以下に縮小した場合、新しい `bytearray` を割り当て直してデータをコピーし、旧バッファを GC に回収させる。

```python
# RandomAccessMemoryFile 内
SHRINK_THRESHOLD = 0.25  # バッファ容量の 25% 以下に縮小した場合に shrink

def truncate(self, size: int, quota_mgr) -> None:
    if size >= len(self._buf):
        return
    old_capacity = len(self._buf)
    release_bytes = len(self._buf) - size
    # サイズ変更
    del self._buf[size:]
    # shrink 判定
    if old_capacity > 0 and size <= old_capacity * self.SHRINK_THRESHOLD:
        # 新しいバッファに再割り当て（GC に旧バッファを回収させる）
        self._buf = bytearray(self._buf)
    quota_mgr.release(release_bytes)
    self.generation += 1
```

#### 【設計判断】

- **閾値 25%**: サイズが元の 1/4 以下になった場合にのみ shrink を実行する。頻繁な shrink によるコピーコストを抑えつつ、大幅な縮小時にはメモリを確実に返却する。
- **`bytearray(self._buf)` による再割り当て**: `bytearray` のコンストラクタに既存の `bytearray` を渡すことで、新しいバッファが最小サイズで生成される。旧バッファは参照カウントがゼロになった時点で GC により回収される。
- **クォータとの整合性**: クォータ上の解放は `truncate()` の `release_bytes` 計算で即時行われるため、shrink の有無はクォータ計算に影響しない。shrink はあくまで**実際のメモリ消費量**と**クォータ計上値**の乖離を緩和するための最適化である。
- **SHRINK_THRESHOLD の調整可能性**: 定数として定義し、将来的にコンストラクタパラメータ化する余地を残す。

#### 【影響範囲】
- `SequentialMemoryFile`: shrink は不要。`truncate()` 時にチャンクリストを再構築する既存の挙動で、不要なチャンクは GC に回収される。
- パフォーマンス: shrink はデータのコピーを伴うが、閾値判定により実行頻度は低く抑えられる。大幅な縮小（元のサイズの 75% 以上の削減）時のみ発生するため、通常の `truncate()` 操作への影響は最小限。

---

### 6.3 PEP 703 (GIL-free Python) 対応設計

#### 【背景】
Python 3.13 で導入された free-threaded build（`python3.13t`）では、GIL が無効化され、複数スレッドが同時にバイトコードを実行する。これにより、GIL に暗黙的に依存していた操作のスレッドセーフティが失われる。

#### 【MFS の GIL 依存度分析】

MFS は設計上 `threading.RLock` + `ReadWriteLock` による明示的なロックを使用しており、**GIL への直接的な依存は限定的**である。ただし、以下の箇所で GIL の暗黙的保護に依存している可能性がある。

| 箇所 | GIL 依存の性質 | v10 での対応状況 | v11 での追加対応 |
|---|---|---|---|
| `_tree` / `_nodes` の `dict` 操作 | CPython の `dict` は GIL 下でスレッドセーフ | `_global_lock` で保護済み | 不要 |
| `export_as_bytesio()` のエントリ参照 | `dict.get()` は GIL 下でアトミック | v10 で `_global_lock` 保護を追加 | **完了** |
| `wb` truncate の読み取りハンドル競合 | `truncate()` 内の複数属性変更は GIL 下で順次実行 | v10 でロック取得後に移動 | **完了** |
| `QuotaManager._used` の更新 | `int` の加算は GIL 下でアトミック | `threading.Lock` で保護済み | 不要 |
| `ReadWriteLock` 内の `Condition` 操作 | `threading.Condition` は GIL 非依存 | 正しく実装済み | 不要 |
| `FileNode` 属性の直接読み取り | `generation`, `_rw_lock` 参照は GIL 下でアトミック | ファイルロック下で保護 | 注意事項を明記 |
| `bytearray` のスライス操作 | GIL 下でアトミックだが、free-threaded では要保護 | ファイルロック下で保護 | 不要 |

#### 【対応方針】

1. **v10 で完了済み（Phase 2）**:
   - `wb` truncate 順序修正（§5.1）
   - `export_as_bytesio()` の `_global_lock` 保護（§4.1）

2. **v11 で追加する対応**:
   - **`FileNode` 属性アクセスの保護確認**: `generation` や `modified_at` の読み取りが、対応するロック（`_rw_lock` または `_global_lock`）の保護下で行われていることを全操作について確認・保証する。
   - **`_nodes` 辞書のイテレーション保護**: `walk()`, `glob()`, `iter_export_tree()` 等でノードツリーをイテレートする際、`_global_lock` 下でキーのスナップショットを取得する設計が既に適用されていることを確認する。

3. **テスト戦略**:
   - Python 3.13t（free-threaded build）を CI マトリクスに追加する。
   - 既存の並行性テスト（`test_concurrency.py`）に加え、`tests/stress/test_threaded_stress.py`（50スレッド×1000回）を free-threaded 環境で実行し、データ競合の有無を検証する。
   - `PYTHON_GIL=0` 環境変数でのテスト実行を追加する。

4. **CI マトリクス拡張**:
```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    python-version: ["3.11", "3.12", "3.13"]
    include:
      - os: ubuntu-latest
        python-version: "3.13t"  # free-threaded build
```

   3.13t ジョブでは `PYTHON_GIL=0` を明示し、通常テストとストレステストを両方実行する：
   ```yaml
   - name: Run tests (free-threaded, GIL=0)
     env:
       PYTHON_GIL: "0"
     run: uv run --python cpython-3.13.7+freethreaded pytest tests/ -v
   ```

   ローカルでの確認コマンド：
   ```bash
   # 通常テスト（3.13t で実行）
   uv run --python cpython-3.13.7+freethreaded pytest tests/ -m "not stress"

   # ストレステスト（3.13t, GIL=0）
   PYTHON_GIL=0 uv run --python cpython-3.13.7+freethreaded pytest tests/stress/ -v
   ```

#### 【設計上の安全マージン】

MFS の既存ロック設計は、GIL を**性能最適化（ロック回避）のために利用していない**。すべてのスレッドセーフティは明示的なロック機構に依存している。そのため、GIL フリー環境への移行は**理論上は追加コード変更なし**で動作するはずである。ただし、CPython の内部実装（`dict`・`list`・`bytearray` のスレッドセーフティ保証）への依存が完全にゼロであることを、free-threaded テスト実行で実証する必要がある。

---

### 6.4 async/await ラッパー層設計

#### 【目的】
asyncio ベースのアプリケーション（FastAPI, aiohttp 等）から MFS を利用する際に、イベントループのブロッキングを回避する薄いラッパー層を提供する。

#### 【設計原則】
1. **コア同期API への変更はゼロ**: `MemoryFileSystem` クラスは完全に同期のまま維持する。
2. **`asyncio.to_thread()` によるオフロード**: ラッパー層は同期メソッドを `asyncio.to_thread()` に委譲するだけの薄い層とする。
3. **別モジュールとして提供**: `memory_file_system/_async.py` に配置し、asyncio を使用しないユーザーに影響を与えない。
4. **ゼロ依存の維持**: `asyncio` は Python 標準ライブラリであるため、依存ゼロの原則を維持できる。

#### 【API 設計】

```python
# memory_file_system/_async.py

import asyncio
from typing import AsyncIterator
from ._fs import MemoryFileSystem
from ._handle import MemoryFileHandle


class AsyncMemoryFileSystem:
    """
    MemoryFileSystem の非同期ラッパー。
    全操作を asyncio.to_thread() 経由で実行し、イベントループをブロックしない。
    """

    def __init__(self, max_quota: int = 256 * 1024 * 1024, **kwargs) -> None:
        self._sync_fs = MemoryFileSystem(max_quota=max_quota, **kwargs)

    async def open(
        self, path: str, mode: str = "rb", **kwargs
    ) -> "AsyncMemoryFileHandle":
        handle = await asyncio.to_thread(
            self._sync_fs.open, path, mode, **kwargs
        )
        return AsyncMemoryFileHandle(handle)

    async def mkdir(self, path: str, exist_ok: bool = False) -> None:
        await asyncio.to_thread(self._sync_fs.mkdir, path, exist_ok=exist_ok)

    async def rename(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync_fs.rename, src, dst)

    async def move(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync_fs.move, src, dst)

    async def remove(self, path: str) -> None:
        await asyncio.to_thread(self._sync_fs.remove, path)

    async def rmtree(self, path: str) -> None:
        await asyncio.to_thread(self._sync_fs.rmtree, path)

    async def copy(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync_fs.copy, src, dst)

    async def copy_tree(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync_fs.copy_tree, src, dst)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync_fs.exists, path)

    async def is_dir(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync_fs.is_dir, path)

    async def listdir(self, path: str) -> list[str]:
        return await asyncio.to_thread(self._sync_fs.listdir, path)

    async def get_size(self, path: str) -> int:
        return await asyncio.to_thread(self._sync_fs.get_size, path)

    async def stat(self, path: str):  # -> MFSStatResult
        return await asyncio.to_thread(self._sync_fs.stat, path)

    async def glob(self, pattern: str) -> list[str]:
        return await asyncio.to_thread(self._sync_fs.glob, pattern)

    async def stats(self) -> dict:
        return await asyncio.to_thread(self._sync_fs.stats)

    async def export_tree(self, **kwargs) -> dict[str, bytes]:
        return await asyncio.to_thread(self._sync_fs.export_tree, **kwargs)

    async def import_tree(self, tree: dict[str, bytes]) -> None:
        await asyncio.to_thread(self._sync_fs.import_tree, tree)

    async def export_as_bytesio(self, path: str, **kwargs):
        return await asyncio.to_thread(
            self._sync_fs.export_as_bytesio, path, **kwargs
        )

    # walk() と iter_export_tree() は AsyncIterator で提供
    async def walk(
        self, path: str = "/"
    ) -> list[tuple[str, list[str], list[str]]]:
        """walk() の結果を一括取得して返す（非同期ジェネレータではなくリスト化）。"""
        return await asyncio.to_thread(
            lambda: list(self._sync_fs.walk(path))
        )


class AsyncMemoryFileHandle:
    """MemoryFileHandle の非同期ラッパー。"""

    def __init__(self, handle: MemoryFileHandle) -> None:
        self._handle = handle

    async def read(self, size: int = -1) -> bytes:
        return await asyncio.to_thread(self._handle.read, size)

    async def write(self, data: bytes) -> int:
        return await asyncio.to_thread(self._handle.write, data)

    async def seek(self, offset: int, whence: int = 0) -> int:
        return await asyncio.to_thread(self._handle.seek, offset, whence)

    async def tell(self) -> int:
        return self._handle.tell()  # 同期で十分（メモリアクセスのみ）

    async def close(self) -> None:
        await asyncio.to_thread(self._handle.close)

    async def __aenter__(self) -> "AsyncMemoryFileHandle":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
```

#### 【設計判断と注意事項】

- **`to_thread()` のオーバーヘッド**: 各呼び出しにスレッドプール経由の切り替えコスト（数十μs）が発生する。MFS のメモリ操作自体は高速（数μs）であるため、ラッパーのオーバーヘッドがドミナントになる場合がある。**パフォーマンスが重要な場合は同期API を直接使用することを推奨する。**
- **`walk()` のリスト化**: 同期版の `walk()` はジェネレータだが、非同期版ではスレッドをまたぐジェネレータの管理が複雑になるため、結果をリスト化して返す。メモリ消費は増加するが、API のシンプルさを優先する。
- **`iter_export_tree()` の非提供**: 同様の理由で、ストリーミングエクスポートは非同期版では提供しない。`export_tree()` で代替する。
- **`tell()` の同期実行**: `tell()` はカーソル位置の読み取りのみであり、ロック取得を伴わないため、`to_thread()` を経由せず同期で実行する。
- **`__init__.py` での公開 [v12 変更]**: `AsyncMemoryFileSystem` と `AsyncMemoryFileHandle` は、`__init__.py` で `__getattr__` によるモジュールレベル遅延インポートを使用して公開する。`TYPE_CHECKING` ガード下では直接インポートを行い、IDE の型推論・`isinstance()` チェック・`help()` を正常に動作させる。これにより、asyncio 未使用環境でのインポートコスト増を回避しつつ、型安全性を両立する。

```python
# __init__.py（v13 設計）
from typing import TYPE_CHECKING

from ._fs import MemoryFileSystem
from ._handle import MemoryFileHandle, MFSTextHandle
from ._exceptions import MFSQuotaExceededError, MFSNodeLimitExceededError
from ._typing import MFSStats, MFSStatResult

if TYPE_CHECKING:
    from ._async import AsyncMemoryFileSystem, AsyncMemoryFileHandle

def __getattr__(name: str):
    if name in ("AsyncMemoryFileSystem", "AsyncMemoryFileHandle"):
        from ._async import AsyncMemoryFileSystem, AsyncMemoryFileHandle
        globals()["AsyncMemoryFileSystem"] = AsyncMemoryFileSystem
        globals()["AsyncMemoryFileHandle"] = AsyncMemoryFileHandle
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "MemoryFileSystem",
    "MemoryFileHandle",
    "MFSTextHandle",
    "MFSQuotaExceededError",
    "MFSNodeLimitExceededError",
    "MFSStats",
    "MFSStatResult",
    "AsyncMemoryFileSystem",
    "AsyncMemoryFileHandle",
]
```

#### 【使用例】

```python
import asyncio
from memory_file_system import AsyncMemoryFileSystem

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

### 6.5 `metadata_tree_lock` の分離（将来検討）

`_global_lock` からメタデータツリーロックを独立させ、ノードツリー操作と高レベルのFS操作のロック粒度を分離する。高並行性環境でのスループット改善が期待できる。

> **現状維持の理由**: 現時点の実用規模（数百〜数千ファイル）では `_global_lock` の競合がボトルネックにならない。ロック分離は設計の複雑化を伴うため、実際にスループット問題が顕在化してから対応する。設計拡張余地は確保済み。

---

## 付録A：v9 からの変更サマリ

| 項目 | v9 | v10 | v11 | v12 | 変更根拠 |
|---|---|---|---|---|---|
| 内部ストレージ構造 | `_tree: dict[str, IMemoryFile]` | `DirNode/FileNode` + `_nodes: dict[int, Node]` | 同左 | 同左 | listdir $O(N)$ → $O(\text{children})$ 改善 |
| ロック階層 | 2層（global → rw） | 3層（global → quota → rw） | 同左 | 同左 | ディレクトリインデックス層との親和性 |
| `wb` truncate 順序 | ロック取得**前** | ロック取得**後** | 同左 | 同左 | PEP 703 対応 |
| `walk()` 整合性 | 暗黙的 | 弱整合性を**明記** | 同左 | 同左 | ドキュメント品質向上 |
| `glob()` パターン | `fnmatch.fnmatch` | `*` は `/` 以外、`**` で再帰マッチ | 同左 | 同左 | 標準glob挙動との整合 |
| `export_as_bytesio()` | `_global_lock` なし | `_global_lock` で保護 | 同左 | 同左 | GILフリー対応 |
| `__del__` stacklevel | `stacklevel=2` | `stacklevel=1` | 同左 | 同左 | GCから呼ばれるため |
| `stats()` chunk_count | 暗黙的 | SequentialMemoryFile のみと**明記** | 同左 | 同左 | ドキュメント品質向上 |
| 新規API (v10) | — | `copy_tree()`, `move()`, `glob("**")` | 同左 | 同左 | ツリー操作の充実 |
| `is_dir`等の所在 | `IMemoryFile` 内 | `DirNode`/`FileNode` に分離 | 同左 | 同左 | 関心の分離 |
| **タイムスタンプ** | なし | ロードマップのみ | **`FileNode` に `created_at`/`modified_at` を追加、`stat()` API** | 同左 | 差分処理判定、アーカイブ対応 |
| **bytearray shrink** | なし | ロードマップのみ | **`RandomAccessMemoryFile.truncate()` に shrink 機構** | 同左 | メモリ効率の改善 |
| **PEP 703 対応** | なし | ロードマップのみ | **対応設計の詳細化、CI マトリクス拡張** | 同左 | free-threaded Python への備え |
| **async/await** | なし | ロードマップのみ | **`AsyncMemoryFileSystem` / `AsyncMemoryFileHandle` ラッパー** | 同左 | asyncio アプリとの統合 |
| **将来ロードマップ** | なし | 第6部（概要のみ） | 第6部（詳細設計に昇格） | 同左 | ロードマップから正式設計へ |
| **`_global_lock` 保護範囲** | — | — | 一部注記 | **`get_size()`, `listdir()` にも適用、`walk()`/`glob()` のスナップショット取得も保護** | GILフリー安全性 |
| **`_NoOpQuotaManager`** | — | — | — | **削除** | 未使用コード除去 |
| **`AsyncMemoryFileSystem` 公開** | なし | なし | 関数ラッパー | **`__getattr__` 遅延インポート + `TYPE_CHECKING` ガード** | `isinstance()` / IDE対応 |
| **`copy()` API仕様** | — | — | — | **引数仕様・例外仕様を明記** | ドキュメント品質 |
| **`_force_reserve()` 制約** | — | — | — | **使用条件を明記** | 安全性・保守性 |
