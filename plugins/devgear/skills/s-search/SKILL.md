---
name: s-search
description: 実装前 既存解決策探索ワークフロー。ツール/ライブラリ/パターン調査→カスタムコード作成。リサーチャーエージェント呼び出し。
context: fork
---

# コードを書く前に調べる

## 発動タイミング

新機能追加・依存関係追加・新規ユーティリティ/ヘルパー/抽象化を作る前

## ワークフロー

1. **要件分析** — 必要な機能と言語/フレームワーク制約を把握
2. **並列検索** — パッケージレジストリ・MCP/スキル・GitHub/Webを同時に検索
3. **評価** — 機能・保守性・コミュニティ・ドキュメント・ライセンス・依存関係で採点
4. **判定** — 採用/拡張/自作を決定
5. **実装** — パッケージインストール/MCP設定/最小限カスタムコードを書く

## 判定マトリクス

- 完全一致・保守継続・MIT/Apache → **採用** — そのままインストール
- 部分一致・土台として良好 → **拡張** — 薄いラッパーを書く
- 弱い候補が複数 → **組み合わせる** — 2〜3個を組み合わせ
- 適切な候補なし → **自作** — 調査結果を踏まえてカスタム実装

## 使い方

### 簡易モード（インライン）

0. リポジトリにもうある？ → `rg` で探す
1. よくある問題？ → パッケージレジストリを検索
2. MCP はある？ → `~/.claude/settings.json` を確認
3. スキルはある？ → `~/.claude/skills/` を確認
4. GitHub に実装はある？ → 保守されている OSS を GitHub コード検索で探す

### 完全モード（エージェント並列）

以下の3エージェントを**同時起動**し、全結果をマージしてから評価・判定マトリクスを適用する:

```text
# エージェントA: パッケージレジストリ
Agent(subagent_type="general-purpose", prompt="
  Search npm/PyPI for: [DESCRIPTION]. Language/framework: [LANG]
  Return top 3: name, version, weekly downloads, last update, license, description
")

# エージェントB: MCP・スキル・ローカル資産
Agent(subagent_type="general-purpose", prompt="
  Search for existing assets for: [DESCRIPTION]
  1. ~/.claude/settings.json でMCPサーバー確認
  2. ~/.claude/skills/ で関連スキル確認
  3. rg で既存実装を確認
  Return: type, name/path, match_quality
")

# エージェントC: GitHub・Web
Agent(subagent_type="general-purpose", prompt="
  Search GitHub and web for: [DESCRIPTION]. Language/framework: [LANG]
  Find actively maintained OSS. Check: stars, last commit, open issues, license
  Return top 3 with comparison
")
```

## カテゴリ別ショートカット

- 静的解析: `eslint`, `ruff`, `textlint`
- 整形: `prettier`, `black`, `gofmt`
- テスト: `jest`, `pytest`, `go test`
- HTTPクライアント: `httpx`(Py), `ky`/`got`(Node)
- バリデーション: `zod`(TS), `pydantic`(Py)
- Markdown処理: `remark`, `unified`, `markdown-it`
- Claude SDK: Context7で最新ドキュメント確認

## アンチパターン

- 既存確認なしにユーティリティを作る
- MCPサーバーを見落とす
- ライブラリを過剰にラップして利点を失わせる
- 小さな機能のために巨大なパッケージを入れる

## 永続メモリ

search: `adopt reject tool library {category}` / `{tool_name} success fail issue`
record: `{"event_type": "tool-search", "content": "Searched for {category}. Adopted: {tool_name}. Reason: {reason}"}`
参照: 採用決定履歴 / ツール成功追跡 / 却下理由
