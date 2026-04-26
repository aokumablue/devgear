# memフック蓄積データ監査報告書

**日時**: 2026-04-26  
**対象**: devgear.mem システムのフック実装と蓄積状況  
**調査結果**: **🔴 重大な蓄積漏れが発見されました**

---

## 📊 蓄積データの現状

### DBの実態

| テーブル | 件数 | 最終更新 | ステータス |
|---|---|---|---|
| `memory_chunks` | **0** | — | 🔴 **蓄積なし** |
| `sessions` | **0** | — | 🔴 **蓄積なし** |
| `interaction_logs` | **0** | — | 🔴 **蓄積なし** |
| `mem_item_runs` | **0** | — | 🔴 **蓄積なし** |
| `project_profiles` | 2 | 2026-04-26 01:52:40 | 🟡 **部分的** |

**結論**: ツール使用、セッション、インタラクションが**ほぼ全く記録されていない**

---

## 🎯 フック機能マトリックス

### SessionStart フェーズ

| フック | コマンド | 機能 | ステータス | 記録先 |
|---|---|---|---|---|
| SessionStart #1 | `devgear.mem.cli setup` | DB スキーマ初期化 | ✅ 実装済み | (N/A) |
| SessionStart #2 | `devgear.hooks.session_start` | コンテキスト読み込み | ✅ 実装済み | (N/A) |
| SessionStart #3 | `devgear.mem.cli context` | 過去チャンク検索・注入 | ✅ 実装済み | memory_chunks 参照 |
| **実装漏れ** | `devgear.mem.cli record-project-profile` | プロジェクトメタデータ記録 | ❌ **未登録** | project_profiles |

---

### UserPromptSubmit フェーズ

| フック | コマンド | 機能 | ステータス | 記録先 |
|---|---|---|---|---|
| UserPromptSubmit #1 | `devgear.mem.cli session-init` | セッション初期化 + 適応的検索 | ✅ 実装済み | memory_chunks 参照 |
| UserPromptSubmit #2 | `devgear.mem.cli team-session-init` | チーム共有チャンク検索 | ✅ 実装済み | (PostgreSQL) |
| UserPromptSubmit #3 | `devgear.hooks.pre_user_prompt` | Slim コマンド検出 | ✅ 実装済み | (N/A) |
| UserPromptSubmit #4 | `devgear.mem.cli sync-check` | PostgreSQL 同期確認 | ✅ 実装済み | (PostgreSQL) |
| **実装漏れ** | `devgear.mem.cli record-interaction` | ユーザープロンプト + AI応答の記録 | ❌ **未登録** | interaction_logs |

**問題**: interaction_logs テーブルが完全に空（ユーザーとAIのやり取りが一切記録されない）

---

### PreToolUse フェーズ

| フック | コマンド | 機能 | ステータス | 問題 |
|---|---|---|---|---|
| PreToolUse #1 | `devgear.hooks.block_no_verify` | `--no-verify` フラグブロック | ✅ 実装済み | — |
| PreToolUse #2 | `devgear.hooks.pre_bash_commit_quality` | コミット前品質チェック | ✅ 実装済み | — |
| **⚠️ 逆転** | `devgear.mem.cli observe` | ツール使用を memory_chunks に記録 | ❌ **タイミング間違い** | **ツール結果がまだない** |

**問題**: `observe` コマンドは tool_response が必須なのに、PreToolUse（実行**前**）で呼ばれている

---

### PostToolUse フェーズ

| ツール | フック | コマンド | 機能 | ステータス | 記録先 |
|---|---|---|---|---|---|
| Skill | PostToolUse #1 | `devgear.mem.cli record-item-run` | スキル実行を記録 | ✅ 実装済み | mem_item_runs |
| Bash | **未登録** | `devgear.mem.cli observe` | 変更内容を記録 | ❌ **完全漏れ** | memory_chunks |
| Write | **未登録** | `devgear.mem.cli observe` | ファイル作成を記録 | ❌ **完全漏れ** | memory_chunks |
| Edit | **未登録** | `devgear.mem.cli observe` | コード変更を記録 | ❌ **完全漏れ** | memory_chunks |
| MultiEdit | **未登録** | `devgear.mem.cli observe` | 複数ファイル編集を記録 | ❌ **完全漏れ** | memory_chunks |

**結論**: **主要な変更系ツール (Bash/Write/Edit/MultiEdit) が memory_chunks に記録されない**

---

### SessionEnd フェーズ

| フック | コマンド | 機能 | ステータス | 記録先 |
|---|---|---|---|---|
| SessionEnd #1 | `devgear.hooks.session_end_marker` | セッション終了マーカー | ✅ 実装済み | (N/A) |
| SessionEnd #2 | `devgear.mem.cli session-end` | 埋め込み一括生成 + 最適化 | ✅ 実装済み | memory_chunks (embedding) |
| SessionEnd #3 | `devgear.mem.cli sync-check` | PostgreSQL バッチ同期 | ✅ 実装済み | (PostgreSQL) |

**注**: 埋め込み生成前に memory_chunks が空なため、実質的には役に立たない

---

## 📋 記録対象テーブルの詳細

### memory_chunks テーブル

**現状**: 0 件（蓄積ゼロ）

| カラム | ソース | コマンド | 登録フック | 実装ステータス |
|---|---|---|---|---|
| session_id | ユーザープロンプト | observe | PostToolUse | ❌ フック未登録 |
| tool_names | ツール実行 | observe | PostToolUse | ❌ フック未登録 |
| files_read | Bash/Write出力解析 | observe | PostToolUse | ❌ フック未登録 |
| files_modified | Bash/Write出力解析 | observe | PostToolUse | ❌ フック未登録 |
| content | tool_response | observe | PostToolUse | ❌ フック未登録 |
| user_prompt | stdin | observe | PostToolUse | ❌ フック未登録 |
| execution_status | tool_response 解析 | observe | PostToolUse | ❌ フック未登録 |
| tool_error | tool_response 解析 | observe | PostToolUse | ❌ フック未登録 |
| ai_response_summary | AI応答 | observe | PostToolUse | ❌ フック未登録 |

**蓄積漏れの理由**: PostToolUse フックで `observe` が登録されていない

---

### interaction_logs テーブル

**現状**: 0 件（完全に蓄積ゼロ）

| カラム | ソース | コマンド | 登録フック | 実装ステータス |
|---|---|---|---|---|
| user_prompt_full | ユーザープロンプト | record-interaction | **(未登録)** | ❌ **完全漏れ** |
| ai_response_summary | Claude の応答 | record-interaction | **(未登録)** | ❌ **完全漏れ** |
| ai_response_tool_plan | ツール計画 | record-interaction | **(未登録)** | ❌ **完全漏れ** |
| execution_outcome | tool実行結果 | record-interaction | **(未登録)** | ❌ **完全漏れ** |
| tool_error_count | エラー数 | record-interaction | **(未登録)** | ❌ **完全漏れ** |

**蓄積漏れの理由**: interaction_logs 記録機能がフックから呼ばれていない（実装はあるが未登録）

---

### mem_item_runs テーブル

**現状**: 0 件

| カラム | ソース | コマンド | 登録フック | 実装ステータス |
|---|---|---|---|---|
| skill_name | Skill ツール | record-item-run | PostToolUse(Skill) | ✅ 実装済み |
| outcome | stdin | record-item-run | PostToolUse(Skill) | ✅ 実装済み |
| item_type | stdin (skill/command/agent) | record-item-run | PostToolUse(Skill) | ✅ 実装済み |

**注**: スキル実行の記録は登録されているが、**実際には一度も呼ばれていない**（ユーザーがスキルを使っていない、またはアクセス中に記録フックが動作しない）

---

## 🔴 蓄積漏れの根本原因

### 原因1: PostToolUse(Bash/Write/Edit/MultiEdit) フック未登録

**何が起こるべきか**:
```
User Prompt → Bash Tool → tool_response ready → PostToolUse Hook → 
  `devgear.mem.cli observe` → memory_chunks に記録
```

**実際に起こっていること**:
```
User Prompt → Bash Tool → tool_response ready → (何も起きない)
```

**修正**: hooks.json に以下を追加
```json
{
  "matcher": "Bash|Write|Edit|MultiEdit",
  "command": "devgear.mem.cli observe",
  "async": true,
  "timeout": 10
}
```

---

### 原因2: interaction_logs 記録フック未登録

**何が起こるべきか**:
```
User Prompt Submit → `devgear.mem.cli record-interaction` → interaction_logs に記録
```

**実際に起こっていること**:
```
User Prompt Submit → (何も起きない)
```

**修正**: hooks.json の UserPromptSubmit に以下を追加
```json
{
  "matcher": "*",
  "command": "devgear.mem.cli record-interaction",
  "timeout": 30
}
```

---

### 原因3: PreToolUse/observe のタイミング逆転

**現在の実装**:
```json
"PreToolUse": [
  {
    "command": "devgear.mem.cli observe"  // ← ツール実行前に呼ぶ
  }
]
```

**問題**: `observe` は tool_response を要求するが、PreToolUse では result がまだない

**修正**: 以下のように移動
```json
"PostToolUse": [
  {
    "matcher": "Bash|Write|Edit|MultiEdit",
    "command": "devgear.mem.cli observe"
  }
]
```

---

### 原因4: project_profiles 自動記録フック未登録

**何が起こるべきか**:
```
SessionStart → プロジェクト検出 → `devgear.mem.cli record-project-profile` → 
  project_profiles に記録
```

**実際に起こっていること**:
```
SessionStart → (project_profiles は手動でしか更新されない)
```

**修正**: hooks.json の SessionStart に以下を追加
```json
{
  "matcher": "*",
  "command": "devgear.mem.cli record-project-profile",
  "timeout": 15
}
```

---

## 📈 蓄積されるべき種類とタイミング

### タイミング別蓄積一覧

| タイミング | イベント | テーブル | 何が記録されるか | 現状 |
|---|---|---|---|---|
| **SessionStart** | セッション開始 | sessions (本来) | セッションID、ブランチ、コミット | ❌ 蓄積なし |
| **SessionStart** | セッション開始 | project_profiles | 言語、フレームワーク | ❌ フック未登録 |
| **UserPromptSubmit** | プロンプト送信 | interaction_logs | ユーザープロンプト、インデックス | ❌ フック未登録 |
| **PreToolUse** | ツール実行前 | (記録なし) | — | ✅ 正常 |
| **PostToolUse(Bash)** | Bash 実行後 | memory_chunks | コマンド、出力、ファイル変更 | ❌ フック未登録 |
| **PostToolUse(Write)** | ファイル作成後 | memory_chunks | パス、内容要約 | ❌ フック未登録 |
| **PostToolUse(Edit)** | コード編集後 | memory_chunks | パス、変更内容、diff | ❌ フック未登録 |
| **PostToolUse(MultiEdit)** | 複数編集後 | memory_chunks | パス複数、diff 集計 | ❌ フック未登録 |
| **PostToolUse(Skill)** | スキル実行後 | mem_item_runs | スキル名、結果、実行時間 | ✅ 登録済み |
| **SessionEnd** | セッション終了 | memory_chunks (embedding) | embeddings 生成・保存 | ⚠️ 前提が空 |

---

## 🔧 修正提案

### 優先度1: 必須フック登録

#### 1.1 PostToolUse(Bash/Write/Edit) に observe を追加

**ファイル**: `plugins/devgear/hooks/hooks.json`  
**場所**: `PostToolUse` セクション

```json
{
  "matcher": "Bash|Write|Edit|MultiEdit",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/src/devgear/launcher.py\" devgear.mem.cli observe",
      "async": true,
      "timeout": 10
    }
  ],
  "description": "mem: ツール実行（Bash/Write/Edit）をメモリチャンクに記録"
}
```

#### 1.2 UserPromptSubmit に record-interaction を追加

```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/src/devgear/launcher.py\" devgear.mem.cli record-interaction",
      "timeout": 30
    }
  ],
  "description": "mem: ユーザープロンプトと AI応答のペア記録（interaction_logs）"
}
```

### 優先度2: 重要フック登録

#### 2.1 SessionStart に record-project-profile を追加

```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/src/devgear/launcher.py\" devgear.mem.cli record-project-profile",
      "timeout": 15
    }
  ],
  "description": "mem: プロジェクトプロファイル自動記録（言語、フレームワーク）"
}
```

### 優先度3: PreToolUse/observe の位置修正

**現在の状態**: `PreToolUse` の中に `observe` がある  
**修正**: `PostToolUse` に移動（ツール実行後）  
**理由**: tool_response が必要だから

---

## 📊 修正後の期待値

### 修正完了後のDB蓄積量（予測）

| テーブル | 修正前 | 修正後 | 根拠 |
|---|---|---|---|
| memory_chunks | 0 | 10-20/session | Bash/Write/Edit/MultiEdit が記録される |
| sessions | 0 | 1/session | SessionStart で初期化 |
| interaction_logs | 0 | 5-10/session | 各ユーザープロンプト毎 |
| mem_item_runs | 0 | 0-5/session | スキル使用時のみ |
| project_profiles | 2 | 2-3 | プロジェクト初回検出時のみ |

---

## ✅ 検証チェックリスト

修正後、以下で動作確認してください：

- [ ] hooks.json を修正
- [ ] `python3 -m pytest tests/ci/test_harness_audit.py -v` でテスト実行
- [ ] 新規セッションで Bash 実行 → memory_chunks に記録されるか確認
- [ ] プロンプト送信 → interaction_logs に記録されるか確認
- [ ] `devgear mem.cli compact` で記録内容を確認
- [ ] PostgreSQL 同期が有効なら `sync-check` で PostgreSQL にも蓄積されるか確認

---

## 📌 結論

**状況**: memシステムは実装は完全だが、フック登録が**4つ不完全**

**蓄積漏れ**:
- 🔴 memory_chunks: 0/N 件 (PostToolUse フック未登録)
- 🔴 interaction_logs: 0/N 件 (ユーザープロンプト記録フック未登録)
- 🟡 mem_item_runs: 0/N 件 (登録済みだが呼ばれたことがない)
- 🟡 project_profiles: 2 件 (手動のみ、自動化なし)

**対応**: hooks.json に4つのフック追加で完全蓄積が実現可能

---

## ✅ 修正完了（2026-04-26）

### 実装した修正

| # | 修正項目 | ファイル | 変更内容 |
|---|---|---|---|
| 1 | PreToolUse の observe 削除 | hooks.json | `PreToolUse` から `devgear.mem.cli observe` を削除 |
| 2 | PostToolUse に observe 追加 | hooks.json | `PostToolUse` に `matcher: "Bash\|Write\|Edit\|MultiEdit"` で observe を追加 |
| 3 | interaction_logs 記録機能追加 | hooks.json | `UserPromptSubmit` に `devgear.mem.cli record-interaction` を追加 |
| 4 | project_profiles 自動記録 | hooks.json | `SessionStart` に `devgear.mem.cli record-project-profile` を追加 |

### 修正後のフック配置

#### SessionStart
```
1. devgear.mem.cli setup              [DB初期化]
2. devgear.hooks.session_start        [コンテキスト読み込み]
3. devgear.mem.cli record-project-profile  [プロジェクト情報]
4. devgear.mem.cli context            [メモリ検索・注入]
```

#### UserPromptSubmit
```
1. devgear.mem.cli session-init       [セッション初期化・適応的検索]
2. devgear.mem.cli team-session-init  [チーム共有検索]
3. devgear.mem.cli record-interaction [プロンプト記録] ✅ NEW
4. devgear.hooks.pre_user_prompt      [Slim検出]
5. devgear.mem.cli sync-check         [同期確認]
```

#### PostToolUse
```
1. devgear.mem.cli observe            [ツール使用記録] ✅ NEW (moved from PreToolUse)
2. devgear.mem.cli record-item-run    [スキル実行記録]
3. devgear.hooks.post_bash_compact    [出力圧縮]
4. devgear.hooks.post_bash_pr_created [PR記録]
5. devgear.hooks.quality_gate         [品質ゲート]
```

#### SessionEnd
```
1. devgear.hooks.session_end_marker   [セッション終了マーカー]
2. devgear.mem.cli session-end        [埋め込み一括生成]
3. devgear.mem.cli sync-check         [PostgreSQL同期]
```

### 検証結果

- ✅ JSON 形式検証: 成功
- ✅ pytest テスト: 7/7 パス
- ✅ ruff linting: 警告なし
