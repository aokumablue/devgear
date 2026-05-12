---
name: c-clean
description: 各ステップでテスト検証しながら安全にデッドコード特定・削除。
command: /c-clean
---

# リファクタリング整理

## s-grillme 強制起動（必須）

開始直後に s-grillme を必ず起動し、完了まで他の処理に進まない。

## 永続メモリ

search: `rollback revert undo delete remove` / `ADR architecture decision {対象ファイルパス}`
record: `{"event_type": "clean", "content": "Deleted: X functions, Y files. Skipped: Z items"}`
参照: 危険削除履歴 / アーキテクチャ制約 / 動的参照パターン。
memで検出時: ロールバック履歴あり→SAFE→CAUTION昇格 / ADR参照→CAUTION→DANGER昇格 / 動的import→確認要求

## ステップ1: デッドコード検出

プロジェクト種別に応じて解析ツール実行:

- knip: 未使用エクスポート・ファイル・依存関係 → `npx knip`
- depcheck: 未使用npm依存 → `npx depcheck`
- ts-prune: 未使用TSエクスポート → `npx ts-prune`
- vulture: 未使用Pythonコード → `vulture src/`
- deadcode: 未使用Goコード → `deadcode ./...`
- cargo-udeps: 未使用Rust依存 → `cargo +nightly udeps`

ツールがない場合はGrepでインポート数0のエクスポートを探す。

## ステップ2: 分類

- **SAFE**: 未使用ユーティリティ・テストヘルパー・内部fn → 削除
- **CAUTION**: コンポーネント・APIルート・MW → 動的インポートや外部利用者確認
- **DANGER**: 設定ファイル・エントリポイント・型定義 → 触る前に調査

## ステップ3: 安全削除ループ

SAFE各項目:

1. フルテストスイート実行（全green確立）
2. デッドコード削除（Editツールで外科的に）
3. テストスイート再実行
4. テスト失敗 → `git checkout -- <file>` で戻してスキップ
5. テスト通過 → 次の項目へ

## ステップ4: CAUTION項目

削除前:

- 動的インポートを探す: `import()`, `require()`, `__import__`
- 文字列参照を探す: ルート名・設定内コンポーネント名
- 公開パッケージAPIからエクスポートされていないか確認
- 外部利用者がいないか確認

## ステップ5: 重複統合

- 80%以上類似fn → 1つに統合
- 冗長な型定義 → 統合
- 価値のないラッパーfn → 直接呼び出し
- 目的のない再エクスポート → 間接層削除

## ステップ6: 要約

```
Dead Code Cleanup
──────────────────────────────
Deleted:   12 unused functions
           3 unused files
           5 unused dependencies
Skipped:   2 items (tests failed)
Saved:     ~450 lines removed
──────────────────────────────
All tests passing PASS:
```

## ルール

- **削除前にテスト実行**
- **一度に1つだけ削除** — ロールバックを容易に
- **不確かならスキップ** — デッドコードを残す方が本番破壊よりよい
- **クリーンアップ中リファクタしない** — 先に削除、後でリファクタ
