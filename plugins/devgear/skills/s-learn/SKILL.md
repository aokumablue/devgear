---
name: s-learn
description: セッション観測→信頼度付き原子的インスティンクト作成→skills/commands/agentsに進化させる学習システム。プロジェクト単位インスティンクトでプロジェクト間混入防止。
---

# 継続学習 - インスティンクトベース構成

セッション→再利用可能な知識へ変換。プロジェクト単位でインスティンクト分離、汎用パターンのみグローバル共有。

## 発動タイミング

自動学習設定・フック経由インスティンクト抽出設定・信頼度しきい値調整・インスティンクトのレビュー/エクスポート/インポート・skills/commands/agentsへの進化・スコープ切り替え・昇格

## 機能概要

- 保存先: `projects/<hash>/`
- スコープ: project + global
- 検出方法: git remote URL / repo path
- 昇格条件: 2プロジェクト以上で出現 → global
- プロジェクト間混入: 既定で分離

## インスティンクトモデル

```yaml
---
id: prefer-functional-style
trigger: "when writing new functions"
confidence: 0.7
domain: "code-style"
scope: project
project_id: "a1b2c3d4e5f6"
---
# アクション / 根拠
```

**特性:** 原子的（1トリガー→1アクション）・信頼度付き（0.3-0.9）・ドメインタグ付き・証拠付き

## 仕組み

```
セッション活動 → フック（100%信頼性）でキャプチャ
  → projects/<hash>/observations.jsonl
  → バックグラウンドエージェント（Haiku）でパターン検出
  → project/global スコープに分けてインスティンクト作成/更新
  → /c-instinct evolve でクラスタ化 → skills/commands/agents
```

## クイックスタート

### 1. 観測フックを有効化

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/src/devgear/launcher.py\" devgear.skills.learn.observe pre"}]}],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/src/devgear/launcher.py\" devgear.skills.learn.observe post"}]}]
  }
}
```

### 2. コマンド

- `/c-instinct evolve` — skills/commands/agentsにクラスタ化
- `/c-instinct export` — エクスポート
- `/c-instinct import <file>` — インポート
- `/c-instinct promote [id]` — project → global 昇格
- `/c-dashboard` — 既知プロジェクト・スキル健全性・成長候補の可視化

## スコープ判定

- 言語/フレームワーク規約 → project
- ファイル構成の好み → project
- コードスタイル → project
- セキュリティ実践 → global
- 一般的ベストプラクティス → global
- ツール操作の好み → global
- Gitの運用 → global

## 信頼度スコア

- 0.3: 試行段階（提案のみ）
- 0.5: 中程度（関連時に適用）
- 0.7: 強い（自動承認）
- 0.9: ほぼ確実（中核の振る舞い）

## ファイル構成

```
~/.devgear/
├── identity.json
├── projects.json
├── instincts/{personal,inherited}/
├── evolved/{agents,skills,commands}/
└── projects/<hash>/
    ├── observations.jsonl
    ├── instincts/{personal,inherited}/
    └── evolved/{skills,commands,agents}/
```

## プライバシー

観測データはローカルのみ。エクスポートできるのはインスティンクト（パターン）のみ・元の観測データは非公開。

## 永続メモリ

search: `{instinct_id} confidence` / `instinct conflict {domain}` / `instinct global promote success`
record: `{"event_type": "instinct-update", "content": "Updated {instinct_id}: confidence {old} -> {new}"}`
参照: 進化履歴 / 矛盾検出 / クロスプロジェクト分析 / 昇格判断

## 手動評価モード（Manual Eval）

セッション終了後にパターン抽出を手動で精査する場合に使用する。自動学習（フックベース）を補完する手動検証フロー。

### 抽出対象（4カテゴリ）

1. **Error Resolution Patterns** — 根本原因 + 修正 + 再利用性
2. **Debugging Techniques** — 目立たない手順・ツール組み合わせ
3. **Workarounds** — ライブラリの癖・API制限・バージョン固有修正
4. **Project-Specific Patterns** — 規約・アーキテクチャ判断・統合パターン

### 手順（7ステップ）

**Step 1:** 抽出可能なパターンを確認する

**Step 2:** 最も価値ある知見を特定する

**Step 3:** 保存先決定ロジック
- **Global** (`~/.claude/skills/learned/`) — 2プロジェクト以上で使える汎用パターン
- **Project** (`.claude/skills/learned/`) — プロジェクト固有知識・コンテキスト依存
- 迷ったら **Global**（Global → Project への移動は逆より簡単）

**Step 4:** skillファイル下書きフォーマット
```markdown
---
name: pattern-name
description: "Under 130 characters"
user-invocable: false
origin: auto-extracted
---

## Problem
[問題の説明]

## Solution
[解決策]

## When to Use
[使用場面]
```

**Step 5:** 品質ゲート（必須チェックリスト）
- `~/.claude/skills/` と project の `.claude/skills/` をgrepして重複確認
- MEMORY.md（projectとglobal両方）で重複確認
- 既存skillへの追記で足りるか検討
- 一回限りの修正ではなく再利用可能なパターンか確認

**Step 6:** 総合判定（4択）
- **Save** — 独自性あり・具体的・範囲適切 → Step 7へ
- **Improve then Save** — 価値はあるが改善必要 → 改善点列挙→修正→再評価（1回）
- **Absorb into [X]** — 既存skillに追記すべき → 対象skillと追加内容を示す
- **Drop** — 自明・重複・抽象的すぎ → 理由説明して終了

各判定の出力フォーマット（テンプレート）：
```markdown
### チェックリスト
- [ ] skills/ grep: 重複なし
- [ ] MEMORY.md: 重複なし
- [ ] Existing skill append: 新規ファイルが適切
- [ ] Reusability: 確認済み

### Verdict: Save / Improve then Save / Absorb into [X] / Drop
**Rationale:** （1〜2文）
**Diff（Absorbの場合）:** 対象skillへの追記内容
**下書き（Saveの場合）:** 新規skillファイルの完全下書き
```

**Step 7:** 決定した保存先へ保存/追記

### 注意事項

- タイプミス・単純な構文エラーは抽出しない（セッション中に修正可能）
- 一回限りの問題は抽出しない（今後のセッションで再利用できるパターンのみ）
- skillは1パターンに集中（複数パターンの場合は複数skillを分割）
- Absorb 判定時は既存 skill に追記する（新規作成しない）
- 関連する既存 skill が存在しない場合のみ新規作成する
