---
name: c-skill-create
description: リポジトリ固有入力収集→s-skillmasterにSKILL.md生成委譲。
command: /c-skill-create
---

# スキル生成入力収集

リポジトリ固有入力を集めて整理し、SKILL.md生成はs-skillmasterに委譲。

## 使い方

```bash
/c-skill-create                    # 現在のリポジトリ分析
/c-skill-create --commits 100      # 直近100件のコミット分析
/c-skill-create --output ./skills  # 生成先指定
/c-skill-create --instincts        # インスティンクト生成も依頼
```

## 手順

### ステップ1: 入力候補収集

```bash
source "${DEVGEAR_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
collect_skill_create_inputs "${COMMITS:-200}"
devgear_mem_search "<search query>" 3
```

### ステップ2: パターン検出

- コミット規約: コミットメッセージ正規表現（feat:, fix:, chore:）
- ファイル同時変更: 常に一緒に変更されるファイル
- ワークフロー連続パターン: 繰り返しファイル変更パターン
- アーキテクチャ: フォルダ構造と命名規則
- テストパターン: テストファイルの場所・命名・カバレッジ

### ステップ3: s-skillmaster呼び出し

整理した入力を渡すとSKILL.md生成。

### ステップ4: インスティンクト生成（--instincts時）

s-learn連携用インスティンクトも同流れで生成。

## 関連

- `/c-instinct import` — 生成インスティンクトをインポート
- `/c-dashboard` — 学習済みインスティンクトや成長候補の可視化
- `/c-evolve` — インスティンクトをskills/agentsにクラスタリング
