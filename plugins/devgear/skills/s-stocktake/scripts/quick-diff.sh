#!/usr/bin/env bash
# quick-diff.sh — スキルファイルのmtimeをresults.jsonのevaluated_atと比較する
# 使い方: quick-diff.sh RESULTS_JSON [CWD_SKILLS_DIR]
# 出力: 変更済み・新規ファイルのJSON配列をstdoutに出力（変更なしの場合は []）
#
# CWD_SKILLS_DIR 省略時は $PWD/.claude/skills をデフォルトとする。
# 呼び出し元に依存せずプロジェクトレベルのスキルを常に取得する。
#
# 環境変数:
#   SKILL_STOCKTAKE_GLOBAL_DIR   ~/.claude/skills を上書き（テスト専用。本番では設定しない）
#   SKILL_STOCKTAKE_PROJECT_DIR  プロジェクトディレクトリ検出を上書き（テスト専用）

set -euo pipefail

RESULTS_JSON="${1:-}"
CWD_SKILLS_DIR="${SKILL_STOCKTAKE_PROJECT_DIR:-${2:-$PWD/.claude/skills}}"
GLOBAL_DIR="${SKILL_STOCKTAKE_GLOBAL_DIR:-$HOME/.claude/skills}"

if [[ -z "$RESULTS_JSON" || ! -f "$RESULTS_JSON" ]]; then
  echo "Error: RESULTS_JSON not found: ${RESULTS_JSON:-<empty>}" >&2
  exit 1
fi

# CWD_SKILLS_DIR が .claude/skills パスに見えるか検証（多層防御）。
# パスが存在する場合のみ警告。存在しないパスはディレクトリトラバーサルのリスクなし。
if [[ -n "$CWD_SKILLS_DIR" && -d "$CWD_SKILLS_DIR" && "$CWD_SKILLS_DIR" != */.claude/skills* ]]; then
  echo "Warning: CWD_SKILLS_DIR does not look like a .claude/skills path: $CWD_SKILLS_DIR" >&2
fi

evaluated_at=$(jq -r '.evaluated_at' "$RESULTS_JSON")

# evaluated_at が不正・欠落の場合は早期終了する。
# "null" との ISO 8601 文字列比較で予期しない結果が出るのを防ぐ。
if [[ ! "$evaluated_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
  echo "Error: invalid or missing evaluated_at in $RESULTS_JSON: $evaluated_at" >&2
  exit 1
fi

# results.json から既知パスを一度だけ抽出する（ファイルごとに O(1) ルックアップ）
known_paths=$(jq -r '.skills[].path' "$RESULTS_JSON" 2>/dev/null)

tmpdir=$(mktemp -d)
# $tmpdir をクォート文字列に埋め込まないよう関数経由でクリーンアップ
# （TMPDIRにシェルメタ文字が含まれる場合のインジェクション防止）
_cleanup() { rm -rf "$tmpdir"; }
trap _cleanup EXIT

# process_dir 呼び出しをまたぐ共有カウンター（intentionally NOT local）
i=0

process_dir() {
  local dir="$1"
  while IFS= read -r file; do
    local mtime dp is_new
    mtime=$(date -u -r "$file" +%Y-%m-%dT%H:%M:%SZ)
    dp="${file/#$HOME/~}"

    # results.json に既知かどうかを完全行一致で確認する。
    # 部分一致誤検知を防ぐ（例: "python-patterns" が "python-patterns-v2" にマッチしないよう）
    if echo "$known_paths" | grep -qxF "$dp"; then
      is_new="false"
      # 既知ファイル: mtime が変化した場合のみ出力（ISO 8601 文字列比較は安全）
      [[ "$mtime" > "$evaluated_at" ]] || continue
    else
      is_new="true"
      # 新規ファイル: mtime に関係なく常に出力
    fi

    jq -n \
      --arg path "$dp" \
      --arg mtime "$mtime" \
      --argjson is_new "$is_new" \
      '{path:$path,mtime:$mtime,is_new:$is_new}' \
      > "$tmpdir/$i.json"
    i=$((i+1))
  done < <(find "$dir" -name "*.md" -type f 2>/dev/null | sort)
}

[[ -d "$GLOBAL_DIR" ]] && process_dir "$GLOBAL_DIR"
[[ -n "$CWD_SKILLS_DIR" && -d "$CWD_SKILLS_DIR" ]] && process_dir "$CWD_SKILLS_DIR"

if [[ $i -eq 0 ]]; then
  echo "[]"
else
  jq -s '.' "$tmpdir"/*.json
fi
