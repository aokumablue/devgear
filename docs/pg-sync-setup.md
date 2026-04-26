# PostgreSQL チーム同期セットアップガイド

devgear の永続メモリ (`mem`) をチーム間で共有するための PostgreSQL 同期機能のセットアップガイドです。

## 概要

この機能により、各開発者のローカル SQLite データベースに蓄積されたメモリを、共有 PostgreSQL サーバーにバッチ同期できます。

**特徴:**

- **定期バッチ同期**: デフォルト 7 日間隔（設定変更可能）
- **片方向同期**: ローカル → リモートのみ
- **UUID ベース**: 複数ユーザーからの同期でも ID 重複が発生しない
- **冪等性**: 同じデータを何度同期しても重複しない

## 前提条件

- PostgreSQL 17 以上
- `pg_trgm` 拡張（FTS 用、PostgreSQL に標準搭載）
- `pgvector` 拡張（`pg_setup.sql` を使う場合は必要。`pg_setup.sh docker17` では自動で入る）
- Python パッケージ `psycopg[binary]`

## 1. PostgreSQL セットアップ

共有サーバーで PostgreSQL 17 を Docker で起動する場合は、`pg_setup.sh` と `pg_setup.sql` を任意のフォルダにコピーして、そのフォルダで `bash pg_setup.sh docker17` を実行できます。実行すると `${workspace}/.env` が自動生成され、`POSTGRES_PASSWORD` にはランダムな値が入り、ファイル権限は `0600` になります。`--force` を付けると既存の Docker volume を削除して PostgreSQL を初期状態から再作成し、`pg_setup.sql` を再投入します。あわせて `default_toast_compression=lz4` を有効にして、TOAST 対象の大きい列を圧縮します。

`install.sh` を先に実行すると、`~/.devgear/settings.json` に `project` / `hooks` / `skills` / `commands` / `mem` のフルデフォルトが入るので、その後の同期設定の編集がしやすくなります。

### データベースとユーザーの作成

```sql
-- データベース作成
CREATE DATABASE devgear_mem;

-- ユーザー作成（本番環境では適切なパスワードを設定）
CREATE USER devgear WITH PASSWORD 'your-secure-password';
GRANT ALL PRIVILEGES ON DATABASE devgear_mem TO devgear;
```

### テーブル作成

提供されているスクリプトを使用:

```bash
# 配置したフォルダから
psql -h your-db-host -U devgear -d devgear_mem -f pg_setup.sql
```

または、シェルスクリプト経由:

```bash
# 配置したフォルダで
MEM_PG_URL="postgresql://devgear:password@host:5432/devgear_mem" \
  bash pg_setup.sh apply
```

### 作成されるテーブル

| テーブル | 用途 |
|---------|------|
| `memory_chunks` | メモリチャンク（コンテキスト） |
| `sessions` | セッション情報（git ブランチ・コミットハッシュ含む） |
| `instincts` | インスティンクト（学習した習慣） |
| `adrs` | Architecture Decision Records |
| `event_logs` | イベントログ（observations, skill-runs, costs） |
| `interaction_logs` | ユーザー指示と AI 応答のペア記録（スキル自動生成の原料） |
| `project_profiles` | プロジェクトの技術スタック情報（instinct の scope 判定に使用） |
| `mem_item_runs` | スキル活用記録（ベストエフォート観測） |
| `memory_chunks_vec` | ベクトル検索用（pgvector 拡張が必要） |

## 2. クライアント設定

### settings.json の設定

`install.sh` で作成された各開発者のローカル設定ファイル (`~/.devgear/settings.json`) には同期設定の既定値も入っています。チーム同期を有効にする場合は `mem.sync` を編集してください:

```json
{
  "mem": {
    "sync": {
      "enabled": true,
      "interval_hours": 24,
      "postgres_url": "postgresql://user:password@host:5432/devgear_mem?sslmode=require",
      "origin_user": "your-username"
    }
  }
}
```

`pg_setup.sh docker17` はこのファイルを更新しないため、接続 URL とユーザー名を手動で追記してください。

### 設定項目

| 項目 | 必須 | デフォルト | 説明 |
|------|------|----------|------|
| `enabled` | - | `false` | 同期を有効化 |
| `interval_hours` | - | `24` | 同期間隔（時間） |
| `postgres_url` | ✓ | - | PostgreSQL 接続 URL |
| `origin_user` | ✓ | - | ユーザー識別子（チーム内でユニーク） |

### セキュリティに関する注意

**接続 URL にパスワードを直接書く場合:**

```json
"postgres_url": "postgresql://user:password@host:5432/db"
```

**環境変数を使う場合（推奨）:**

1. 環境変数を設定:

```bash
export MEM_PG_URL="postgresql://user:password@host:5432/db"
```

1. settings.json では空文字列を設定し、コード側で環境変数を参照

### SSL 接続

本番環境では SSL を有効にすることを推奨:

```
postgresql://user:pass@host:5432/db?sslmode=require
```

## 3. 依存パッケージのインストール

同期機能を使う場合、`psycopg` が必要です:

```bash
pip install psycopg[binary]
```

## 4. 使い方

### 手動同期

```bash
# 同期を実行
echo '{}' | python -m devgear.mem sync

# ドライラン（実際の同期は行わない）
echo '{"dry_run": true}' | python -m devgear.mem sync
```

### 自動同期

`SessionEnd` フックで自動的に同期間隔がチェックされ、条件を満たせば同期が実行されます。

手動でチェック・実行する場合:

```bash
python -m devgear.mem sync-check
```

### 外部データのインポート

ADR やインスティンクトなどの外部データを mem に取り込む:

```bash
# すべてのデータをインポート
echo '{"repo_root": "/path/to/repo"}' | python -m devgear.mem import

# 特定のタイプのみ
echo '{"types": ["instincts"], "repo_root": "/path/to/repo"}' | python -m devgear.mem import
```

## 5. トラブルシューティング

### 接続エラー

```
PostgreSQL への接続に失敗しました
```

- URL が正しいか確認
- ネットワーク接続を確認
- PostgreSQL サーバーが起動しているか確認
- ファイアウォール設定を確認

### 同期がスキップされる

- `sync.enabled` が `true` か確認
- `origin_user` が設定されているか確認
- `interval_hours` の間隔が経過しているか確認

## 6. 運用ガイドライン

### バックアップ

PostgreSQL サーバーの定期バックアップを設定:

```bash
pg_dump -h host -U user devgear_mem > backup_$(date +%Y%m%d).sql
```

### 監視項目

- ディスク使用量
- 同期エラーのログ
- テーブルサイズの増加率

### データ保持ポリシー

古いイベントログの削除例:

```sql
DELETE FROM event_logs
WHERE created_at_epoch < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
```
