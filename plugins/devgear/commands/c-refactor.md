---
name: c-refactor
description: 変更差分を対象に性能劣化防止と明確欠陥改善、デッドコード排除、可読性改善、レビューまで一気通貫で実行。
command: /c-refactor
---

# 統合リファクタリング

## 永続メモリ

search: `refactor clean simplify perf review {対象ファイルパス}` / `critical high blocker`
record: `{"event_type": "refactor", "content": "Scope: {scope}. Clean: {cleaned}. Simplify: {simplified}. Perf: {perf_fixed}. Blockers: {blockers}"}`
参照: 過去リファクタ履歴 / ファイル単位リバート履歴 / 頻出CRITICAL・HIGH指摘。

## ステップ1: preflight（既定スコープ + 実行準備）

既定スコープは**変更差分のみ**:

```bash
git diff --name-only HEAD
```

引数でファイル/ディレクトリ指定があれば、そちらを対象にする。

着手前に以下を実行して準備を固定:

- `s-refprep`（必須）: 対象分割、依存可視化、実行前テストセット確定
- `s-refrb`（必須）: ファイル単位リバート計画（Rollback Blueprint）を生成
- `a-reforch`（必須）: clean/simplify/perf/review の実行順・並列制御を担当

`deps.from` / `deps.to` は `groups` 配列のインデックスを指す。

`s-refrb` の運用規約:

- `risk_files` に含まれる `CAUTION` は自動適用せず、要確認として最終要約に記録する
- `Skip Rules` は `{file, reason, required_action}` で出力し、該当ファイルは処理対象から除外する
- `deps_order` は `groups` の依存関係をトポロジカル順で解決し、復旧時は逆順で適用する

## ステップ2: baseline

1. プロジェクト標準のテスト・linterを実行し基準を取得
2. 既存失敗を記録し、新規失敗判定に使用
3. 基準取得不能なら実装を止め、原因解消後に再開

## ステップ3: clean（`a-reforch` から `devgear:a-clean` / `a-clean` へ委譲）

`devgear:a-clean` に対象を委譲してデッドコードを削除。

各ファイル適用ごとに:

1. 変更反映
2. テスト実行
3. 失敗時は `git checkout -- <file>` で**そのファイルだけ**リバートして継続

## ステップ4: simplify（並列, `a-reforch` から `devgear:a-simplify` / `a-simplify` へ委譲）

対象ファイルをグループ化し、`devgear:a-simplify` を**同時起動**する。

- 機能保持を前提に可読性・一貫性・保守性を改善
- グループ完了ごとにテスト実行
- 失敗ファイルは `git checkout -- <file>` でファイル単位リバート

## ステップ5: perf（`a-reforch` から `devgear:a-perf` / `a-perf` へ委譲）

step4 の simplify 全グループ完了後に開始する。

`devgear:a-perf` に委譲して、性能劣化防止と明確欠陥改善を実施。

- 不要計算・重複I/O・N+1・過剰メモリアロケーションを優先改善
- 変更ごとに関連テスト（必要ならベンチ）を実行
- 失敗ファイルは `git checkout -- <file>` でファイル単位リバート

## ステップ6: review + secure（並列, `a-reforch` から委譲）

以下を**同時起動**し、結果を統合:

- `devgear:a-review` / `a-review`: 品質・設計・保守性レビュー
- `devgear:a-secure` / `a-secure`: セキュリティ・脆弱性レビュー

## ステップ7: final gate

1. テストとlinterを再実行
2. レビュー結果に **CRITICAL または HIGH** が1件でもあればブロック
3. 失敗した変更はファイル単位でリバートし、再検証
4. すべて通過した場合のみ完了

## ステップ8: 要約

```
Unified Refactor
──────────────────────────────
Scope:      {n} files
Cleaned:    {cleaned} files
Simplified: {simplified} files
Perf fixed: {perf_fixed} files
Reverted:   {reverted} files
Issues:     CRITICAL {c} / HIGH {h} / MEDIUM {m} / LOW {l}
──────────────────────────────
Final Gate: PASS / BLOCKED
```

※ Issues は `a-review` と `a-secure` の結果を統合した件数を使用する。

## ルール

- **既定スコープは変更差分のみ**
- **失敗時は必ずファイル単位リバート**
- **CRITICAL/HIGH が残る状態では承認・コミットしない**
- **機能変更禁止（WHAT不変）**。挙動変更の疑義がある変更は適用せず、要確認として報告する
- **安全性に疑義がある変更はスキップ**し、最終要約に要確認として記載する
- **サブエージェント委譲を必須化**（`a-reforch` を統括とし、`a-clean`, `a-simplify`, `a-perf`, `a-review`, `a-secure` を実行）

## 引数

$ARGUMENTS: `[ファイルパス or ディレクトリ]`
