#!/usr/bin/env bash
# install.sh
# devgear の Python 依存を repo-local の .venv に導入し、初回の ~/.devgear/settings.json を作成する。
# 使い方:
#   bash install.sh
#   bash install.sh --repo-root /path/to/repo
#   DEVGEAR_INSTALL_SKIP_PYTHON=1 bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
SKIP_PYTHON="${DEVGEAR_INSTALL_SKIP_PYTHON:-0}"
INSTALL_DEV="${DEVGEAR_INSTALL_DEV:-0}"
# --dev を除く引数を install-dev.sh へ転送するために正規化して保持する
NORMALIZED_ARGS=()

usage() {
  cat <<'EOF'
Usage: bash scripts/install.sh [options]

Options:
  --repo-root PATH   Repository root (default: script directory)
  --skip-python      Skip Python package installation and venv setup
  --dev              Run the developer installer instead of the user installer
  --help             Show this help

Environment:
  DEVGEAR_INSTALL_SKIP_PYTHON=1  Skip Python package installation and venv setup
  DEVGEAR_INSTALL_DEV=1          Run the developer installer instead of the user installer
EOF
}

# python3 -m venv が使えるか確認し、なければ OS パッケージでインストールする
ensure_venv_module() {
  if python3 -m venv --help >/dev/null 2>&1; then
    return
  fi

  echo "[devgear] python3-venv not found. Attempting to install..."

  local py_ver
  py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y "python${py_ver}-venv" \
      || sudo apt-get install -y python3-venv
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "python${py_ver}-devel" python3-virtualenv \
      || sudo dnf install -y python3-virtualenv
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3-virtualenv
  elif command -v brew >/dev/null 2>&1; then
    # macOS: venv は Python 本体に含まれるため再インストールで解決
    brew install "python@${py_ver}" || brew install python3
  else
    echo "Error: python3-venv が見つからず、自動インストールにも失敗しました。" >&2
    echo "       手動で python3-venv をインストールしてから再実行してください。" >&2
    exit 1
  fi

  if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "Error: python3-venv のインストール後も venv が使えません。" >&2
    exit 1
  fi
  echo "[devgear] python3-venv インストール完了"
}

ensure_virtualenv() {
  if [[ -x "${VENV_PYTHON}" ]]; then
    return
  fi

  ensure_venv_module

  echo "[devgear] Creating Python virtual environment at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Error: failed to create virtual environment at ${VENV_DIR}." >&2
    exit 1
  fi
}

ensure_settings_json() {
  if [[ -e "${SETTINGS_DIR}" && ! -d "${SETTINGS_DIR}" ]]; then
    echo "Error: ${SETTINGS_DIR} exists and is not a directory." >&2
    exit 1
  fi

  if [[ -e "${SETTINGS_PATH}" ]]; then
    if [[ -f "${SETTINGS_PATH}" ]]; then
      echo "[devgear] Existing settings file found at ${SETTINGS_PATH}"
      return
    fi
    echo "Error: ${SETTINGS_PATH} exists and is not a regular file." >&2
    exit 1
  fi

  if [[ ! -f "${SETTINGS_TEMPLATE_PATH}" ]]; then
    echo "Error: settings template not found at ${SETTINGS_TEMPLATE_PATH}." >&2
    exit 1
  fi

  mkdir -p "${SETTINGS_DIR}"
  # テンプレートをそのまま展開する（mem は sync.enabled / sync.postgres_url のみ保持）
  python3 - "${SETTINGS_TEMPLATE_PATH}" "${SETTINGS_PATH}" <<'PY'
from pathlib import Path
import json
import sys

template_path = Path(sys.argv[1])
settings_path = Path(sys.argv[2])

data = json.loads(template_path.read_text(encoding="utf-8"))
settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
settings_path.chmod(0o600)
PY
  echo "[devgear] Wrote full default settings file: ${SETTINGS_PATH}"
}

install_user_python() {
  ensure_virtualenv

  if ! "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    echo "[devgear] Bootstrapping pip via ensurepip"
    "${VENV_PYTHON}" -m ensurepip --upgrade
  fi

  echo "[devgear] Installing Python package dependencies into ${VENV_DIR}"
  "${VENV_PYTHON}" -m pip install --upgrade pip wheel
  # sentence-transformers の依存解決より先に CPU-only torch を固定する
  "${VENV_PYTHON}" -m pip install 'torch>=2.0' --index-url https://download.pytorch.org/whl/cpu
  "${VENV_PYTHON}" -m pip install -e "${REPO_ROOT}"
  "${VENV_PYTHON}" -m pip install 'psycopg[binary]' 'psycopg-pool'

  echo "[devgear] Prefetching embedding model cache"
  "${VENV_PYTHON}" - <<'PY'
from devgear.mem.embedding import prefetch_model

prefetch_model()
PY
}

# ---- 引数パース ----

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      NORMALIZED_ARGS+=("--repo-root" "$2")
      shift 2
      ;;
    --skip-python)
      SKIP_PYTHON=1
      NORMALIZED_ARGS+=("--skip-python")
      shift
      ;;
    --dev)
      INSTALL_DEV=1
      # --dev は install-dev.sh へ転送しない（再帰呼び出し防止）
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# ---- 変数確定（引数パース後に設定） ----

VENV_DIR="${REPO_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python3"
: "${HOME:?Error: HOME must be set.}"
SETTINGS_DIR="${HOME}/.devgear"
SETTINGS_PATH="${SETTINGS_DIR}/settings.json"
SETTINGS_TEMPLATE_PATH="${REPO_ROOT}/settings.json"

# ---- 前提条件チェック ----

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required." >&2
  exit 1
fi

python3 - <<'PY'
import sys

if sys.version_info < (3, 12):
  raise SystemExit("Error: Python 3.12+ is required.")
PY

# ---- メイン処理 ----

if [[ "${INSTALL_DEV}" == "1" ]]; then
  exec "${SCRIPT_DIR}/install-dev.sh" "${NORMALIZED_ARGS[@]}"
fi

ensure_settings_json

if [[ "${SKIP_PYTHON}" != "1" ]]; then
  install_user_python
fi

# Claude Code キャッシュ: ~/.claude/plugins/cache/devgear/<org>/<version>/
# launcher.py は src/devgear/launcher.py なので parents[2] = <version>/ が REPO_ROOT になる。
# よって .venv は <version>/.venv に置く必要がある。
if [[ -d "${HOME}/.claude/plugins/cache/devgear" ]]; then
  for org_dir in "${HOME}/.claude/plugins/cache/devgear"/*; do
    [[ -d "$org_dir" ]] || continue
    for ver_dir in "$org_dir"/*; do
      [[ -d "$ver_dir" ]] || continue
      if [[ ! -e "$ver_dir/.venv" ]]; then
        echo "[devgear] Symlinking .venv into Claude cache: $ver_dir/.venv -> ${VENV_DIR}"
        ln -sf "${VENV_DIR}" "$ver_dir/.venv"
      fi
    done
  done
fi

# Copilot キャッシュ: ~/.copilot/installed-plugins/devgear/devgear/
# launcher.py は src/devgear/launcher.py なので parents[2] = devgear/ が REPO_ROOT になる。
COPILOT_PLUGIN_DIR="${HOME}/.copilot/installed-plugins/devgear/devgear"
if [[ -d "${COPILOT_PLUGIN_DIR}" && ! -e "${COPILOT_PLUGIN_DIR}/.venv" ]]; then
  echo "[devgear] Symlinking .venv into Copilot cache: ${COPILOT_PLUGIN_DIR}/.venv -> ${VENV_DIR}"
  ln -sf "${VENV_DIR}" "${COPILOT_PLUGIN_DIR}/.venv"
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "[devgear] Note: PostgreSQL client (psql) is required for mem sync features." >&2
fi

# ~/.devgear/mem.db スキーマを初期化する（べき等: 既存DBは変更しない）
if [[ "${SKIP_PYTHON}" != "1" ]]; then
  echo "[devgear] Initializing mem database at ${SETTINGS_DIR}/mem.db"
  "${VENV_PYTHON}" -m devgear.mem setup
fi

echo "[devgear] OK"
