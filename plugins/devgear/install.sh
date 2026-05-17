#!/usr/bin/env bash
# install.sh
# devgear の Python 依存を repo-local の .venv に導入し、初回の ~/.devgear/settings.json を作成する。
# Ubuntu と macOS に対応。
# 使い方:
#   bash install.sh
#   bash install.sh --repo-root /path/to/repo
#   DEVGEAR_INSTALL_SKIP_PYTHON=1 bash install.sh
#   DEVGEAR_INSTALL_ASSUME_YES=1 bash install.sh  # sudo パッケージインストールを自動許可

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
SKIP_PYTHON="${DEVGEAR_INSTALL_SKIP_PYTHON:-0}"
INSTALL_DEV="${DEVGEAR_INSTALL_DEV:-0}"
# sudo インストールの明示オプトイン（DEVGEAR_INSTALL_ASSUME_YES=1 または --assume-yes）
ASSUME_YES="${DEVGEAR_INSTALL_ASSUME_YES:-0}"
# --dev を除く引数を install-dev.sh へ転送するために正規化して保持する
NORMALIZED_ARGS=()

usage() {
  cat <<'EOF'
Usage: bash plugins/devgear/install.sh [options]

Options:
  --repo-root PATH   Repository root (default: script directory)
  --skip-python      Skip Python package installation and venv setup
  --dev              Run the developer installer instead of the user installer
  --assume-yes       Allow sudo package installation without confirmation
  --help             Show this help

Environment:
  DEVGEAR_INSTALL_SKIP_PYTHON=1  Skip Python package installation and venv setup
  DEVGEAR_INSTALL_DEV=1          Run the developer installer instead of the user installer
  DEVGEAR_INSTALL_ASSUME_YES=1   Allow sudo package installation without confirmation
EOF
}

run_quietly() {
  local output_file
  output_file="$(mktemp)"
  local status=0
  if "$@" >"${output_file}" 2>&1; then
    rm -f "${output_file}"
    return 0
  else
    status=$?
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

  # sudo インストールに明示的な許可が必要
  if [[ "${ASSUME_YES}" != "1" ]]; then
    echo "[devgear] sudo を使って python3-venv をインストールします。" >&2
    echo "[devgear] 許可するには DEVGEAR_INSTALL_ASSUME_YES=1 を設定するか --assume-yes を指定してください。" >&2
    exit 1
  fi

  local py_ver
  py_ver="$("${PYTHON3}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

  if command -v apt-get >/dev/null 2>&1; then
    echo "[devgear] sudo apt-get install python${py_ver}-venv を実行します"
    sudo apt-get update -qq
    sudo apt-get install -y "python${py_ver}-venv" \
      || sudo apt-get install -y python3-venv
  elif command -v dnf >/dev/null 2>&1; then
    echo "[devgear] sudo dnf install python${py_ver}-devel python3-virtualenv を実行します"
    sudo dnf install -y "python${py_ver}-devel" python3-virtualenv \
      || sudo dnf install -y python3-virtualenv
  elif command -v yum >/dev/null 2>&1; then
    echo "[devgear] sudo yum install python3-virtualenv を実行します"
    sudo yum install -y python3-virtualenv
  elif command -v brew >/dev/null 2>&1; then
    echo "[devgear] brew install python@${py_ver} を実行します"
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

# 既存 venv の stale symlink を削除する
check_and_reset_venv() {
  # 壊れたシンボリックリンク（自己参照含む）は即削除
  if [[ -L "${VENV_DIR}" ]]; then
    echo "[devgear] Removing stale .venv symlink at ${VENV_DIR}"
    rm -f -- "${VENV_DIR}"
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

  # 信頼鍵ストアを初期化する（DEVGEAR_TRUSTED_KEY_FILE が設定されている場合のみ import）
  local trust_dir="${SETTINGS_DIR}/trust"
  mkdir -p "${trust_dir}"
  chmod 0700 "${trust_dir}"
  if [[ -n "${DEVGEAR_TRUSTED_KEY_FILE:-}" && -f "${DEVGEAR_TRUSTED_KEY_FILE}" ]]; then
    local gnupg_dir="${trust_dir}/gnupg"
    mkdir -p "${gnupg_dir}"
    chmod 0700 "${gnupg_dir}"
    cp -- "${DEVGEAR_TRUSTED_KEY_FILE}" "${trust_dir}/maintainer.asc"
    chmod 0600 "${trust_dir}/maintainer.asc"
    GNUPGHOME="${gnupg_dir}" gpg --import "${trust_dir}/maintainer.asc" 2>/dev/null || true
    echo "[devgear] 信頼鍵を import しました: ${trust_dir}/gnupg"
  fi

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

  # ハッシュロックで PyPI レジストリ側改ざんを検知する（LS-1）。
  # 再生成: pip-compile --generate-hashes plugins/devgear/requirements.in -o plugins/devgear/requirements.txt
  run_quietly "${VENV_PYTHON}" -m pip install --no-input --quiet --disable-pip-version-check \
    --require-hashes -r "${SCRIPT_DIR}/requirements.txt"

  # --no-deps: pyproject.toml の依存解決をスキップして上で固定したバージョンを維持する
  # editable install は --require-hashes と排他のため別途実行する
  pip_install_quiet --no-deps -e "${REPO_ROOT}"

  # ONNX モデルが未生成の場合は HuggingFace から自前ビルドする（model.onnx 存在時はスキップ）
  # shellcheck source=../../scripts/_build_onnx_lib.sh
  source "${SCRIPT_DIR}/../../scripts/_build_onnx_lib.sh"
  local model_target="${HOME}/.devgear/models"
  build_onnx_if_missing "${REPO_ROOT}" "${model_target}" "fp16"

  # 既存 settings.json のセキュリティ移行（パスワード分離・sslmode 強制）
  if [[ -f "${SETTINGS_PATH}" ]]; then
    echo "[devgear] Migrating existing settings.json to hardened format"
    "${VENV_PYTHON}" -m devgear.mem migrate-settings || echo "[devgear] Note: settings migration skipped."
  fi
}

# Claude Code キャッシュに .venv シンボリックリンクを張る
# TOCTOU 対策: 対象が devgear venv (pyvenv.cfg 存在) ならスキップ。symlink / 不存在のみ操作する。
update_claude_cache_symlinks() {
  [[ -d "${HOME}/.claude/plugins/cache/devgear" ]] || return 0

  for org_dir in "${HOME}/.claude/plugins/cache/devgear"/*; do
    [[ -L "${org_dir}" ]] && continue
    [[ -d "${org_dir}" ]] || continue
    for ver_dir in "${org_dir}"/*; do
      [[ -L "${ver_dir}" ]] && continue
      [[ -d "${ver_dir}" ]] || continue
      local target_venv="${ver_dir}/.venv"
      # VENV_DIR 自身はスキップ
      if [[ "${target_venv}" == "${VENV_DIR}" ]]; then
        echo "[devgear] Claude cache .venv is the install target itself, skipping symlink"
        continue
      fi
      # 既に正しいリンクが張られている場合はスキップ
      if [[ -L "${target_venv}" && "$(readlink "${target_venv}")" == "${VENV_DIR}" ]]; then
        echo "[devgear] Claude cache .venv already linked: ${target_venv}"
        continue
      fi
      # 実体 venv（pyvenv.cfg が存在）は上書きしない（TOCTOU 保護）
      if [[ -e "${target_venv}/pyvenv.cfg" ]]; then
        echo "[devgear] Warning: ${target_venv} は実体 venv のためスキップします" >&2
        continue
      fi
      # symlink または不存在のみ操作（それ以外はスキップ）
      if [[ ! -L "${target_venv}" && -e "${target_venv}" ]]; then
        echo "[devgear] Warning: ${target_venv} は予期しないファイル種別のためスキップします" >&2
        continue
      fi
      echo "[devgear] Symlinking .venv into Claude cache: ${target_venv} -> ${VENV_DIR}"
      rm -- "${target_venv}" 2>/dev/null || true
      ln -sfn -- "${VENV_DIR}" "${target_venv}"
    done
  done
}

# Copilot キャッシュに .venv シンボリックリンクを張る
# TOCTOU 対策: update_claude_cache_symlinks と同じ保護を適用する。
update_copilot_cache_symlink() {
  local copilot_plugin_dir="${HOME}/.copilot/installed-plugins/devgear/devgear"
  [[ -d "${copilot_plugin_dir}" ]] || return 0

  local target_venv="${copilot_plugin_dir}/.venv"
  if [[ "${target_venv}" == "${VENV_DIR}" ]]; then
    echo "[devgear] Copilot cache .venv is the install target itself, skipping symlink"
    return 0
  fi
  if [[ -L "${target_venv}" && "$(readlink "${target_venv}")" == "${VENV_DIR}" ]]; then
    echo "[devgear] Copilot cache .venv already linked: ${target_venv}"
    return 0
  fi
  # 実体 venv は上書きしない
  if [[ -e "${target_venv}/pyvenv.cfg" ]]; then
    echo "[devgear] Warning: ${target_venv} は実体 venv のためスキップします" >&2
    return 0
  fi
  if [[ ! -L "${target_venv}" && -e "${target_venv}" ]]; then
    echo "[devgear] Warning: ${target_venv} は予期しないファイル種別のためスキップします" >&2
    return 0
  fi
  echo "[devgear] Symlinking .venv into Copilot cache: ${target_venv} -> ${VENV_DIR}"
  rm -- "${target_venv}" 2>/dev/null || true
  ln -sfn -- "${VENV_DIR}" "${target_venv}"
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
    --assume-yes)
      ASSUME_YES=1
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

update_claude_cache_symlinks
update_copilot_cache_symlink

if ! command -v psql >/dev/null 2>&1; then
  echo "[devgear] Note: PostgreSQL client (psql) is required for mem sync features." >&2
fi

# ~/.devgear/mem.db スキーマを初期化する（べき等: 既存DBは変更しない）
if [[ "${SKIP_PYTHON}" != "1" ]]; then
  echo "[devgear] Initializing mem database at ${SETTINGS_DIR}/mem.db"
  "${VENV_PYTHON}" -m devgear.mem setup
fi

echo "[devgear] OK"
