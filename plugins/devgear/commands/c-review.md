---
name: c-review
description: 未コミット変更に対するセキュリティ/品質レビュー実施。
command: /c-review
---

# コードレビュー

## 永続メモリ

search: `review violation security` / `{変更ファイル名}` (file_pattern指定)
record: 必要時のみ、最終レビュー結果を1回だけ記録
参照: プロジェクト固有ルール / 頻出違反パターン。繰り返し違反は警告レベルを1段階上げ「繰り返し違反」とマーク。

## READ-ONLY 制約（絶対厳守）

このコマンドは**絶対にファイルを変更しない**。

- Edit / Write / MultiEdit ツールの使用を禁止する
- `git apply`, `sed -i`, `awk -i` 等のファイル書き換え Bash コマンドを禁止する
- 起動する a-review / a-secure も同様の制約に従う（tools リストに Write/Edit は含まれていないが明示的に禁止）
- 修正提案は「推奨修正」として**テキストで出力する**のみ。コード変更は禁止。

## スコープ制約

- `git diff --name-only HEAD` で取得したファイルのみ対象
- 引数で明示指定された場合のみ範囲変更可
- 隣接ファイルへの自律的な拡散を禁止する

## 変更ファイル取得: `git diff --name-only HEAD`

## レビュー実行（並列）

以下の2エージェントを**同時起動**し、両結果が揃ってからレポートを統合する:

**エージェントA: `devgear:a-review`**
品質・設計・保守性・BPレビュー。50行超fn/800行超ファイル/4階層超ネスト/エラーハンドリング不足/テスト不足/console.log/TODO-FIXME/a11y問題を確認。

**エージェントB: `devgear:a-secure`**
セキュリティ・脆弱性レビュー。ハードコード認証情報/SQLi/XSS/入力検証不足/パストラバーサルを確認。

## レポート内容

- 深刻度: CRITICAL, HIGH, MEDIUM, LOW
- ファイル位置と行番号
- 問題の説明
- 推奨修正
- **過去の類似違反**（memから取得した場合）

## CRITICAL または HIGH → commitをブロック

セキュリティ脆弱性あるコードは絶対承認しない!
