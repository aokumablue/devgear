---
name: s-skillmaster
description: 新スキル生成/既存スキル改善/eval実行/ベンチマーク分析/説明文最適化。/c-skill-createからの委譲先。
---

# スキル生成・改善

スキルを生成しテストして改善するためのスキル。`/c-skill-create` は入力収集フロントエンド、ここが生成本体。

## 全体の流れ

1. 何をしたいスキルかを決める
2. SKILL.md 下書きを書く
3. テストプロンプトを2〜3個作る
4. `claude -p` で実行してみる
5. 定性的・定量的に結果を確認
6. フィードバックをもとに書き直す
7. 十分になるまで繰り返す
8. テスト数を増やしてスケール確認

## スキル生成

### ヒアリング内容

1. このスキルでClaudeに何をさせたいか
2. いつトリガーされるべきか
3. 期待する出力形式
4. テストケースが必要か

### SKILL.md 基本構造

```text
skill-name/
├── SKILL.md (必須)
│   ├── YAML frontmatter (name, description)
│   └── Markdown の指示文
└── Bundled Resources (任意)
    ├── src/devgear/skills/ — 決定的・反復的な処理用のPythonモジュール
    ├── references/ — 必要に応じて読む文書
    └── assets/ — テンプレートや画像
```

### 書き方のポイント

- **name**: スキル識別子
- **description**: いつトリガーされるか・何をするか。Claudeはスキルを使い渋る傾向があるので説明はやや強めに書く
- SKILL.md は500行未満に保つ
- 長くなるなら階層を増やして参照ファイルに分ける
- 命令形を基本にし、なぜその指示が大事かを説明する

### テストケース（evals/evals.json）

```json
{
  "skill_name": "example-skill",
  "evals": [{"id": 1, "prompt": "...", "expected_output": "...", "files": []}]
}
```

完全スキーマは `references/schemas.md` 参照。

## テスト実行と評価

**詳細は `references/eval-workflow.md` 参照。** 概要:

1. 各テストケースでスキルあり/ベースラインの2サブエージェントを同時起動
2. 実行中に定量的アサーションを下書き
3. `timing.json` に即座に保存
4. grading → ベンチマーク集約 → 分析 → viewerで表示

## スキル改善

**詳細は `references/improvement-guide.md` 参照。** 改善のポイント:

- フィードバックを一般化する（その例だけに最適化しない）
- プロンプトを軽く保つ（効いていない説明は削る）
- なぜを説明する（ALWAYS/NEVERの連発は黄色信号）
- テストケース間の重複を探す

反復ループ: 変更反映 → 再実行 → レビュー → フィードバック → 改善

## 参照ファイル

- `references/eval-workflow.md` — eval実行・採点・viewerの詳細手順
- `references/improvement-guide.md` — 改善ループ・盲検比較・説明文最適化
- `references/schemas.md` — JSON構造定義
- `../../agents/a-grader.md` / `../../agents/a-comparator.md` / `../../agents/a-analyzer.md`

## 永続メモリ

search: `skill eval benchmark {skill_category}` / `skill improve iteration {skill_name}`
record: `{"event_type": "skill-eval", "content": "Evaluated {skill_name}: pass_rate {rate}%, iterations {n}"}`
