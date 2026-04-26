---
name: s-simplify
description: 変更済みコードを複数のa-simplifyサブエージェントで並列単純化。機能保持しつつ明確性・一貫性・保守性向上。
command: /c-simplify
---

# 並列コード単純化

## 永続メモリ

search: `simplify refactor clean {対象ファイルパス}`
record: `{"event_type": "simplify", "content": "Simplified: {files}. Issues resolved: {count}"}`

## ステップ1: 変更ファイル取得

```bash
git diff --name-only HEAD
```

引数でファイル/ディレクトリ指定があれば、そちらを対象にする。

## ステップ2: ファイルをグループ分け

変更ファイルを最大4グループに分割（ファイル数が少ない場合は1グループ/ファイル）。

グループ分けの基準:
- 同一モジュール・ディレクトリは同じグループにまとめる
- テストファイルと実装ファイルは同じグループにする
- 1グループ最大5ファイル

## ステップ3: サブエージェント並列起動

各グループに対して `devgear:a-simplify` エージェントをサブエージェントとして**同時起動**する。

各サブエージェントへの指示テンプレート:
```
以下のファイルを単純化してください。機能を完全に保持し、明確性・一貫性・保守性を向上させてください。

対象ファイル:
- {file1}
- {file2}
...

a-simplifyエージェントの制約に従い、HOWのみ変更してください。
```

## ステップ4: 結果確認

すべてのサブエージェント完了後:

1. プロジェクトのテストコマンドでテスト実行（例: pytest, jest, go test, cargo test など）
2. テスト失敗 → 失敗ファイルを `git checkout -- <file>` で戻す
3. プロジェクトのlinterを実行（例: ruff, eslint, golangci-lint など）

## ステップ5: 要約

```
Parallel Simplification
──────────────────────────────
Groups:    {n} parallel agents
Files:     {total} files processed
Changed:   {changed} files simplified
Reverted:  {reverted} files (test failures)
──────────────────────────────
Tests: PASS / FAIL
```

## ルール

- **機能変更禁止** — リファクタのみ
- **テスト失敗ファイルは即リバート**
- **グループ間依存は順次実行** — 共有型・インターフェース変更が先
