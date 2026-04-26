#!/usr/bin/env bash
# save-results.sh — 評価済みスキルをresults.jsonに正確なUTCタイムスタンプとともにマージする
# 使い方: save-results.sh RESULTS_JSON <<< "$EVAL_JSON"
#
# stdin フォーマット:
#   { "skills": {...}, "mode"?: "full"|"quick", "batch_progress"?: {...} }
#
# 常に `date -u` で現在のUTC時刻を evaluated_at にセットする。
# stdinの .skills を既存のresults.jsonにマージする（新規エントリが古いものを上書き）。
# stdinに .mode と .batch_progress があれば更新する。

set -euo pipefail

RESULTS_JSON="${1:-}"

if [[ -z "$RESULTS_JSON" ]]; then
  echo "Error: RESULTS_JSON argument required" >&2
  echo "Usage: save-results.sh RESULTS_JSON <<< \"\$EVAL_JSON\"" >&2
  exit 1
fi

EVALUATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# stdinから評価結果を読み込み、結果ファイルを更新する前にJSONを検証する
input_json=$(cat)
if ! echo "$input_json" | jq empty 2>/dev/null; then
  echo "Error: stdin is not valid JSON" >&2
  exit 1
fi

if [[ ! -f "$RESULTS_JSON" ]]; then
  # 初回作成: stdinのJSONに現在のUTCタイムスタンプを付加して新規作成する
  echo "$input_json" | jq --arg ea "$EVALUATED_AT" \
    '. + { evaluated_at: $ea }' > "$RESULTS_JSON"
  exit 0
fi

# マージ: 新しい .skills が既存を上書きする。input_jsonにないスキルは保持される。
# .mode と .batch_progress は提供されている場合のみ更新する。
#
# 競合する同時実行を防ぐため mktemp で衝突安全な一時ファイルを使用する
# （同じ RESULTS_JSON に対する並行実行が予測可能な ".tmp" サフィックスで競合しないよう）
tmp=$(mktemp "${RESULTS_JSON}.XXXXXX")
trap 'rm -f "$tmp"' EXIT

jq -s \
  --arg ea "$EVALUATED_AT" \
  '.[0] as $existing | .[1] as $new |
   $existing |
   .evaluated_at = $ea |
   .skills = ($existing.skills + ($new.skills // {})) |
   if ($new | has("mode")) then .mode = $new.mode else . end |
   if ($new | has("batch_progress")) then .batch_progress = $new.batch_progress else . end' \
  "$RESULTS_JSON" <(echo "$input_json") > "$tmp"

mv "$tmp" "$RESULTS_JSON"
