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

### evolve

蓄積されたインスティンクトからスキル・コマンド・エージェント候補を検出・生成。

```bash
/c-instinct evolve             # インスティンクト分析・進化案を表示
/c-instinct evolve --generate  # 進化済みファイルも生成
```

**フラグ:** `--generate`（検出した新しいスキル/コマンド/エージェントをファイル生成）

**実施内容:**
1. 現在のプロジェクトコンテキスト検出
2. project / global のインスティンクト読む（ID衝突時はproject優先）
3. トリガー/ドメインパターンごとに分類
4. Skill候補（2件以上同パターンクラスタ）・Command候補・Agent候補を特定
5. 昇格候補（project→global）を提示
6. `--generate` 時は `evolved/{skills,commands,agents}/` 配下にファイル生成

**進化ルール（3分類）:**
- **Command** — ユーザーが明示的に呼び出す操作・繰り返し可能な手順・ユーザー入力が不可欠
- **Skill** — 自動発火する振る舞い・パターンマッチ型トリガー・背後で隠れた効率化
- **Agent** — 複雑な多段階処理・複数の独立した検証が必要・分離の恩恵が大きい

**生成ファイルフロントマター形式:**
```yaml
---
name: {name}
description: {description}
evolved_from: [{instinct-ids}]
---
```

## 永続メモリ

search: `instinct applied used`
record: `{"event_type": "instinct-{action}", "content": "{summary}"}`
record (evolve): `{"event_type": "evolve", "content": "Evolved: X skills, Y commands, Z agents from N instincts"}`
参照: 進化決定履歴 / クラスタリングルール / 昇格成功率

## 引数

$ARGUMENTS: `export [options] | import <file-or-url> [options] | promote [instinct-id] [options] | prune [options] | evolve [--generate]`
