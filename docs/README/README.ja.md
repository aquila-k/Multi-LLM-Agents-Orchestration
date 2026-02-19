# Multi-LLM Agents Orchestration

Codex / Gemini / GitHub Copilot などの外部 CLI に複雑なタスクを委譲できる Claude Code スキルです。
やりたいことを文書に書いてスキルを呼び出すだけで、あとは Claude Code が自動でパイプラインを回します。

---

## 仕組み

`/agent-collab` を Claude Code で呼び出すと、以下のパイプラインが自動で実行されます:

1. **Plan** — Gemini が実装計画を立案・洗練
2. **Impl** — Codex または Copilot が実装
3. **Review** — Gemini が成果物をレビュー

スクリプトを直接叩く必要はありません。

---

## 前提条件

**Claude Code** が使えること。そのうえで、以下の CLI を 1 つ以上インストール・認証してください:

| CLI | インストールガイド |
| --- | ----------------- |
| Gemini CLI | [geminicli.com/docs/get-started](http://geminicli.com/docs/get-started/) |
| OpenAI Codex CLI | [developers.openai.com/codex/cli](https://developers.openai.com/codex/cli) |
| GitHub Copilot CLI | [GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli) |

また、`python3 + pyyaml` と `perl` が必要です（macOS/Linux では標準で入っています）:

```bash
pip3 install pyyaml
```

> 使う CLI だけ用意すれば十分です。見つからない CLI があった場合は、スキル側が「`which <tool>` を実行して出力を教えてください」と案内します。

---

## セットアップ

```bash
git clone <this-repo-url>
cd Multi-LLM-Agents-Orchestration
```

このディレクトリを Claude Code で開くだけで `/agent-collab` スキルが使えるようになります。

---

## 使い方

### Step 1 — タスク文書を書く

テンプレートをコピーして中身を記入します:

```bash
mkdir -p .tmp/agent-collab
cp .claude/skills/agent-collab/preflight.template.md .tmp/agent-collab/preflight.md
# .tmp/agent-collab/preflight.md を編集する
```

以下の項目を書いてください:

| 項目 | 何を書くか |
| ---- | ---------- |
| **Goal** | 達成したい結果 |
| **Scope** | 変更してよい範囲 / 変更してはいけない範囲 |
| **Acceptance Criteria** | 完了の判定基準（検証可能な形で） |
| **Verification Commands** | 完了確認のコマンド |
| **Constraints** | 互換性・性能・締切などの制約 |

文書が具体的なほど、アウトプットの品質が上がります。曖昧な目標は曖昧な結果を生みます。

### Step 2 — スキルを呼び出す

Claude Code で以下を入力します:

```text
/agent-collab
```

Claude Code が preflight 文書を読み、「計画が必要か・実装か・レビューか」を自動で判断してパイプラインを実行します。

### Step 3 — 結果を確認する

成果物は `.tmp/agent-collab/<run-id>/` に書き出されます。Claude Code が結果を要約し、失敗があれば原因も伝えます。

---

## 自動で行われること

- **パス解決** — NVM や Homebrew など非標準の場所にインストールされた CLI も自動で検出します。見つからない場合は `which <tool>` の実行を案内します。
- **モード自動判断** — リクエスト内容から `plan` / `impl` / `review` を自動で推定します。
- **ルーティング** — タスクの規模や種類に応じて適切な CLI が選ばれます。通常は設定不要です。

---

## 応用: フェーズを明示的に指定する

特定のフェーズだけを実行したい場合は、スキル呼び出し時に一言添えてください:

| やりたいこと | Claude Code への指示 |
| ------------ | -------------------- |
| 計画だけ | `/agent-collab` + *"plan only"* |
| 承認済み計画を実装 | `/agent-collab` + *"implement the approved plan"* |
| 成果物をレビュー | `/agent-collab` + *"review the output"* |
| 全フェーズを一括実行 | `/agent-collab` + *"run all phases"* |

---

## トラブルシューティング

**CLI が見つからない** — どのバイナリが不足しているか、何を実行すればよいか（`which <tool>`）をスキルが案内します。出力を Claude Code に渡すと自動でリトライします。

**アウトプットの品質が低い** — 原因のほとんどは preflight 文書の不足です。Acceptance Criteria と Verification Commands を具体的に書き直してください。

**タイムアウト** — タスクが大きすぎる可能性があります。タスクを分割するか、スキル呼び出し時にその旨を伝えてください。
