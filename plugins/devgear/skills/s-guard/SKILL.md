---
name: s-guard
description: 本番環境作業・エージェント自律実行時に破壊的操作を防ぐ。
context: fork
---

# Safety Guard — 破壊的操作防止

## 発動タイミング

- 本番環境作業
- エージェント自律実行（フルオートモード）
- 編集を特定ディレクトリに制限したい
- 機密性高い操作（マイグレーション/デプロイ/データ変更）

## 仕組み

破壊的コマンドを実行前に検知して警告。

監視パターン:

- rm -rf (especially /, ~, or project root)
- git push --force
- git reset --hard
- git checkout .
- DROP TABLE / DROP DATABASE
- docker system prune
- kubectl delete
- chmod 777
- sudo rm
- npm publish
- Any command with --no-verify

検知時→コマンド内容を示し、確認を求め、より安全な代替案を提案。

## 実装

PreToolUse フックでBash/Write/Edit/MultiEditのツール呼び出しを検知。コマンド・パスを有効ルールと照合後、実行許可。

## 永続メモリ

search: `guard block prevent dangerous` / `{command_pattern} block risk` / `guard false positive override`
record: `{"event_type": "guard-block", "content": "Blocked: {command}. Reason: {reason}. Alternative: {alternative}"}`
参照: ブロック操作ログ / リスクパターン / 誤検知追跡
