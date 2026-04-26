---
name: s-gitflow
description: Gitワークフローパターン。ブランチ戦略/コミット規約/マージvsリベース/コンフリクト解決/全規模チーム向け共同開発ベストプラクティス。
---

# Git ワークフローパターン

Gitバージョン管理・ブランチ戦略・共同開発ベストプラクティス。

## 発動タイミング

- ブランチ戦略を決めるとき
- コミットメッセージやPR説明文を書くとき
- マージコンフリクトを解決するとき
- リリースやバージョンタグを管理するとき

## ブランチ戦略

- Pull Requestベース: 規模問わず・継続的デプロイ → SaaS・Webアプリ・スタートアップ
- トランクベース: 経験豊富な5名以上・1日複数回デプロイ → 高速開発チーム・機能フラグ運用
- GitFlow: 10名以上・定期リリース → エンタープライズ・規制の厳しい業界

**詳細は `references/branching-strategies.md` 参照。**

## コミットメッセージ

Conventional Commits形式: `<type>(<scope>): <subject>`

- `feat`: 新機能 / `fix`: バグ修正 / `docs`: ドキュメント / `refactor`: リファクタリング
- `test`: テスト / `chore`: 保守作業 / `perf`: 性能改善

**詳細は `references/commit-conventions.md` 参照。**

## マージ vs リベース

- feature → main: マージ
- ローカルfeatureをmainに追従: リベース
- push済み/他の人が作業中: マージ（リベース禁止）
- 直線的な履歴にしたい: リベース

## アンチパターン

- mainに直接コミット → featureブランチとPR使う
- シークレットをコミット → `.gitignore`と環境変数
- 巨大PR（1000行以上） → 小さく焦点を絞ったPRに分割
- 曖昧なコミットメッセージ → 説明的なメッセージ
- 公開履歴を書き換える → revert使う
- 長期featureブランチ → 短く保ち頻繁にリベース

## 早見表

- ブランチ作成: `git checkout -b feature/name`
- マージ: `git merge branch-name`
- リベース: `git rebase main`
- コミット取り消し: `git reset --soft HEAD~1`
- push済み取り消し: `git revert HEAD`
- スタッシュ: `git stash push -m "message"`

## 参照ファイル

- `references/branching-strategies.md` — ブランチ戦略詳細・マージ/リベース手順・コンフリクト解決
- `references/commit-conventions.md` — Conventional Commits・PRテンプレート・リリース管理・Git設定

## 永続メモリ

search: `git commit branch merge rebase`
record: `{"event_type": "git-workflow", "content": "Merged {branch} to main. Conflicts: {n}. Strategy: {strategy}"}`
