#!/usr/bin/env bash
# build_onnx_model.sh — ruri-v3 ONNX ビルド・量子化・分割を 1 発で実行するメンテナ向けスクリプト。
#
# 使い方:
#   ./scripts/build_onnx_model.sh                        # FP16 デフォルト（推奨）
#   ./scripts/build_onnx_model.sh --quant fp32           # FP32（品質劣化ゼロ、約 1.2 GB）
#   ./scripts/build_onnx_model.sh --quant int8           # INT8（動的量子化、約 300 MB）
#   ./scripts/build_onnx_model.sh --quant fp16 --revision <SHA>
#
# 出力先: assets/models/
# 使用する venv: .venv-modelbuild/（リポ管理外、このスクリプトが自動作成）
#
# 量子化方式:
#   FP16: onnxruntime.transformers.optimizer を使用（CPU 対応）。約 600 MB。
#   FP32: 量子化なし。品質劣化ゼロ。約 1.2 GB（GitHub 推奨 1GB 超）。
#   INT8: onnxruntime 動的量子化。約 300 MB。精度低下 < 0.5%（要検証）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."

QUANT="fp16"
REVISION=""

usage() {
  cat <<'EOF'
Usage: ./scripts/build_onnx_model.sh [options]

Options:
  --quant fp16|fp32|int8   量子化レベル (default: fp16)
                            fp16: ort optimizer 経由（CPU 対応、約 600 MB）★推奨
                            fp32: 量子化なし（約 1.2 GB）
                            int8: 動的量子化（約 300 MB）
  --revision SHA           HF Hub commit SHA (default: settings.py の _DEFAULT_EMBEDDING_REVISION)
  --help                   このヘルプを表示

出力先: assets/models/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quant)
      QUANT="$2"
      shift 2
      ;;
    --revision)
      REVISION="$2"
      if [[ ! "${REVISION}" =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]]; then
        echo "Error: --revision は 40 または 64 文字の16進数 SHA を指定してください: '${REVISION}'" >&2
        exit 1
      fi
      shift 2
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

# 量子化レベルのバリデーション
case "${QUANT}" in
  fp16|fp32|int8) ;;
  *)
    echo "Error: --quant は fp16 / fp32 / int8 のいずれかを指定してください。" >&2
    exit 1
    ;;
esac

VENV_DIR="${REPO_ROOT}/.venv-modelbuild"
VENV_PYTHON="${VENV_DIR}/bin/python3"
SRC_DIR="${REPO_ROOT}/src"

echo "[build] ONNX モデルビルドを開始します (quant=${QUANT})"
echo "[build] リポジトリルート: ${REPO_ROOT}"

# ---- メンテナ用 venv 作成 ----
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[build] メンテナ用 venv を作成しています: ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi

echo "[build] ビルド依存を venv にインストールしています..."
"${VENV_PYTHON}" -m pip install --quiet --disable-pip-version-check --upgrade pip

# ハッシュロックで依存パッケージのレジストリ側改ざんを検知する（LS-1）。
# 再生成: pip-compile --generate-hashes scripts/requirements-build.in -o scripts/requirements-build.txt
"${VENV_PYTHON}" -m pip install --quiet --disable-pip-version-check \
  --require-hashes -r "${SCRIPT_DIR}/requirements-build.txt"

# ---- model_build をビルド venv に追加 ----
# sys.path に src/ を追加して直接実行（パッケージインストール不要）

BUILD_ARGS=("--quant" "${QUANT}")
if [[ -n "${REVISION}" ]]; then
  BUILD_ARGS+=("--revision" "${REVISION}")
fi

echo "[build] ONNX ビルドを実行しています..."
PYTHONPATH="${SRC_DIR}" "${VENV_PYTHON}" -m model_build build "${BUILD_ARGS[@]}"

echo "[build] ビルド成果物を検証しています..."
OUT_DIR="${REPO_ROOT}/assets/models"
PYTHONPATH="${SRC_DIR}" "${VENV_PYTHON}" -m model_build verify --model-dir "${OUT_DIR}"

echo "[build] model_sources.json を生成しています..."
PYTHONPATH="${SRC_DIR}" "${VENV_PYTHON}" -m model_build sources \
  --model-dir "${OUT_DIR}" \
  --out "${REPO_ROOT}/plugins/devgear/model_sources.json"

echo ""
echo "[build] 完了。生成ファイル:"
ls -lh "${OUT_DIR}"
SHORT_SHA="$(git rev-parse --short=7 HEAD)"
TAG_NAME="models/${SHORT_SHA}-${QUANT}"

echo ""
echo "[build] 次のステップ: 署名タグを作成してから model_sources.json を生成してください。"
echo ""
echo "  # 1. 生成ファイルを commit する（tag 前に commit が必要）"
echo "  git add assets/models/"
echo "  git commit -m 'chore: update ONNX model (${QUANT})'"
echo ""
echo "  # 2. 署名済み git tag を作成して push する"
echo "  git tag -s ${TAG_NAME} -m 'Model build ${QUANT}'"
echo "  git push origin ${TAG_NAME}"
echo ""
echo "  # 3. 署名者の GPG 指紋を確認する（gpg --list-keys で確認可）"
echo "  # 4. model_sources.json を生成する"
echo "  python3 -m model_build sources \\"
echo "    --signed-tag ${TAG_NAME} \\"
echo "    --signer-fingerprint <YOUR_40HEX_KEY_FINGERPRINT>"
echo "  git add plugins/devgear/model_sources.json"
echo "  git commit -m 'chore: update model_sources.json with signed tag ${TAG_NAME}'"
