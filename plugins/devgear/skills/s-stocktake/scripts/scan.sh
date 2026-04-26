#!/usr/bin/env bash
# scan.sh — スキルファイルを列挙し、フロントマターとUTC更新日時を抽出する
# 使い方: scan.sh [CWD_SKILLS_DIR]
# 出力: JSONをstdoutに出力
#
# CWD_SKILLS_DIR 省略時は $PWD/.claude/skills をデフォルトとする。
# 呼び出し元に依存せずプロジェクトレベルのスキルを常に取得する。
#
# 環境変数:
#   SKILL_STOCKTAKE_GLOBAL_DIR   ~/.claude/skills を上書き（テスト専用。本番では設定しない）
#   SKILL_STOCKTAKE_PROJECT_DIR  プロジェクトディレクトリ検出を上書き（テスト専用）

set -euo pipefail

GLOBAL_DIR="${SKILL_STOCKTAKE_GLOBAL_DIR:-$HOME/.claude/skills}"
CWD_SKILLS_DIR="${SKILL_STOCKTAKE_PROJECT_DIR:-${1:-$PWD/.claude/skills}}"
# ツール使用観測データのJSONLファイルパス（任意。使用頻度集計に使用）。
# 異なるパスを使う場合は SKILL_STOCKTAKE_OBSERVATIONS 環境変数で上書き可能。
OBSERVATIONS="${SKILL_STOCKTAKE_OBSERVATIONS:-$HOME/.claude/observations.jsonl}"

# CWD_SKILLS_DIR が .claude/skills パスに見えるか検証（多層防御）。
# パスが存在する場合のみ警告。存在しないパスはディレクトリトラバーサルのリスクなし。
if [[ -n "$CWD_SKILLS_DIR" && -d "$CWD_SKILLS_DIR" && "$CWD_SKILLS_DIR" != */.claude/skills* ]]; then
  echo "Warning: CWD_SKILLS_DIR does not look like a .claude/skills path: $CWD_SKILLS_DIR" >&2
fi

# フロントマターフィールドを抽出する（クォートあり・なし両方の単一行値に対応）。
# 複数行YAMLブロック（| や >）やネストしたYAMLキーは非対応。
extract_field() {
  local file="$1" field="$2"
  awk -v f="$field" '
    BEGIN { fm=0 }
    /^---$/ { fm++; next }
    fm==1 {
      n = length(f) + 2
      if (substr($0, 1, n) == f ": ") {
        val = substr($0, n+1)
        gsub(/^"/, "", val)
        gsub(/"$/, "", val)
        print val
        exit
      }
    }
    fm>=2 { exit }
  ' "$file"
}

# N日前のUTCタイムスタンプを取得する（macOSとGNU dateの両方に対応）
date_ago() {
  local n="$1"
  date -u -v-"${n}d" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null ||
  date -u -d "${n} days ago" +%Y-%m-%dT%H:%M:%SZ
}

# 指定ファイルパスのカットオフ以降の観測数を集計する
count_obs() {
  local file="$1" cutoff="$2"
  if [[ ! -f "$OBSERVATIONS" ]]; then
    echo 0
    return
  fi
  jq -r --arg p "$file" --arg c "$cutoff" \
    'select(.tool=="Read" and .path==$p and .timestamp>=$c) | 1' \
    "$OBSERVATIONS" 2>/dev/null | wc -l | tr -d ' '
}

# ディレクトリをスキャンしてJSONオブジェクト配列を生成する
scan_dir_to_json() {
  local dir="$1"
  local c7 c30
  c7=$(date_ago 7)
  c30=$(date_ago 30)

  local tmpdir
  tmpdir=$(mktemp -d)
  # $tmpdir をクォート文字列に埋め込まないよう関数経由でクリーンアップ
  # （TMPDIRにシェルメタ文字が含まれる場合のインジェクション防止）
  local _scan_tmpdir="$tmpdir"
  _scan_cleanup() { rm -rf "$_scan_tmpdir"; }
  trap _scan_cleanup RETURN

  # 観測数をファイルごとではなく2パスで事前集計する（O(n*m) → O(n+m) に削減）
  local obs_7d_counts obs_30d_counts
  obs_7d_counts=""
  obs_30d_counts=""
  if [[ -f "$OBSERVATIONS" ]]; then
    obs_7d_counts=$(jq -r --arg c "$c7" \
      'select(.tool=="Read" and .timestamp>=$c) | .path' \
      "$OBSERVATIONS" 2>/dev/null | sort | uniq -c)
    obs_30d_counts=$(jq -r --arg c "$c30" \
      'select(.tool=="Read" and .timestamp>=$c) | .path' \
      "$OBSERVATIONS" 2>/dev/null | sort | uniq -c)
  fi

  local i=0
  while IFS= read -r file; do
    local name desc mtime u7 u30 dp
    name=$(extract_field "$file" "name")
    desc=$(extract_field "$file" "description")
    mtime=$(date -u -r "$file" +%Y-%m-%dT%H:%M:%SZ)
    # grep -F の部分一致誤検知を避けるため awk の完全フィールド一致を使用。
    # uniq -c の出力形式: "   N /path/to/file" — パスは常にフィールド2。
    u7=$(echo "$obs_7d_counts" | awk -v f="$file" '$2 == f {print $1}' | head -1)
    u7="${u7:-0}"
    u30=$(echo "$obs_30d_counts" | awk -v f="$file" '$2 == f {print $1}' | head -1)
    u30="${u30:-0}"
    dp="${file/#$HOME/~}"

    jq -n \
      --arg path "$dp" \
      --arg name "$name" \
      --arg description "$desc" \
      --arg mtime "$mtime" \
      --argjson use_7d "$u7" \
      --argjson use_30d "$u30" \
      '{path:$path,name:$name,description:$description,use_7d:$use_7d,use_30d:$use_30d,mtime:$mtime}' \
      > "$tmpdir/$i.json"
    i=$((i+1))
  done < <(find "$dir" -name "*.md" -type f 2>/dev/null | sort)

  if [[ $i -eq 0 ]]; then
    echo "[]"
  else
    jq -s '.' "$tmpdir"/*.json
  fi
}

# --- メイン処理 ---

global_found="false"
global_count=0
global_skills="[]"

if [[ -d "$GLOBAL_DIR" ]]; then
  global_found="true"
  global_skills=$(scan_dir_to_json "$GLOBAL_DIR")
  global_count=$(echo "$global_skills" | jq 'length')
fi

project_found="false"
project_path=""
project_count=0
project_skills="[]"

if [[ -n "$CWD_SKILLS_DIR" && -d "$CWD_SKILLS_DIR" ]]; then
  project_found="true"
  project_path="$CWD_SKILLS_DIR"
  project_skills=$(scan_dir_to_json "$CWD_SKILLS_DIR")
  project_count=$(echo "$project_skills" | jq 'length')
fi

# グローバルとプロジェクトのスキルを1つの配列にマージする
all_skills=$(jq -s 'add' <(echo "$global_skills") <(echo "$project_skills"))

jq -n \
  --arg global_found "$global_found" \
  --argjson global_count "$global_count" \
  --arg project_found "$project_found" \
  --arg project_path "$project_path" \
  --argjson project_count "$project_count" \
  --argjson skills "$all_skills" \
  '{
    scan_summary: {
      global: { found: ($global_found == "true"), count: $global_count },
      project: { found: ($project_found == "true"), path: $project_path, count: $project_count }
    },
    skills: $skills
  }'
