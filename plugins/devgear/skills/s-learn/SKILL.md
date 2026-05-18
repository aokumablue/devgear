---
name: s-learn
description: セッション観測→信頼度付き原子的インスティンクト作成→skills/commands/agentsに進化させる学習システム。プロジェクト単位インスティンクトでプロジェクト間混入防止。
context: fork
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

## コマンド

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

## 永続メモリ

search: `{instinct_id} confidence` / `instinct conflict {domain}` / `instinct global promote success`
record: `{"event_type": "instinct-update", "content": "Updated {instinct_id}: confidence {old} -> {new}"}`
参照: 進化履歴 / 矛盾検出 / クロスプロジェクト分析 / 昇格判断

