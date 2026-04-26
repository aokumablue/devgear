---
name: c-instinct
description: インスティンクト エクスポート/インポート/昇格/削除の統合コマンド。
command: /c-instinct
---

# インスティンクト管理

学習済みインスティンクトの管理・昇格・削除を扱う。状態確認は `c-dashboard` に集約する。

## 実装

```bash
source "${CLAUDE_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.skills.learn.cli <subcommand>
```

## サブコマンド

### export

全インスティンクトをYAML形式でstdoutに出力する。

```bash
/c-instinct export
```

### import

ローカルファイルまたはURLから全インスティンクトを取り込む。確認なしで即時適用する。

```bash
/c-instinct import team-instincts.yaml
/c-instinct import https://github.com/org/repo/instincts.yaml
```

### promote

昇格条件を満たす全候補をprojectスコープからglobalスコープへ自動昇格する。

昇格条件: 2プロジェクト以上に出現・信頼度しきい値を満たす。

```bash
/c-instinct promote
```

### prune

30日より古い未レビュー・未昇格の保留インスティンクトを削除する。

```bash
/c-instinct prune
```

### evolve

蓄積されたインスティンクトからスキル・コマンド・エージェント候補を検出し、ファイルを生成する。

```bash
/c-instinct evolve
```

**実施内容:**
1. 現在のプロジェクトコンテキスト検出
2. project / global のインスティンクト読む（ID衝突時はproject優先）
3. トリガー/ドメインパターンごとに分類
4. Skill候補（2件以上同パターンクラスタ）・Command候補・Agent候補を特定
5. 昇格候補（project→global）を提示
6. `evolved/{skills,commands,agents}/` 配下にファイル生成

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

## 自然言語指示

サブコマンドの代わりに自然言語で指示してもよい。例:

- 「インスティンクトを書き出して」→ export 相当
- 「team.yaml を取り込んで」→ import 相当
- 「昇格できるものを全部昇格して」→ promote 相当
- 「古いインスティンクトを整理して」→ prune 相当
- 「インスティンクトからスキルを生成して」→ evolve 相当

## 永続メモリ

search: `instinct applied used`
record: `{"event_type": "instinct-{action}", "content": "{summary}"}`
record (evolve): `{"event_type": "evolve", "content": "Evolved: X skills, Y commands, Z agents from N instincts"}`
参照: 進化決定履歴 / クラスタリングルール / 昇格成功率

## 引数

$ARGUMENTS: `export | import <file-or-url> | promote | prune | evolve`
