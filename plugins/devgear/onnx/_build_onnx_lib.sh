#!/usr/bin/env bash
# _build_onnx_lib.sh — ONNX ビルド共通ロジック。install.sh と build_onnx_model.sh から source する。
# 直接実行しない。

_BUILD_ONNX_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# build_onnx_if_missing <model_target_dir> <quant> [revision]
#   model_target_dir に model.onnx が存在しない場合のみビルドする（冪等）。
#   ~/.devgear/.venv-modelbuild をビルド用 venv として使用する。
#
# build_onnx_always <model_target_dir> <quant> [revision]
#   冪等チェックなしで必ずビルドする。
build_onnx_impl() {
  local model_target="$1"
  local quant="$2"
  local revision="${3:-}"

  local build_venv="${HOME}/.devgear/.venv-modelbuild"
  local build_python="${build_venv}/bin/python3"
  local build_reqs="${_BUILD_ONNX_LIB_DIR}/requirements-build.txt"
  local src_dir="${_BUILD_ONNX_LIB_DIR}/../src"
  local log_dir="${HOME}/.devgear/logs"
  local build_log="${log_dir}/modelbuild.log"

  mkdir -p "${log_dir}" "${model_target}"

  if [[ ! -x "${build_python}" ]]; then
    echo "[build] ビルド用 venv を作成しています: ${build_venv}"
    python3 -m venv "${build_venv}"
  fi

  # ハッシュロックで PyPI レジストリ側改ざんを検知する（LS-1）
  # 再生成: pip-compile --generate-hashes plugins/devgear/onnx/requirements-build.in -o plugins/devgear/onnx/requirements-build.txt
  # run_quietly が利用可能なら使用し、なければ直接実行する（build_onnx_model.sh から直接呼ばれる場合）
  if declare -f run_quietly >/dev/null 2>&1; then
    run_quietly "${build_python}" -m pip install --quiet --disable-pip-version-check --upgrade pip
    run_quietly "${build_python}" -m pip install --quiet --disable-pip-version-check \
      --require-hashes -r "${build_reqs}"
  else
    "${build_python}" -m pip install --quiet --disable-pip-version-check --upgrade pip
    "${build_python}" -m pip install --quiet --disable-pip-version-check \
      --require-hashes -r "${build_reqs}"
  fi

  local build_args=("--quant" "${quant}" "--out" "${model_target}")
  if [[ -n "${revision}" ]]; then
    build_args+=("--revision" "${revision}")
  fi

  if ! PYTHONPATH="${src_dir}" "${build_python}" -m model_build build "${build_args[@]}" \
      2>&1 | tee "${build_log}"; then
    echo "[build] Error: ONNX ビルドに失敗しました。ログ: ${build_log}" >&2
    return 1
  fi

  if ! PYTHONPATH="${src_dir}" "${build_python}" -m model_build verify \
      --model-dir "${model_target}" 2>&1 | tee -a "${build_log}"; then
    echo "[build] Error: モデル検証に失敗しました。ログ: ${build_log}" >&2
    return 1
  fi
}

build_onnx_if_missing() {
  local model_target="$1"
  local quant="$2"
  local revision="${3:-}"
  local model_onnx="${model_target}/model.onnx"

  if [[ -f "${model_onnx}" ]]; then
    echo "[build] ONNX モデルは既にビルド済みです（スキップ）: ${model_onnx}"
    return 0
  fi

  local avail_mb
  avail_mb="$(awk '/MemAvailable/ { print int($2/1024) }' /proc/meminfo 2>/dev/null || echo 0)"
  if [[ "${avail_mb}" -lt 3072 ]]; then
    echo "[build] Warning: 利用可能 RAM が ${avail_mb} MB です。4096 MB 以上を推奨します。" >&2
  fi

  echo "[build] ONNX モデルを HuggingFace からビルドしています (~5-10 分, RAM 4-6 GB 必要)"
  echo "[build] 出力先: ${model_target}"
  build_onnx_impl "${model_target}" "${quant}" "${revision}"
  echo "[build] ONNX モデルのビルドと検証が完了しました: ${model_target}"
}

build_onnx_always() {
  build_onnx_impl "$@"
  echo "[build] 完了。生成ファイル:"
  ls -lh "${1}"
}
