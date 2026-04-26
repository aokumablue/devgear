---
name: c-evolve
description: インスティンクト分析→進化した構造を提案/生成。
command: /c-evolve
---

# 進化コマンド

## 永続メモリ

search: `evolve skill command agent` / `{ドメイン名} pattern instinct`
record: `{"event_type": "evolve", "content": "Evolved: X skills, Y commands, Z agents from N instincts"}`
参照: 進化決定履歴 / クラスタリングルール / 昇格成功率

## 実装

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.skills.learn.cli evolve [--generate]
```

## 使い方

```bash
/c-evolve              # 分析して進化案を示す
/c-evolve --generate   # ファイルも生成する
```

## 進化ルール

- **Command**: ユーザーが明示的に呼び出す操作・繰り返し可能な手順
- **Skill**: 自動発火する振る舞い・パターンマッチ型トリガー
- **Agent**: 複雑多段階処理・分離の恩恵がある場合

## 実施内容

1. 現在のプロジェクトコンテキスト検出
2. project / global のインスティンクト読む（ID衝突時はproject優先）
3. トリガー/ドメインパターンごとに分類
4. Skill候補（2件以上クラスタ）・Command候補・Agent候補特定
5. 昇格候補（project→global）提示
6. `--generate` 時は `evolved/{skills,commands,agents}` 配下にファイル生成

## 生成ファイル形式

```md
---
name: {name}
description: {description}
evolved_from: [{instinct-ids}]
---
[クラスタ化インスティンクトから生成された内容]
```

## 引数

`--generate`: 分析出力に加えて進化済みファイル生成
