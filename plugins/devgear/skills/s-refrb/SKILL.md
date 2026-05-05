---
name: s-refrb
description: c-refactor前にファイル単位ロールバック計画を確定し、失敗時の復旧を高速化する。
---

# リファクタ ロールバック設計

## 発動タイミング

- `/c-refactor` の preflight
- 失敗時の復旧が複数ファイルにまたがる変更を扱うとき
- 並列サブエージェント実行前にリスクを明示したいとき

## 目的

失敗時に迷わず復旧できるよう、**ファイル単位**の Rollback Blueprint を事前に固定する。

## 入力

- 変更対象（既定: `git diff --name-only HEAD`）
- `s-refprep` が作成したグループ/依存関係/テストセット
- 高リスク境界（公開API、外部I/O、永続化境界）

`s-refprep` 入力契約:

```json
{
  "scope_files": ["path/a.py", "path/b.py"],
  "groups": [["path/a.py"], ["path/b.py"]],
  "deps": [{"from": 1, "to": 0}],
  "tests": {
    "baseline": ["python3 -m pytest -q"],
    "group": ["python3 -m pytest -q tests/test_a.py"],
    "final": ["python3 -m pytest -q", "ruff check plugins/devgear/src plugins/devgear/tests"]
  }
}
```

必須項目:
- `scope_files`
- `groups`
- `deps`
- `tests.baseline` / `tests.group` / `tests.final`

## 手順

1. 変更対象を列挙し、各ファイルの復旧コマンドを定義する
2. 高リスク境界を `CAUTION` としてタグ付けする
3. ファイルごとに検証コマンド（テスト/linters）を紐付ける
4. グループ依存がある場合は、復旧順序を依存逆順で定義する
5. 実行用の Rollback Blueprint を出力する

`CAUTION` 判定条件:
- 公開API/外部I/O/永続化境界を含む
- 依存グループをまたぐ変更を含む

復旧順計算ルール:
- `deps` をトポロジカル順に解決
- rollback 適用時はトポロジカル順の逆順で `revert_files` を処理

## 出力形式

```text
Rollback Blueprint
──────────────────────────────
Scope: {n} files
File Rules:
  - {file}: revert="git checkout -- {file}" verify="{cmd}" risk={SAFE|CAUTION}
Order:
  - revert group {g2} -> {g1}
Skip Rules:
  - {file}: {reason} (required_action={manual_review|extra_test|keep})
──────────────────────────────
```

必須キー:

```json
{
  "file_rules": [
    {"file": "path/a.py", "revert": "git checkout -- path/a.py", "verify": "python3 -m pytest -q tests/test_a.py", "risk": "CAUTION"}
  ],
  "revert_files": ["path/a.py"],
  "deps_order": [{"from": 1, "to": 0}],
  "risk_files": [{"file": "path/a.py", "risk": "CAUTION", "reason": "public_api", "action": "manual_review"}],
  "skip_rules": [{"file": "path/a.py", "reason": "dynamic_reference", "required_action": "extra_test"}]
}
```

## ルール

- 復旧単位は常に**ファイル単位**
- 復旧コマンドは `git checkout -- <file>` を標準とする
- 不確実な変更は適用せず `Skip Rules` に記録する
- 機能変更は禁止（WHAT不変）

## 永続メモリ

search: `refactor rollback blueprint {file_path}` / `revert failure pattern`
record: `{"event_type":"refrb","content":"Scope:{scope}. RevertPlan:{n_files}. RiskFiles:{risk_files}"}`
