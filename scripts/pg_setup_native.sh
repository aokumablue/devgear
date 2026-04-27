#!/usr/bin/env bash
# PostgreSQL ネイティブ環境セットアップ
# 既存の PostgreSQL にユーザ登録・DB作成・pg_vector インストール・スキーマ初期化を行う
#
# 使用方法:
#   bash pg_setup_native.sh [OPTIONS]
#   bash pg_setup_native.sh --user myuser --password mypass --db mydb

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SQL_FILE="${SCRIPT_DIR}/pg_setup.sql"

# デフォルト値
PG_USER="devgear"
PG_PASSWORD=""
PG_DB="devgear_mem"
PG_HOST="localhost"
PG_PORT="5432"
ORIGIN_USER=""
SQL_FILE="${DEFAULT_SQL_FILE}"
INSTALL_PGVECTOR=1
SKIP_SCHEMA=0
FORCE=0
CREDENTIALS_FILE=""

# ディストリビューション検出関数
detect_distro() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    echo "${ID}"
  elif [[ -f /etc/redhat-release ]]; then
    echo "rhel"
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macos"
  else
    echo "unknown"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  bash pg_setup_native.sh [OPTIONS]

Options:
  --user USER                PostgreSQL ユーザ名 (default: devgear)
  --password PASSWORD        ユーザのパスワード (default: auto-generate)
  --db DB_NAME              データベース名 (default: devgear_mem)
  --host HOST               PostgreSQL ホスト (default: localhost)
  --port PORT               PostgreSQL ポート (default: 5432)
  --origin-user USER        settings.json の origin_user (default: $(id -un))
  --sql-file PATH           SQL スクリプトパス (default: ./pg_setup.sql)
  --credentials-file PATH   認証情報を保存するファイル (default: ~/.devgear/pg_credentials.json)
  --no-install-pgvector     pg_vector インストールをスキップ
  --skip-schema             スキーマ初期化をスキップ
  --force                   既存ユーザ・DB を削除して再作成
  --help, -h               このヘルプを表示

Requirements:
  - PostgreSQL がインストール済み（バージョン 13 以上推奨）
  - psql がアクセス可能（通常、postgres ユーザで実行するか、.pgpass を設定）
  - sudo（pg_vector インストール時）
  - ビルド環境：gcc、make、git

Supported Operating Systems:
  - Ubuntu / Debian (apt)
  - RockyLinux / RHEL / CentOS / AlmaLinux (yum/dnf)
  - macOS (homebrew)

EOF
}

log() {
  printf '[pg-setup-native] %s\n' "$1"
}

fail() {
  printf '[pg-setup-native] Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command not found: $1"
  fi
}

generate_password() {
  openssl rand -hex 16
}

get_package_manager() {
  local distro="$1"
  case "${distro}" in
    ubuntu|debian)
      echo "apt"
      ;;
    rhel|rocky|centos|fedora|almalinux)
      if command -v dnf >/dev/null 2>&1; then
        echo "dnf"
      else
        echo "yum"
      fi
      ;;
    macos)
      echo "brew"
      ;;
    *)
      fail "Unsupported distribution: ${distro}. Please install required packages manually."
      ;;
  esac
}

install_package() {
  local package="$1"
  local pkg_mgr="$2"

  case "${pkg_mgr}" in
    apt)
      sudo apt-get update >/dev/null 2>&1
      sudo apt-get install -y "${package}" >/dev/null 2>&1
      ;;
    yum|dnf)
      sudo "${pkg_mgr}" install -y "${package}" >/dev/null 2>&1
      ;;
    brew)
      brew install "${package}" >/dev/null 2>&1
      ;;
  esac
}

check_psql_access() {
  local test_sql="SELECT 1;"
  if ! echo "${test_sql}" | psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres >/dev/null 2>&1; then
    fail "Cannot connect to PostgreSQL at ${PG_HOST}:${PG_PORT}. Ensure PostgreSQL is running and accessible."
  fi
}

install_pgvector() {
  log "Installing pg_vector..."

  # ディストリビューション検出
  local distro pkg_mgr
  distro="$(detect_distro)"
  pkg_mgr="$(get_package_manager "${distro}")"

  log "Detected: ${distro} (package manager: ${pkg_mgr})"

  # pg_vector の確認（既に存在するかチェック）
  if psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1; then
    log "pg_vector extension is already available"
    return 0
  fi

  # PostgreSQL 開発ファイルのインストール
  log "Installing PostgreSQL development files..."
  case "${distro}" in
    ubuntu|debian)
      local pg_version
      pg_version=$(psql -t -U postgres -d postgres -c "SELECT version_num / 10000;" 2>/dev/null || echo "15")
      install_package "postgresql-server-dev-${pg_version}" "${pkg_mgr}"
      ;;
    rhel|rocky|centos|almalinux|fedora)
      install_package "postgresql-devel" "${pkg_mgr}"
      ;;
    macos)
      # macOS では PostgreSQL がインストール済みと仮定
      log "Skipping postgresql-devel on macOS (assuming already installed)"
      ;;
  esac

  # Build tools のインストール
  if ! command -v gcc >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
    log "Installing build tools..."
    case "${distro}" in
      ubuntu|debian)
        install_package "build-essential" "${pkg_mgr}"
        ;;
      rhel|rocky|centos|almalinux|fedora)
        install_package "gcc" "${pkg_mgr}"
        install_package "make" "${pkg_mgr}"
        ;;
      macos)
        log "Please install Xcode Command Line Tools: xcode-select --install"
        fail "Xcode Command Line Tools required"
        ;;
    esac
  fi

  # git のインストール
  if ! command -v git >/dev/null 2>&1; then
    log "Installing git..."
    install_package "git" "${pkg_mgr}"
  fi

  log "Compiling and installing pg_vector from source..."
  local tmpdir
  tmpdir="$(mktemp -d)"
  trap "rm -rf ${tmpdir}" EXIT

  (
    cd "${tmpdir}"
    if ! git clone --branch v0.8.2 --depth 1 https://github.com/pgvector/pgvector.git; then
      fail "Failed to clone pg_vector repository"
    fi
    cd pgvector
    if ! make; then
      fail "Failed to compile pg_vector. Ensure PostgreSQL development files are installed."
    fi
    if ! sudo make install; then
      fail "Failed to install pg_vector. Check sudo permissions."
    fi
  )

  log "pg_vector installation completed"
}

user_exists() {
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -t -c "SELECT 1 FROM pg_user WHERE usename='$(echo "${PG_USER}" | sed "s/'/''/g")';" 2>/dev/null | grep -q 1
}

db_exists() {
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -t -c "SELECT 1 FROM pg_database WHERE datname='$(echo "${PG_DB}" | sed "s/'/''/g")';" 2>/dev/null | grep -q 1
}

drop_user_if_exists() {
  if user_exists; then
    log "Dropping existing user: ${PG_USER}"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -c "DROP USER IF EXISTS \"${PG_USER}\" CASCADE;" >/dev/null
  fi
}

drop_db_if_exists() {
  if db_exists; then
    log "Dropping existing database: ${PG_DB}"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -c "DROP DATABASE IF EXISTS \"${PG_DB}\" WITH (FORCE);" >/dev/null
  fi
}

create_user() {
  if user_exists; then
    if [[ "${FORCE}" != "1" ]]; then
      fail "User '${PG_USER}' already exists. Use --force to overwrite."
    fi
    drop_user_if_exists
  fi

  log "Creating PostgreSQL user: ${PG_USER}"
  local escaped_password="${PG_PASSWORD//\'/\'\'}"
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -c "CREATE USER \"${PG_USER}\" WITH PASSWORD '${escaped_password}' CREATEDB;" >/dev/null
  log "User created with password (store it safely)"
}

create_database() {
  if db_exists; then
    if [[ "${FORCE}" != "1" ]]; then
      fail "Database '${PG_DB}' already exists. Use --force to overwrite."
    fi
    drop_db_if_exists
  fi

  log "Creating database: ${PG_DB}"
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d postgres -c "CREATE DATABASE \"${PG_DB}\" OWNER \"${PG_USER}\";" >/dev/null
  log "Database created"
}

enable_extensions() {
  log "Enabling PostgreSQL extensions..."

  # pg_trgm
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d "${PG_DB}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null
  log "Extension pg_trgm enabled"

  # vector (pg_vector)
  if psql -h "${PG_HOST}" -p "${PG_PORT}" -U postgres -d "${PG_DB}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1; then
    log "Extension vector (pg_vector) enabled"
  else
    log "Warning: vector extension not available. Ensure pg_vector is installed."
  fi
}

load_schema() {
  if [[ "${SKIP_SCHEMA}" == "1" ]]; then
    log "Skipping schema initialization"
    return 0
  fi

  if [[ ! -f "${SQL_FILE}" ]]; then
    fail "SQL file not found: ${SQL_FILE}"
  fi

  log "Loading schema from: ${SQL_FILE}"
  psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -v ON_ERROR_STOP=1 -f "${SQL_FILE}" >/dev/null
  log "Schema loaded successfully"
}

print_connection_info() {
  local connection_string_masked="postgresql://${PG_USER}:***@${PG_HOST}:${PG_PORT}/${PG_DB}"
  local connection_string_full="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"
  local origin_user="${ORIGIN_USER:-$(id -un)}"

  printf '\n'
  log "Setup completed successfully!"
  log "Connection URL (masked): ${connection_string_masked}"
  printf '\n'
  printf '=== PASSWORD ===\n'
  printf '%s\n' "${PG_PASSWORD}"
  printf '================\n'
  printf '\n'
  printf 'Next steps:\n'
  printf '1. Store the password securely (see above)\n'
  printf '2. Edit ~/.devgear/settings.json:\n'
  printf '   {\n'
  printf '     "mem": {\n'
  printf '       "sync": {\n'
  printf '         "enabled": true,\n'
  printf '         "interval_hours": 24,\n'
  printf '         "postgres_url": "%s",\n' "${connection_string_full}"
  printf '         "origin_user": "%s"\n' "${origin_user}"
  printf '       }\n'
  printf '     }\n'
  printf '   }\n'
  printf '3. Run: python3 -m devgear.mem sync\n'
  printf '\n'
}

save_credentials() {
  if [[ -z "${CREDENTIALS_FILE}" ]]; then
    CREDENTIALS_FILE="${HOME}/.devgear/pg_credentials.json"
  fi

  local credentials_dir
  credentials_dir="$(dirname "${CREDENTIALS_FILE}")"

  if [[ ! -d "${credentials_dir}" ]]; then
    if ! mkdir -p "${credentials_dir}"; then
      log "Warning: Failed to create credentials directory: ${credentials_dir}"
      return 1
    fi
  fi

  cat > "${CREDENTIALS_FILE}" <<EOF
{
  "user": "${PG_USER}",
  "password": "${PG_PASSWORD}",
  "host": "${PG_HOST}",
  "port": ${PG_PORT},
  "database": "${PG_DB}",
  "connection_url": "postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"
}
EOF

  chmod 0600 "${CREDENTIALS_FILE}"
  log "Credentials saved: ${CREDENTIALS_FILE}"
  log "File permissions: 0600 (owner read-write only)"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user)
        [[ $# -ge 2 ]] || fail "--user requires a value"
        PG_USER="$2"
        shift 2
        ;;
      --password)
        [[ $# -ge 2 ]] || fail "--password requires a value"
        PG_PASSWORD="$2"
        shift 2
        ;;
      --db)
        [[ $# -ge 2 ]] || fail "--db requires a value"
        PG_DB="$2"
        shift 2
        ;;
      --host)
        [[ $# -ge 2 ]] || fail "--host requires a value"
        PG_HOST="$2"
        shift 2
        ;;
      --port)
        [[ $# -ge 2 ]] || fail "--port requires a value"
        PG_PORT="$2"
        shift 2
        ;;
      --origin-user)
        [[ $# -ge 2 ]] || fail "--origin-user requires a value"
        ORIGIN_USER="$2"
        shift 2
        ;;
      --sql-file)
        [[ $# -ge 2 ]] || fail "--sql-file requires a value"
        SQL_FILE="$2"
        shift 2
        ;;
      --credentials-file)
        [[ $# -ge 2 ]] || fail "--credentials-file requires a value"
        CREDENTIALS_FILE="$2"
        shift 2
        ;;
      --no-install-pgvector)
        INSTALL_PGVECTOR=0
        shift
        ;;
      --skip-schema)
        SKIP_SCHEMA=1
        shift
        ;;
      --force)
        FORCE=1
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "Unknown option: $1"
        ;;
    esac
  done
}

main() {
  parse_args "$@"

  # パスワードの生成
  if [[ -z "${PG_PASSWORD}" ]]; then
    PG_PASSWORD="$(generate_password)"
  fi

  log "PostgreSQL Native Setup"
  log "User: ${PG_USER}, DB: ${PG_DB}, Host: ${PG_HOST}:${PG_PORT}"
  printf '\n'

  require_command psql
  require_command openssl

  # PostgreSQL への接続確認
  check_psql_access

  # pg_vector インストール
  if [[ "${INSTALL_PGVECTOR}" == "1" ]]; then
    install_pgvector
    printf '\n'
  fi

  # ユーザ・DB 作成
  create_user
  create_database
  printf '\n'

  # 拡張有効化
  enable_extensions
  printf '\n'

  # スキーマ読み込み
  load_schema
  printf '\n'

  # 認証情報をファイルに保存
  save_credentials
  printf '\n'

  # 接続情報表示
  print_connection_info
}

main "$@"
