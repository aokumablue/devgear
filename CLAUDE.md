# CLAUDE.md

## コードベース分析

必ずサブエージェントに依頼する

## コーディングルール

- `Python` コードに `docstring` を付ける
- 後方互換フォールバックは実装しない（古いコードは必ず削除）
- カバレッジ `100%`
- テーブル定義変更は `CREATE TABLE` を直接修正（リリース前のためマイグレーション不要）

## 作業ルール

- Python は `python3` を使う
- 変更後は `.venv` を有効化して `python3 -m pytest -q` と `ruff check plugins/devgear/src tests` が成功することを確認（警告なし）

## 永続メモリ

- `SessionStart`: `devgear.mem.cli context` が `<mem-context>` を注入
- `PreToolUse` / `PostToolUse`: ツール操作を記録
- `SessionEnd`: 埋め込み生成と s-learn ブリッジ
- DB: `~/.devgear/mem.db`
- 実装起点: `plugins/devgear/src/devgear/mem/{cli,search,context,bridge}.py`
