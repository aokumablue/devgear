---
name: c-instinct
description: インスティンクト エクスポート/インポート/昇格/削除の統合コマンド。
command: /c-instinct
---

# インスティンクト管理

学習済みインスティンクトの管理・昇格・削除を扱う。状態確認は `c-dashboard` に集約する。

## 実装

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.skills.learn.cli <subcommand> [options]
```

## サブコマンド

### export

インスティンクトをYAML形式で書き出し。

```bash
/c-instinct export # 全インスティンクト
/c-instinct export --domain testing # ドメイン指定
/c-instinct export --min-confidence 0.7 # 信頼度フィルタ
/c-instinct export --scope project --output out.yaml
```

**フラグ:** `--domain <name>`, `--min-confidence <n>`, `--output <file>`, `--scope <project|global|all>`

### import

ローカルファイルまたはURLからインスティンクト取り込み。

```bash
/c-instinct import team-instincts.yaml
/c-instinct import https://github.com/org/repo/instincts.yaml
/c-instinct import team-instincts.yaml --dry-run
/c-instinct import team-instincts.yaml --scope global --force
```

**フラグ:** `--dry-run`, `--force`, `--min-confidence <n>`, `--scope <project|global>`

**マージ動作:** 高信頼importは更新候補・同等以下はスキップ。`--force`以外はユーザー確認。

### promote

projectスコープのインスティンクトをglobalスコープへ昇格。

```bash
/c-instinct promote                     # 自動で昇格候補検出
/c-instinct promote --dry-run           # プレビュー
/c-instinct promote grep-before-edit    # 個別指定
```

**昇格条件:** 2プロジェクト以上に出現・信頼度しきい値を満たす。

### prune

レビュー・昇格されなかった期限切れの保留インスティンクト削除。

```bash
/c-instinct prune                       # 30日より古いものを削除
/c-instinct prune --max-age 60          # 期限を日数で指定
/c-instinct prune --dry-run             # プレビュー
```

## 永続メモリ

search: `instinct applied used`
record: `{"event_type": "instinct-{action}", "content": "{summary}"}`

## 引数

$ARGUMENTS: `export [options] | import <file-or-url> [options] | promote [instinct-id] [options] | prune [options]`
