# 公開前 残件チェックリスト

MFS を GitHub / PyPI に公開するまでに解決が必要な残件の一覧です。  
コード修正が済んだ項目は含みません。

---

## P0 — 公開ブロッカー（必須）

| # | 項目 | 詳細 |
|---|------|------|
| 1 | **GitHubリポジトリの作成** | `D-MemFS`（またはお好みのリポジトリ名）でパブリックリポジトリを作成し、初回 push を行う |
| 2 | **`pyproject.toml` の URL 更新** | `[project.urls]` の `Homepage` / `Repository` を実際のリポジトリURLに変更する（例: `https://github.com/<username>/D-MemFS`） |
| 3 | **`LICENSE` の著作者名記入** | `Copyright (c) 2026` の後に著作者名（個人名 or 組織名）を追記する |
| 4 | **PyPI パッケージ名の空き確認** | `pip index versions D-MemFS` または [https://pypi.org/project/D-MemFS/](https://pypi.org/project/D-MemFS/) でパッケージ名の利用可否を確認する |
| 5 | **`README.md` / `README_ja.md` のバッジ URL 更新** | CI バッジ・PyPI バッジ等のURLをリポジトリ確定後に更新する |

---

## P1 — 公開後 早期に対処推奨

| # | 項目 | 詳細 |
|---|------|------|
| ~~6~~ | ~~**`walk()` / `glob()` / `copy()` の拡充**~~ | ✅ v0.2.0 で実装済み: `glob("**")` 再帰パターン、`copy_tree()`、`move()`、`stat()` |
| 7 | **SQLite serialize/deserialize テストのカバレッジ拡充** | 現在 3テスト。エラーケース（破損データなど）や大規模DBのテスト追加を検討 |
| 8 | **PyPI への公開** | `uv build` + `uv publish` または `twine upload` でパッケージを公開する |

---

## P2 — 余裕があれば対処

| # | 項目 | 詳細 |
|---|------|------|
| 9 | **紹介記事の執筆（国内: Qiita / Zenn）** | 「なぜ tmpfs ではダメなのか」「ハードクォータの設計思想」等をテーマにした記事 |
| 10 | **紹介記事の執筆（海外: Reddit / HN）** | Show HN または r/Python 向けの英語記事 |
| ~~11~~ | ~~**`glob(pattern)` の `**` 対応**~~ | ✅ v0.2.0 で実装済み |
| ~~12~~ | ~~**`listdir()` O(N) の改善**~~ | ✅ v0.2.0 で DirNode.children 導入により O(children_count) に改善済み |

---

## 完了済み（参考）

- [x] `remove()` / `rmtree()` クォータリーク修正（チャンクオーバーヘッド未返却）
- [x] `remove()` / `rmtree()` クォータ解放をグローバルロック内に移動
- [x] `.gitignore` 作成
- [x] `LICENSE` 著作者名の年を 2026 に修正
- [x] `CHANGELOG.md` 作成
- [x] `CONTRIBUTING.md` 作成
- [x] `py.typed` (PEP 561) マーカーファイル追加
- [x] CI ワークフロー: `pip` → `uv`、3 OS × 3 Python マトリクスに更新
- [x] バージョン `1.0.0` → `0.1.0`、classifier `4 - Beta` に変更
- [x] `_PromotionSignal` 廃止 → `write_at()` タプル戻り値方式に変更（Pythonアンチパターン解消）
- [x] `SequentialMemoryFile.read_at()` O(N) → O(log N) 改善（`_cumulative` + `bisect`）
- [x] 新API追加: `copy()`, `get_size()`, `walk()`, `glob()`
- [x] `test_multiple_readers_allowed` をスレッドベース（3スレッド + Barrier）に修正
- [x] SQLiteテストを実際の `sqlite3.serialize()`/`deserialize()` を使った実装に書き換え
- [x] 178/178 テスト全 PASS
