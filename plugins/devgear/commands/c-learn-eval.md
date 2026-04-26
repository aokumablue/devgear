---
name: c-learn-eval
description: セッションから再利用可能パターン抽出→品質評価→保存先（Global/Project）決定。
command: /c-learn-eval
---

# 抽出→評価→保存

## 抽出対象

1. **Error Resolution Patterns** — 根本原因 + 修正 + 再利用性
2. **Debugging Techniques** — 目立たない手順・ツール組み合わせ
3. **Workarounds** — ライブラリの癖・API制限・バージョン固有修正
4. **Project-Specific Patterns** — 規約・アーキテクチャ判断・統合パターン

## 手順

1. セッションから抽出可能なパターン確認
2. 最も価値高く再利用できる知見特定

3. **保存先決定:**
   - Global (`~/.claude/skills/learned/`): 2プロジェクト以上で使える汎用パターン
   - Project (`.claude/skills/learned/`): プロジェクト固有知識
   - 迷ったらGlobal（Global→Projectの移動は逆より簡単）

4. **skillファイル下書き:**

```md
---
name: pattern-name
description: "Under 130 characters"
user-invocable: false
origin: auto-extracted
---
## Problem / Solution / When to Use
```

5. **品質ゲート — チェックリスト + 総合判定**

   **必須チェックリスト（実際にファイル読んで確認）:**
   - [ ] `~/.claude/skills/` と project の `.claude/skills/` をgrepして重複確認
   - [ ] MEMORY.md（projectとglobal両方）で重複確認
   - [ ] 既存skillへの追記で足りるか検討
   - [ ] 一回限りの修正でなく再利用可能なパターンか確認

   **総合判定（1つ選ぶ）:**

   - **Save**: 独自性あり・具体的・範囲適切 → Step 6へ
   - **Improve then Save**: 価値はあるが改善必要 → 改善点列挙→修正→再評価（1回）
   - **Absorb into [X]**: 既存skillに追記すべき → 対象skillと追加内容を示す→Step 6
   - **Drop**: 自明・重複・抽象的すぎ → 理由説明して終了

6. **判定別確認フロー:**
   - **Save**: 保存先 + チェック結果 + 判定理由 + 完全下書き → ユーザー確認後保存
   - **Improve then Save**: 改善点 + 修正版 + 再評価 → Saveなら確認後保存
   - **Absorb into [X]**: 対象パス + diff + 判定理由 → ユーザー確認後追記
   - **Drop**: チェック結果 + 理由のみ（確認不要）

7. 決定した保存先へ保存/追記

## Step 5 出力形式

```md
### チェックリスト
- [ ] skills/ grep: 重複なし
- [ ] MEMORY.md: 重複なし
- [ ] Existing skill append: 新規ファイルが適切
- [ ] Reusability: 確認済み

### Verdict: Save / Improve then Save / Absorb into [X] / Drop
**Rationale:** （1〜2文）
```

## 注意

- タイプミス・単純な構文エラーは抽出しない
- 一回限りの問題は抽出しない
- skillは1パターンに集中
- Absorb判定時は新規作成でなく既存skillに追記
