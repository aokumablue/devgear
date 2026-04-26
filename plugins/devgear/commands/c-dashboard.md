---
name: c-dashboard
description: スキル/コマンド/エージェント使用率を個人（SQLite）とチーム（PostgreSQL）で比較する静的 HTML ダッシュボード生成。
command: /c-dashboard
---

# ダッシュボード生成

個人データ（SQLite）常時収集・PostgreSQL設定時はチームデータも収集→個人 vs チーム比較表示の静的HTMLダッシュボード生成。スキル健全性・成長候補・プロジェクト登録もここに集約する。

## 前提条件

- ローカルSQLite（`~/.devgear/mem.db`）初期化済み
- チーム比較: `settings.json` で `mem.sync.enabled: true` かつ `postgres_url` 設定済み

## 使い方

```bash
/c-dashboard                                    # デフォルト（30日・HTML出力）
/c-dashboard --days 90                          # 90日間
/c-dashboard --output ~/reports/dashboard.html  # 出力先指定
/c-dashboard --format json                      # JSONエクスポート
```

## 実装

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_mem_json dashboard '{"days": 30, "output": "./devgear-dashboard.html", "format": "html"}'
```

## ダッシュボード内容

### アイテム使用率パネル

集計対象: `mem_item_runs` テーブル実行記録ありのみ

- スキル使用回数ランキング: グループ横棒グラフ（個人 vs チーム）
- コマンド使用回数ランキング: 同上
- エージェント使用回数ランキング: 同上
- 日次実行トレンド: 2系列折れ線グラフ
- アウトカム分布: ドーナツ（success/partial/failure/unknown）

### Skill Health / Growth / Projects

- スキル健全性: 7日/30日成功率、低下トレンド、保留修正
- スキル成長候補: 繰り返しパターン、ギャップ候補、実行アクション
- プロジェクト登録: 既知プロジェクト、インスティンクト数、観測数、最終検出時刻

### メモリ統計パネル（PostgreSQL設定時のみ）

- ユーザー別アクティビティ: 横棒グラフ
- プロジェクト別アクティビティ: 横棒グラフ
- ツール使用分布: ドーナツ
- 日次アクティビティ推移: 折れ線
- ファイル変更頻度: テーブル
- インスティンクト成長: 棒グラフ

## 引数

$ARGUMENTS:

- `--days <n>` - 集計期間（デフォルト: 30）
- `--output <path>` - 出力先（デフォルト: /tmp/devgear-dashboard.html）
- `--format <html|json>` - 出力形式（デフォルト: html）
