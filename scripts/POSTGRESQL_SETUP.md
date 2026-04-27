# PostgreSQL セットアップガイド

devgear の永続メモリ機能を有効化するための PostgreSQL セットアップ手順です。

## 概要

2 つのセットアップスクリプトが用意されています：

| スクリプト | 用途 | 対象環境 |
| --- | --- | --- |
| `pg_setup.sh docker17` | Docker で PostgreSQL 17 + pgvector を起動 | 既存 PostgreSQL がない、開発環境 |
| `pg_setup_native.sh` | 既存 PostgreSQL にユーザ・DB を作成 | PostgreSQL がサーバに既にインストール済み |

## オプション 1: Docker でのセットアップ（推奨）

### 前提条件

- Docker がインストール済み
- Docker Compose がインストール済み

### 手順

```bash
bash scripts/pg_setup.sh docker17 --workspace /path/to/workspace
```

**オプション:**

- `--workspace PATH` - ワークスペースディレクトリ（デフォルト: `$PWD`）
- `--origin-user USER` - 同期元ユーザ名（デフォルト: `$(id -un)`）
- `--server-host HOST` - サーバホスト名（デフォルト: `hostname -f`）
- `--sql-file PATH` - SQL スクリプトパス（デフォルト: `./pg_setup.sql`）
- `--force` - 既存コンテナとボリュームを削除して再作成

**出力:**

- `Dockerfile.postgres17-pgvector` - Docker イメージ定義
- `compose.yaml` - Docker Compose 設定
- `.env` - 接続情報（ランダムパスワード付き）

接続 URL は `.env` から取得：

```bash
grep POSTGRES_PASSWORD .env  # パスワード確認
# 接続: postgresql://devgear:PASSWORD@localhost:5432/devgear_mem
```

## オプション 2: 既存 PostgreSQL へのセットアップ

### 前提条件

- PostgreSQL がインストール済み（バージョン 13 以上推奨）
- `psql` がアクセス可能
- `sudo` が利用可能（pg_vector コンパイル時）
- ビルド環境：gcc、make、git

### 対応 OS

| OS | パッケージマネージャ | 対応状況 |
| --- | --- | --- |
| Ubuntu / Debian | apt | ✓ 完全対応 |
| RockyLinux / RHEL / CentOS / AlmaLinux | yum / dnf | ✓ 完全対応 |
| macOS | homebrew | ✓ 完全対応（Xcode Command Line Tools 必須） |

スクリプトは自動的にディストリビューションを検出し、適切なパッケージマネージャを使用します。

### 手順

**基本的な実行:**

```bash
bash scripts/pg_setup_native.sh
```

スクリプト実行完了時に、以下の形式でパスワードが表示されます：

```
=== PASSWORD ===
21da71f5ef4a093e9abc13917efb1582
================
```

このパスワードは **安全に保管してください**。

**パスワード保存（重要）:**

スクリプトは自動的にパスワードを JSON ファイルに保存します：

```bash
# デフォルト保存先
cat ~/.devgear/pg_credentials.json
# {
#   "user": "devgear",
#   "password": "21da71f5ef4a093e9abc13917efb1582",
#   "host": "localhost",
#   "port": 5432,
#   "database": "devgear_mem",
#   "connection_url": "postgresql://devgear:21da71f5ef4a093e9abc13917efb1582@localhost:5432/devgear_mem"
# }

# ファイル権限は 0600（オーナーのみ読み取り可能）
ls -l ~/.devgear/pg_credentials.json
# -rw------- 1 user user 256 Apr 27 12:30 /home/user/.devgear/pg_credentials.json

# 別のパスに保存する場合
bash scripts/pg_setup_native.sh --credentials-file /path/to/my_creds.json
```

**カスタム設定:**

```bash
# ユーザ名、パスワード、DB 名を指定
bash scripts/pg_setup_native.sh \
  --user devgear \
  --password my-secure-password \
  --db devgear_mem

# リモートホストの場合
bash scripts/pg_setup_native.sh \
  --host db.example.com \
  --port 5432 \
  --user devgear_prod \
  --password prod-password \
  --db devgear_mem_prod

# pg_vector インストールをスキップ（既にインストール済みの場合）
bash scripts/pg_setup_native.sh --no-install-pgvector

# スキーマ初期化をスキップ
bash scripts/pg_setup_native.sh --skip-schema

# 既存ユーザ・DB を削除して再作成
bash scripts/pg_setup_native.sh --force
```

### pg_vector の手動インストール（不要な場合）

万一自動インストールが失敗した場合の手動手順：

```bash
# 開発ファイルをインストール
sudo apt-get install postgresql-server-dev-15  # バージョンに応じて変更

# pg_vector をビルド＆インストール
git clone --branch v0.8.2 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# 拡張を有効化
psql -U postgres -d devgear_mem -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### トラブルシューティング

**接続エラー: "Cannot connect to PostgreSQL"**

```bash
# PostgreSQL が起動しているか確認
sudo systemctl status postgresql

# 起動していない場合は開始
sudo systemctl start postgresql

# 接続テスト
psql -U postgres -d postgres -c "SELECT version();"
```

**パスワード不要でアクセス：**.pgpass を設定

```bash
# ~/.pgpass に以下を追記
localhost:5432:*:postgres:postgres_password

# 権限を 0600 に設定
chmod 0600 ~/.pgpass
```

**pg_vector インストール失敗**

```bash
# ログを確認
tail -100 /tmp/pgvector.log

# PostgreSQL 開発ファイルを確認
dpkg -l | grep postgresql-server-dev

# 再実装（開発ファイルの再インストール）
sudo apt-get install --reinstall postgresql-server-dev-15
bash scripts/pg_setup_native.sh --force
```

## 設定ファイルの更新

スクリプト完了後、`~/.devgear/settings.json` を更新：

```json
{
  "mem": {
    "sync": {
      "enabled": true,
      "interval_hours": 24,
      "postgres_url": "postgresql://devgear:PASSWORD@localhost:5432/devgear_mem",
      "origin_user": "your_username"
    }
  }
}
```

**重要:**

- `postgres_url` のパスワードは安全に管理してください
- `origin_user` は git の `user.name` と同じにすることを推奨
- `interval_hours` はデフォルト 24 時間（同期間隔）

## 同期の確認

セットアップ完了後、同期が正しく動作しているか確認：

```bash
python3 -m devgear.mem sync
```

**成功時の出力:**

```
[mem-sync] Connecting to PostgreSQL...
[mem-sync] Syncing session data...
[mem-sync] Sync completed successfully
```

## 注意事項

### Docker セットアップ

- コンテナは `restart: unless-stopped` で自動再起動される
- データは `devgear-postgres17-data` ボリュームに永続化
- デフォルトポート: `5432`

### ネイティブセットアップ

- スクリプトは `postgres` ユーザの権限が必要な操作を行う場合がある
- pg_vector コンパイルに 5-10 分かかる場合がある
- パスワードは自動生成され、スクリプト完了時に表示される
- 既存ユーザ・DB と競合する場合は `--force` で上書き

### 両方のセットアップ

- スキーマ（テーブル・インデックス・拡張）は `scripts/pg_setup.sql` で定義
- チーム間での同期には複数のユーザで同じ PostgreSQL に接続し、`origin_user` を分ける
- パスワードは git にコミットしないこと

## 関連ファイル

- `scripts/pg_setup.sh` - Docker セットアップスクリプト
- `scripts/pg_setup_native.sh` - ネイティブセットアップスクリプト
- `scripts/pg_setup.sql` - スキーマ定義（両スクリプトで使用）

## 参考資料

- [PostgreSQL 公式ドキュメント](https://www.postgresql.org/docs/)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
