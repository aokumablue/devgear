#!/usr/bin/env bash
# install.sh
# devgear の Python 依存を repo-local の .venv に導入し、初回の ~/.devgear/settings.json を作成する。
# Ubuntu と macOS に対応。
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

run_quietly() {
  local output_file
  output_file="$(mktemp)"
  if "$@" >"${output_file}" 2>&1; then
    rm -f "${output_file}"
    return 0
  else
    local status=$?
    cat "${output_file}" >&2
    rm -f "${output_file}"
    return "${status}"
  fi
}

pip_install_quiet() {
  run_quietly "${VENV_PYTHON}" -m pip install --no-input --quiet --disable-pip-version-check "$@"
}

# Python 3.12+ のバイナリを探す
find_python3() {
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      local ver
      ver="$("${candidate}" -c 'import sys; print(sys.version_info.major * 100 + sys.version_info.minor)' 2>/dev/null || echo 0)"
      if [[ "${ver}" -ge 312 ]]; then
        echo "${candidate}"
        return 0
      fi
    fi
  done
  return 1
}

# python3 -m venv が使えるか確認し、なければ OS パッケージでインストールする
ensure_venv_module() {
  if "${PYTHON3}" -m venv --help >/dev/null 2>&1; then
    return
  fi

  echo "[devgear] python3-venv not found. Attempting to install..."

  local py_ver
  py_ver="$("${PYTHON3}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

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
    brew install "python@${py_ver}" || brew install python3
  else
    echo "Error: python3-venv が見つからず、自動インストールにも失敗しました。" >&2
    echo "       手動で python3-venv をインストールしてから再実行してください。" >&2
    exit 1
  fi

  if ! "${PYTHON3}" -m venv --help >/dev/null 2>&1; then
    echo "Error: python3-venv のインストール後も venv が使えません。" >&2
    exit 1
  fi
  echo "[devgear] python3-venv インストール完了"
}

# 既存 venv に旧依存（ONNX 移行前のパッケージ）が残っていれば削除して再作成させる
check_and_reset_venv() {
  # 壊れたシンボリックリンク（自己参照含む）は即削除
  if [[ -L "${VENV_DIR}" ]]; then
    echo "[devgear] Removing stale .venv symlink at ${VENV_DIR}"
    rm -f "${VENV_DIR}"
    return 0
  fi
  [[ ! -x "${VENV_PYTHON}" ]] && return 0
  # ONNX 移行前の重量級パッケージが残っている旧 venv を再構築
  local has_legacy
  has_legacy="$("${VENV_PYTHON}" -c "
from importlib.metadata import packages_distributions, PackageNotFoundError
pkgs = packages_distributions()
legacy = any(p in pkgs for p in ('sentence_transformers', 'torch', 'transformers'))
print('1' if legacy else '0')
" 2>/dev/null || echo 0)"
  if [[ "${has_legacy}" == "1" ]]; then
    echo "[devgear] 旧依存 (sentence-transformers / PyTorch 系) を検出しました。venv を再構築します..."
    rm -rf "${VENV_DIR}"
  fi
}

ensure_virtualenv() {
  if [[ -x "${VENV_PYTHON}" ]]; then
    return
  fi

  ensure_venv_module

  echo "[devgear] Creating Python virtual environment at ${VENV_DIR}"
  "${PYTHON3}" -m venv "${VENV_DIR}"
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
  "${PYTHON3}" - "${SETTINGS_TEMPLATE_PATH}" "${SETTINGS_PATH}" <<'PY'
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
  check_and_reset_venv
  ensure_virtualenv

  if ! "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    echo "[devgear] Bootstrapping pip via ensurepip"
    run_quietly "${VENV_PYTHON}" -m ensurepip --upgrade
  fi

  echo "[devgear] Installing Python package dependencies into ${VENV_DIR}"
  pip_install_quiet --upgrade pip wheel

  # torch / sentence-transformers / transformers / huggingface_hub は ONNX 化により不要
  # CVE-2025-32434（torch pickle RCE）攻撃面を根絶するため完全に排除する
  pip_install_quiet \
    'onnxruntime>=1.18' \
    'tokenizers>=0.20' \
    'pyyaml>=6.0'

  # --no-deps: pyproject.toml の依存解決をスキップして上で固定したバージョンを維持する
  pip_install_quiet --no-deps -e "${REPO_ROOT}"
  # psycopg: PostgreSQL 同期機能を使う場合のみ必要（optional）
  pip_install_quiet 'psycopg[binary]'

  # ONNX モデルを sparse-checkout で取得し ~/.devgear/models/ に統合する
  # 統合済み model.onnx が存在して SHA が一致する場合はスキップする
  local sources_json="${SCRIPT_DIR}/model_sources.json"
  local model_target="${HOME}/.devgear/models/ruri-v3-310m"
  if [[ -f "${sources_json}" ]]; then
    echo "[devgear] ONNX モデルを統合しています: ${model_target}"
    "${VENV_PYTHON}" -m devgear.mem.model_assembler \
      --sources "${sources_json}" \
      --target "${model_target}"
  else
    echo "[devgear] Warning: ${sources_json} が見つかりません。モデル統合をスキップします。" >&2
    echo "[devgear] scripts/build_onnx_model.sh を実行して model_sources.json を生成してください。" >&2
  fi

  # 既存 settings.json のセキュリティ移行（パスワード分離・sslmode 強制）
  if [[ -f "${SETTINGS_PATH}" ]]; then
    echo "[devgear] Migrating existing settings.json to hardened format"
    "${VENV_PYTHON}" -m devgear.mem migrate-settings || echo "[devgear] Note: settings migration skipped."
  fi
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

if ! PYTHON3="$(find_python3)"; then
  echo "Error: Python 3.12+ is required but not found." >&2
  echo "       Install python3.12 (e.g. brew install python@3.12) and retry." >&2
  exit 1
fi
echo "[devgear] Using ${PYTHON3} ($("${PYTHON3}" --version))"

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required." >&2
  exit 1
fi

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
    [[ -L "$org_dir" ]] && continue
    [[ -d "$org_dir" ]] || continue
    for ver_dir in "$org_dir"/*; do
      [[ -L "$ver_dir" ]] && continue
      [[ -d "$ver_dir" ]] || continue
      local_venv="${ver_dir}/.venv"
      # VENV_DIR 自身（実行ディレクトリが既にキャッシュ内の場合）はスキップ
      if [[ "${local_venv}" == "${VENV_DIR}" ]]; then
        echo "[devgear] Claude cache .venv is the install target itself, skipping symlink"
      elif [[ -L "${local_venv}" && "$(readlink "${local_venv}")" == "${VENV_DIR}" ]]; then
        echo "[devgear] Claude cache .venv already linked: ${local_venv}"
      else
        echo "[devgear] Symlinking .venv into Claude cache: ${local_venv} -> ${VENV_DIR}"
        rm -rf "${local_venv}"
        ln -s "${VENV_DIR}" "${local_venv}"
      fi
    done
  done
fi

# Copilot キャッシュ: ~/.copilot/installed-plugins/devgear/devgear/
# launcher.py は src/devgear/launcher.py なので parents[2] = devgear/ が REPO_ROOT になる。
COPILOT_PLUGIN_DIR="${HOME}/.copilot/installed-plugins/devgear/devgear"
if [[ -d "${COPILOT_PLUGIN_DIR}" ]]; then
  copilot_venv="${COPILOT_PLUGIN_DIR}/.venv"
  if [[ "${copilot_venv}" == "${VENV_DIR}" ]]; then
    echo "[devgear] Copilot cache .venv is the install target itself, skipping symlink"
  elif [[ -L "${copilot_venv}" && "$(readlink "${copilot_venv}")" == "${VENV_DIR}" ]]; then
    echo "[devgear] Copilot cache .venv already linked: ${copilot_venv}"
  else
    echo "[devgear] Symlinking .venv into Copilot cache: ${copilot_venv} -> ${VENV_DIR}"
    rm -rf "${copilot_venv}"
    ln -s "${VENV_DIR}" "${copilot_venv}"
  fi
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
