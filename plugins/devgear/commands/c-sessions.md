---
name: c-sessions
description: セッション履歴/エイリアス/保存/再開/メタデータ管理。
command: /c-sessions
---

# Sessions コマンド

`~/.claude/session-data/` のセッション履歴管理。

## 永続メモリ

search: `lesson learned blocker workaround`
record: `{"event_type": "session-save", "content": "{セッションサマリー}"}`
resume時にmemから関連する過去の作業を必要時のみ補完する。

## 使い方

`/c-sessions [action] [options]`

## アクション

### list

```bash
/c-sessions                          # 全セッション一覧
/c-sessions list --limit 10
/c-sessions list --date 2026-02-01
```

**Script:**

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.commands.session_commands list --limit 20
```

### load

```bash
/c-sessions load <id|alias>
```

**Script:**

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.commands.session_commands load $ARGUMENTS
```

### alias

```bash
/c-sessions alias <id> <name>     # 作成
/c-sessions alias --remove <name> # 削除
/c-sessions aliases               # 一覧
```

**Script (create):**

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
devgear_run devgear.commands.session_commands alias $ARGUMENTS
```

### save / resume

```bash
/c-sessions save                      # 変更・決定・失敗・未完了事項を保存
/c-sessions resume [id|date|path]     # 引数なしなら最新ファイルを選択
```

## 引数

`list [--limit n] [--date YYYY-MM-DD] [--search pattern]` / `load <id|alias>` / `alias <id> <name>` / `alias --remove <name>` / `aliases` / `save` / `resume [id|date|path]`

## Notes

- セッションファイル: `~/.claude/session-data/` にmarkdownとして保存
- エイリアス: `~/.claude/session-aliases.json`
- セッションIDは先頭4〜8文字で十分一意
