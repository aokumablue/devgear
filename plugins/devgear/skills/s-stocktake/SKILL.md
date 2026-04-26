---
name: s-stocktake
description: Claude skills/commands品質監査。変更skillのみ対象のQuick Scanと完全レビューのFull Stocktakeの両モード対応。並列サブエージェントバッチ評価。
---

# s-stocktake: スキル棚卸し

skills と commands を品質チェックリストとAIによる総合判断で監査。

## 対象範囲

- `~/.claude/skills/` — グローバルスキル
- `{cwd}/.claude/skills/` — プロジェクトレベルスキル（存在する場合）

フェーズ1開始時にスキャンしたパスを明示的に列挙する。

## モード

- Quick Scan: `results.json` が存在する（既定） → 5〜10分
- Full Stocktake: `results.json` がない、または `/c-stocktake full` → 20〜30分

**結果キャッシュ:** `~/.claude/skills/s-stocktake/results.json`

## Quick Scan

前回実行以降に変更されたskillのみを再評価。

1. `results.json` 読み込む
2. `bash ~/.claude/skills/s-stocktake/scripts/quick-diff.sh ~/.claude/skills/s-stocktake/results.json` を実行
3. 出力が `[]` → 「変更なし」と報告して終了
4. 変更ファイルのみ同じ基準で再評価、未変更は前回結果を引き継ぐ
5. `bash ~/.claude/skills/s-stocktake/scripts/save-results.sh ~/.claude/skills/s-stocktake/results.json <<< "$EVAL_RESULTS"` で保存

## Full Stocktake

### フェーズ1 — インベントリ

`bash ~/.claude/skills/s-stocktake/scripts/scan.sh` を実行。skillファイルを列挙しfrontmatter・mtimeを収集。

### フェーズ2 — 品質評価（並列）

スキルリストを**最大4チャンク**（1チャンク最大20 skill）に分割し、全チャンクのサブエージェントを**同時起動**する（例: 80 skill → 4 agent 同時）。各エージェントは独立して評価を完結させる。

```text
Agent(subagent_type="general-purpose", prompt="
次の skill インベントリをチェックリストに照らして評価し、各 skill について JSON を返してください:
{ "verdict": "Keep"|"Improve"|"Update"|"Retire"|"Merge into [X]", "reason": "..." }
[CHUNK_INVENTORY] / [CHECKLIST]
")
```

**チェックリスト:**
- [ ] 他のskillとの内容の重複確認
- [ ] MEMORY.md / CLAUDE.md との重複確認
- [ ] 技術参照の鮮度確認（WebSearch使用）
- [ ] 利用頻度を考慮

**判定基準:**
- Keep: 有用で現行のまま使える
- Improve: 残す価値はあるが具体的な改善が必要
- Update: 技術参照が古い
- Retire: 品質低い・古い・コストに見合わない
- Merge into [X]: 別のskillと大きく重複

**reasonの品質要件:** 自己完結な内容。`"unchanged"` だけは禁止。Retire/Mergeは具体的な欠陥と代替を述べる。

全エージェント完了後、結果をマージして `status: "completed"` で保存。

起動時に `status: "in_progress"` が見つかったら、**未完了チャンクのみ**再起動（評価済みチャンクは再実行しない）。

### フェーズ3 — 要約表

`| Skill | 7d use | Verdict | Reason |`

### フェーズ4 — 統合

1. **Retire/Merge**: 具体的な根拠を提示してユーザー確認
2. **Improve**: 何をどう変えるか根拠付きで提案
3. **Update**: ソース確認後に更新済み内容を提示
4. MEMORY.md が100行超なら圧縮を提案

## 結果ファイルスキーマ

`~/.claude/skills/s-stocktake/results.json`:

```json
{
  "evaluated_at": "2026-02-21T10:00:00Z",
  "mode": "full",
  "batch_progress": {"total": 80, "evaluated": 80, "status": "completed"},
  "skills": {
    "skill-name": {
      "path": "~/.claude/skills/skill-name/SKILL.md",
      "verdict": "Keep",
      "reason": "...",
      "mtime": "2026-01-15T08:30:00Z"
    }
  }
}
```

`evaluated_at` は `date -u +%Y-%m-%dT%H:%M:%SZ` で取得した実際のUTC時刻。`T00:00:00Z` の近似値は禁止。

## 注意

- 評価はブラインド（由来に関係なく同じチェックリストを適用）
- アーカイブ/削除には必ずユーザー確認

## 永続メモリ

search: `stocktake audit verdict` / `{skill_name} verdict improve retire`
record: `{"event_type": "stocktake", "content": "Stocktake completed: {total} skills, {keep} Keep, {improve} Improve, {retire} Retire"}`
参照: 監査結果トレンド / 引退候補追跡 / 品質メトリクス蓄積
