# Multi-LLM Agents Orchestration

Claude Codeを中心として、Codex / Gemini / GitHub CopilotなどのエージェントをCLI経由で柔軟に組み合わせてタスクを実行するためのスキルと、その運用のためのスクリプトや設定ファイルを提供する。

---

## 日本語

### 1) 前提条件（必須）

- **Claude Code が使用可能であること**(Claude Code以外のエージェントから呼び出す場合には別途最適化が必要な可能性がある。)
- **Codex CLI / Gemini CLI / GitHub Copilot CLI のいずれかが利用可能**であること。
- 使用するCLIのインストールと認証が完了していること（公式ドキュメントを参照してください）:
  - Codex CLI: [Official guide](https://developers.openai.com/codex/cli)
  - Gemini CLI: [Official guide](http://geminicli.com/docs/get-started/)
  - Copilot CLI: [Official guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli)
- 追加で `git` / `python3` / `perl` / YAML パーサー（`yq` または `python3 + pyyaml`）が必要です。

> このプロジェクトは「CLI がすでに使える状態」を前提にしています。未導入の場合のみ、上記公式手順で準備してください。

### 2) clone から初期確認まで

```bash
git clone <your-fork-or-repo-url>
cd Multi-LLM-Agents-Orchestration

# 使う CLI のみを指定して事前確認（例: codex + gemini）
./scripts/agent-cli/preflight.sh --tools codex,gemini
```

### 3) まずやるべきこと（依頼文書の明確化）

`agent-collab` を使う前に、**何を達成したいかを明確化した文書**を必ず作成してください。
目的が曖昧なまま実行しても、品質・再現性・検証可能性が下がります。

最低限、次を明記することを推奨します。

- Goal（達成したい結果）
- Scope（変更してよい範囲 / 禁止範囲）
- Acceptance Criteria（完了条件）
- Verify Commands（検証コマンド）
- Constraints（制約: 互換性、性能、締切など）

簡易テンプレート例:

```md
# Task Request

- Goal:
- Scope (allow/deny):
- Acceptance Criteria:
- Verify Commands:
- Constraints:
```

### 4) 実行方法（代表パターン）

#### A. Plan → Impl → Review を一括で回す

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode all \
  --preflight .tmp/agent-collab/preflight.md \
  --goal "Implement approved plan"
```

#### B. Task Packet を直接実行する

```bash
./scripts/agent-cli/dispatch.sh pipeline --task .tmp/task/<task-id> --plan auto
```

### 5) カスタマイズ手順（clone 後に調整するポイント）

#### モデル選定

- プロバイダ別の既定値・許可モデル: `configs/servant/*.yaml`
- パイプライン段階ごとの固定モデル: `configs/pipeline/*.yaml`
- 優先順位は概ね `manifest override > stage model > purpose model > default model`

推奨運用:

- 実装（impl / verify）は強めモデル
- レビュー（review）は中コストモデル
- one-shot は低遅延モデル

#### 振る舞いの調整

- ルーティング意図: `manifest.yaml` の `routing.intent`
  - 例: `safe_impl`, `one_shot_impl`, `design_only`, `review_cross`
- タイムアウト/待機方針: `timeout_mode`（`enforce` / `wait_done`）
- コスト管理: `budgets.paid_call_budget`, `budgets.retry_budget`
- コンテキスト圧縮: `context.digest_policy`（`off` / `auto` / `aggressive`）

#### 検証品質の調整

- `acceptance.commands[]` を実際に意味のある検証コマンドにする
- `acceptance.criteria[]` をレビュー可能な文で定義する
- 失敗時は `outputs/_summary.md` と `state/last_failure.json` を最初に確認する

### 6) モデル選定ガイド（目的別）

- **大きな差分を伴う実装**: `safe_impl`（brief → impl → verify → review）
- **軽微修正/定型作業**: `one_shot_impl`
- **実装前の設計検討**: `design_only`
- **既存差分の品質強化**: `review_cross` または `post_impl_review`

### 6.1) 推奨プロファイル（最初の運用設定）

- **初期推奨**: `safe_impl`
- **条件付き推奨**: 変更が小さく要件が固い場合のみ `one_shot_impl`
- **レビュー強化時**: 実装後の品質担保が主目的なら `post_impl_review`

設定例（`manifest.yaml`）:

```yaml
routing:
  intent: safe_impl
```

### 7) 主な参照先

- Task Packet 仕様: `docs/TOOLS/TASK_PACKET.md`
- モデルルーティング: `docs/TOOLS/MODEL_ROUTING.md`
- 設定情報: `configs/config-state.md`, `configs/config-state.yaml`
- メインスクリプト: `scripts/agent-cli/dispatch.sh`
