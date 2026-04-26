---
name: c-harness-audit
description: 決定論的ハーネス監査実行→優先度付きスコアカード返却。
command: /c-harness-audit
---

# ハーネス監査・スコアカード

## 永続メモリ

search: `harness audit score` / stats: `{project_name}` (days: 90)
record: 必要時のみ、最終スコアを1回だけ記録
参照: スコア推移 / 修復履歴 / 改善傾向。出力にスコア推移と修復履歴を追記する。

## 使い方

```bash
/c-harness-audit
/c-harness-audit skills --format json
/c-harness-audit --scope hooks --root /path/to/repo
```

`scope` は位置引数でも `--scope` でも指定可。既定値は `repo`。`hooks`・`skills`・`commands`・`agents` も選択可。
`--format` は `text`（既定）または `json`。`--root` は監査対象ルートを上書き。

## 実行エンジン

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.ci.harness_audit <scope> --format <text|json> [--root <path>]
```

スコアリングとチェックの唯一の根拠。追加評価軸や即席採点は行わない。

ルーブリック版: `2026-03-30`

固定カテゴリ7個（各0〜10に正規化）:
1. ツール網羅性
2. 文脈効率
3. 品質ゲート
4. メモリ永続性
5. 評価網羅性
6. セキュリティガードレール
7. コスト効率

スコアは明示的なファイル/ルールチェックから導出・同コミットで再現可能。

## 出力仕様

1. `overall_score` と `max_score`（`repo` では70）
2. カテゴリ別スコアと指摘
3. 失敗したチェックと正確なファイルパス
4. 上位3件のアクション（`top_actions`）
5. 次に適用すべきECCスキルの提案

## チェックルール

- スクリプト出力をそのまま使い、手動で再採点しない
- `--format json` の場合はJSONを変更せずそのまま返す
- `text` の場合は失敗したチェックと上位アクションを要約
- `checks[]` と `top_actions[]` に含まれる正確なファイルパスを残す

## 出力例

```text
Harness Audit (repo, repo): 66/70
- Tool Coverage: 10/10 (10/10 pts)
- Context Efficiency: 9/10 (9/10 pts)
- Quality Gates: 10/10 (10/10 pts)

Top 3 Actions:
1) [Security Guardrails] Add prompt/tool preflight security guards in hooks/hooks.json. (hooks/hooks.json)
2) [Tool Coverage] Sync commands/c-harness-audit.md and .opencode/commands/c-harness-audit.md. (.opencode/commands/c-harness-audit.md)
3) [Eval Coverage] Increase automated test coverage across scripts/hooks/lib. (tests/)
```

## 引数

- `repo|hooks|skills|commands|agents`（位置引数）
- `--scope repo|hooks|skills|commands|agents`
- `--format text|json`
- `--root <path>`
