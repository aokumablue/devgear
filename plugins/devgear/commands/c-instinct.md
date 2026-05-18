---
name: c-instinct
description: インスティンクト エクスポート/インポート/昇格/削除の統合コマンド。
command: /c-instinct
---

# インスティンクト管理

学習済みインスティンクトの管理・昇格・削除を扱う。状態確認は `c-dashboard` に集約する。

## s-grillme 強制起動（必須）

開始直後に s-grillme を必ず起動し、完了まで他の処理に進まない。

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

**実施内容:** プロジェクトコンテキスト検出→project/globalインスティンクト読込（ID衝突時はproject優先）→パターン分類→候補特定→`evolved/{skills,commands,agents}/` 配下にファイル生成

**進化ルール:** Command=ユーザー明示呼び出し / Skill=自動発火パターン / Agent=複雑多段階処理

**生成ファイルフロントマター:** `name` / `description` / `evolved_from: [{instinct-ids}]`

## プロンプト推論（サブコマンド自動判定）

明示サブコマンドなし → プロンプト本文からキーワード照合（書き出/エクスポート→export、取り込/インポート→import、昇格/グローバル化→promote、整理/削除/古い→prune、進化/生成/スキル化→evolve）。推論結果は実行前に1行表示。複数一致/該当なし → `s-grillme` 起動。明示サブコマンドがあれば推論スキップ。

## 永続メモリ

search: `instinct applied used`
record: `{"event_type": "instinct-{action}", "content": "{summary}"}`
record (evolve): `{"event_type": "evolve", "content": "Evolved: X skills, Y commands, Z agents from N instincts"}`
参照: 進化決定履歴 / クラスタリングルール / 昇格成功率

## 引数

$ARGUMENTS: `export | import <file-or-url> | promote | prune | evolve`
