---
name: c-skillgen
description: リポジトリ固有入力収集→s-skillmakeにSKILL.md生成委譲→s-skilltune改善委譲。
command: /c-skillgen
---

# スキル生成入力収集

リポジトリ固有入力を集めて整理し、SKILL.md生成はs-skillmakeに、生成後の改善はs-skilltuneに委譲。

## s-grillme 強制起動（必須）

開始直後に s-grillme を必ず起動し、完了まで他の処理に進まない。

## 使い方

```bash
/c-skillgen                    # 現在のリポジトリ分析
/c-skillgen --commits 100      # 直近100件のコミット分析
/c-skillgen --output ./skills  # 生成先指定
/c-skillgen --instincts        # インスティンクト生成も依頼
```

## 手順

### ステップ1: 入力候補収集

```bash
source "${CLAUDE_PLUGIN_ROOT}/runtime/devgear-helpers.sh"
collect_skill_create_inputs "${COMMITS:-200}"
devgear_mem_search "<search query>" 3
```

### ステップ2: パターン検出

- コミット規約: コミットメッセージ正規表現（feat:, fix:, chore:）
- ファイル同時変更: 常に一緒に変更されるファイル
- ワークフロー連続パターン: 繰り返しファイル変更パターン
- アーキテクチャ: フォルダ構造と命名規則
- テストパターン: テストファイルの場所・命名・カバレッジ

### ステップ3: s-skillmake呼び出し

整理した入力を渡すとSKILL.md生成。

### ステップ4: s-skilltune呼び出し

生成されたSKILL.mdをs-skilltuneに渡し、empirical評価と反復改善を実施。
収束（連続2回で新規不明瞭点ゼロ）を確認してから次ステップへ進む。

### ステップ5: インスティンクト生成（--instincts時）

s-learn連携用インスティンクトも同流れで生成。

## 関連スキルの役割分担

| ステップ | 担当スキル | 役割 |
|---|---|---|
| 入力収集 | c-skillgen（本コマンド） | リポジトリ分析・パターン検出 |
| SKILL.md生成 | s-skillmake | 下書き作成・構造化 |
| 品質改善 | s-skilltune | empirical評価・反復改善 |

## 関連

- `/c-instinct import` — 生成インスティンクトをインポート
- `/c-dashboard` — 学習済みインスティンクトや成長候補の可視化
- `/c-instinct evolve` — インスティンクトをskills/agentsにクラスタリング
