---
name: s-comply
description: skills/rules/agent 定義の遵守率可視化。3段階プロンプト厳密度でシナリオ自動生成→agent実行→行動列分類→ツール呼び出しタイムライン付き遵守率報告。
---

# s-comply: 自動コンプライアンス測定

skills・rules・agent 定義が実際に守られているかを次の方法で測定:
1. 任意の `.md` ファイルから期待される行動シーケンス（spec）を自動生成
2. プロンプト厳密さを段階的に下げながらシナリオ自動生成（supportive → neutral → competing）
3. `claude -p` を実行し、stream-json経由でtool call traceを取得
4. LLMを使ってtool callをspecのステップと照合（正規表現は使わない）
5. 時系列の順序を決定論的に検証
6. spec・プロンプト・タイムライン含む自己完結型レポートを生成

## 対応対象

- **Skills** (`skills/*/SKILL.md`): s-search・s-tddなどのワークフローskill
- **Rules** (`rules/common/*.md`): `testing.md`・`security.md`・`git-workflow.md`などの必須ルール
- **Agent definitions** (`agents/*.md`): 期待通りにagentが呼び出されるか（内部ワークフロー検証は未対応）

## 発動タイミング

- ユーザーが `/c-comply <path>` を実行したとき
- 「このルールは本当に守られているか？」と尋ねたとき
- 新しいrule/skill追加後にagentの遵守状況を検証するとき
- 定期的な品質メンテナンスの一環として

## 使い方

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.skills.comply.cli ~/.claude/rules/common/testing.md
devgear_run devgear.skills.comply.cli --dry-run ~/.claude/skills/s-search/SKILL.md
devgear_run devgear.skills.comply.cli --gen-model haiku --model sonnet <path>
```

## プロンプト非依存性

skill/ruleが、プロンプトがそれを明示的に支援していなくても守られているかを測定。

## レポート内容

自己完結型。含まれる内容:
1. 期待される行動シーケンス（自動生成されたspec）
2. シナリオのプロンプト（各厳密度レベルで何が求められたか）
3. シナリオごとの遵守スコア
4. LLMによる分類ラベル付きのツール呼び出しタイムライン

### 高度な機能（任意）

hooksに慣れているユーザー向けに、遵守率低いステップへのhook昇格推奨もレポートに含まれる。情報提供であり、主な価値は遵守状況の可視化そのもの。

## 永続メモリ

search: `comply compliance rate spec` / `{skill_name} compliance adherence` / `low compliance skip miss`
record: `{"event_type": "compliance", "content": "Compliance for {skill_name}: {rate}%. Steps: {passed}/{total}"}`
参照: コンプライアンス傾向 / 守られにくいステップ / hook昇格履歴
