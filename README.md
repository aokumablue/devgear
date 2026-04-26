# devgear

開発に必要な汎用プラグイン集です。エージェント、スキル、フック、コマンドをまとめて導入し、計画・実装・検証・レビューの流れを揃えます。

## まず必要なもの

- Claude Code
- Python 3.12+（devgear プラグイン本体と内部ヘルパー用。ユーザープロジェクト側の言語ランタイムは不要）
- Git

## 対応するプロジェクト

このプラグインは、ユーザープロジェクトの言語や実行環境を広く問わず使えるようにしています。たとえば Ruby on Rails、Python、Go、JS/TS、React、Next.js、Nuxt、Angular などのプロジェクトを対象にできます。

ユーザープロジェクトに特定言語のランタイムが入っていなくても、プラグイン自体の導入やセッション運用は継続できます。言語固有のコマンドやスキルを明示的に使う場合だけ、その言語の実行環境が必要です。

## プラグインのインストール

### インストール

Claude Code の場合:

```bash
claude plugin marketplace add aokumablue/devgear
claude plugin install devgear@devgear
```

## 関連ソフトウェア/設定ファイルのインストール

```bash
bash scripts/install.sh
```

## 設定ファイル

`bash scripts/install.sh` で `~/.devgear/settings.json` を最小構成で生成する。大半の項目は自動判定・内部デフォルトで賄うため、ユーザーが通常触るのはチーム同期を有効化するときの `mem.sync.postgres_url` のみ。

最小構成:

```json
{
  "mem": {
    "sync": {
      "enabled": false,
      "postgres_url": ""
    }
  }
}
```

### 自動判定される項目

| 項目 | 判定方法 |
| --- | --- |
| 主要言語 | `devgear.lib.project_detect.detect_project()` がプロジェクト配下のファイルから検出 |
| git ホスティングサービス | `git remote get-url origin` の URL から GitHub / GitLab を推測 |
| カバレッジ目標 | プロジェクト／親ディレクトリの `CLAUDE.md` から抽出（例: `カバレッジ80%`）。未記載時は `80` |
| quality-gate のツール | 主要言語に対応するプリセットを適用（Python: `ruff check`、JS/TS: `npx eslint`、Go: `go vet`、Rust: `cargo clippy`、Ruby: `rubocop`）。未対応言語や実行ファイル不足の場合は安全にスキップ |

### 補足

- ここで必要なのは devgear 自身の実行環境であり、ユーザープロジェクトの言語ランタイムではない
- Ruby on Rails / Python / Go / JS/TS などの一般的なプロジェクトで利用できる
- 主要言語が判定できない場合や、該当ツールが PATH にない場合は quality-gate は失敗せずに空のルールとして扱う

### 永続メモリのチーム共有

PostgreSQL でメモリをチーム共有する場合のみ設定する。

| 項目 | 説明 | デフォルト |
| --- | --- | --- |
| `mem.sync.enabled` | PostgreSQL 同期を有効化するかどうか | `false` |
| `mem.sync.postgres_url` | 接続 URL（`enabled=true` のときは必須） | `""` |

同期元ユーザー名は git の `user.name` を自動で使う。ランタイム状態（最終同期時刻・成否など）は `~/.devgear/sync_state.json` に分離保存される。

- フックは常に strict として動作する
- `mem` は `observe` → `session-init` → `SessionEnd` を中心に履歴を引き継ぎ、必要時のみ `SessionStart` で文脈を注入する
- 詳細なフック設定は `plugins/devgear/hooks/README.md` を参照する

## 何が入っているか

- `plugins/devgear/agents/` - 計画、レビュー、TDD、セキュリティ
- `plugins/devgear/skills/` - ワークフローと知識
- `plugins/devgear/commands/` - `/c-*` コマンド
- `plugins/devgear/hooks/` - ツール実行前後の自動化
- `plugins/devgear/src/devgear/` - ランタイム
- `plugins/devgear/src/devgear/mem/` - 永続メモリ

## まず試すもの

1. `bash scripts/install.sh`
2. `/c-sessions`
3. `/c-plan`
4. `/c-tdd`
5. `/c-review`
6. `/c-clean`

## 詳細

- `CLAUDE.md` - このリポジトリで作業する時の基本ルール
- `plugins/devgear/commands/` - 各コマンドの詳細
- `plugins/devgear/skills/` - 各スキルの詳細
- `plugins/devgear/hooks/README.md` - フックの設定とカスタマイズ
- `plugins/devgear/commands/c-skill-create.md` / `plugins/devgear/skills/s-skillmaster/SKILL.md` - スキル生成・改善
- `plugins/devgear/skills/s-learn/SKILL.md` - 学習と昇格

## メモ

```bash
# プライベートリポジトリのプラグインをインストールする場合はSSHを使用するように設定が必要
git config --global url.ssh://git@github.com/.insteadOf https://github.com/
```
