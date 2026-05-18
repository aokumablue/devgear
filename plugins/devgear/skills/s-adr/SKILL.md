---
name: s-adr
description: セッション中アーキテクチャ決定→構造化ADR記録。決定瞬間を自動検出、コンテキスト/代替案/根拠を記録。ADRログでコードベース形成理由を共有。
context: fork
---

# アーキテクチャ決定記録

セッション中アーキテクチャ決定を構造化ADRとして記録。

## 発動タイミング

- 「ADRにして」「この決定を記録」
- 重要な代替案間で選択（フレームワーク/ライブラリ/パターン/DB/API設計）
- 「Xすることに決めた」「YではなくXの理由は」
- 計画フェーズでアーキテクチャトレードオフが議論される

## ADR フォーマット

```md
# ADR-NNNN: [決定タイトル]

**日付**: YYYY-MM-DD  **ステータス**: proposed | accepted | deprecated | superseded by ADR-NNNN

## コンテキスト
[状況・制約・関与する力を 2-5 文で説明]

## 決定
[決定を明確に述べる 1-3 文]

## 検討した代替案
### 代替案 1: [名前]
- 長所 / 短所 / 却下理由

## 結果
### 肯定的 / 否定的 / リスク
```

## ワークフロー

1. **初回のみ**: `docs/adr/` ディレクトリ・インデックス(`README.md`)・テンプレート作成（ユーザー確認後）
2. 決定特定→コンテキスト収集→代替案記録→結果記述
3. 既存ADRスキャンして番号割り当て
4. ドラフトをユーザーへレビュー提示 → **明示的承認後のみ**ファイル書き込み
5. `docs/adr/README.md` インデックス更新

## ディレクトリ構造

```
docs/adr/
├── README.md        ← インデックス（| ADR | Title | Status | Date |）
├── 0001-*.md
└── template.md
```

## 決定検出シグナル

**明示的**: "Xを採用しよう" / "YではなくXを使うべき" / "これをADRとして記録"

**暗黙的**（記録提案・自動作成しない）: 2つのフレームワーク比較して結論 / DBスキーマ設計選択 / アーキテクチャパターン間での選択

## ADRライフサイクル

`proposed → accepted → [deprecated | superseded by ADR-NNNN]`

## 永続メモリ

search: `ADR architecture decision {topic}` / `{technology} vs alternative decision`
record: `{"event_type": "adr-create", "content": "Created ADR-{num}: {title}. Decision: {summary}"}`
参照: ADR検索 / 決定影響追跡 / 過去の決定パターン
