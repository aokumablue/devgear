---
name: s-refprep
description: リファクタ着手前に対象分割・依存可視化・実行前テストセットを最小コストで確定する事前準備スキル。
---

# リファクタ事前準備

## 目的

`c-refactor` 実行前に、対象の分割方針・依存関係・検証テストを固定し、途中の手戻りを減らす。

## 手順

1. **対象確定**
   - 既定: `git diff --name-only HEAD`
   - 引数指定がある場合は指定パスを優先
2. **分割**
   - 変更対象を「同時変更が必要な塊」でグループ化
   - 依存が薄いグループを先行処理に割り当て
3. **依存可視化**
   - import/参照関係を確認し、グループ間の依存順を明示
   - 循環や高リスク境界（公開API・外部I/O）を先に記録
4. **実行前テストセット確定**
   - 全体テスト（baseline）
   - グループ単位の関連テスト
   - final gate 用テスト・lint

## 出力

```
Refactor Preflight
──────────────────────────────
Scope:      {n} files
Groups:     {g1}, {g2}, ...
Dependencies:
  - {g2} depends on {g1}
Test Set:
  - baseline: {cmd}
  - group: {cmds}
  - final: {cmds}
──────────────────────────────
```

## ルール

- 既存テスト/既存lintのみ使用
- 依存不明の対象は単独グループ化
- 公開APIを含む変更は最終グループに配置

## 永続メモリ

search: `refactor preflight scope split dependency testset`
record: `{"event_type":"refprep","content":"Scope:{scope}. Groups:{groups}. TestSet:{tests}"}`
