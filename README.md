# Multi-LLM Agents Orchestration

Claude をオーケストレーターとして使い、外部 CLI（Codex / Gemini / GitHub Copilot）へ段階的に委譲するための、Task Packet ベース実行フレームワークです。

This repository is a Task Packet-based orchestration framework where Claude acts as the orchestrator and delegates stage work to external CLIs (Codex / Gemini / GitHub Copilot).

---

## 日本語

### 1) 前提条件（必須）

- **Claude Code の利用が前提**です。
- **Codex / Gemini / GitHub Copilot のうち、少なくとも 1 つ以上の CLI が利用可能**である必要があります。
- 使用する CLI は、**インストールと認証を完了済み**にしてください（詳細手順は各公式ドキュメントを参照）。
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
- 構成スナップショット: `configs/config-state.md`, `configs/config-state.yaml`
- 中央実行エントリ: `scripts/agent-cli/dispatch.sh`

---

## English

### 1) Prerequisites (Required)

- **Claude Code is required**.
- At least **one CLI among Codex / Gemini / GitHub Copilot must be available**.
- The CLI(s) you use must be **installed and authenticated** (follow official docs; detailed install steps are intentionally omitted here):
  - Codex CLI: [Official guide](https://developers.openai.com/codex/cli)
  - Gemini CLI: [Official guide](http://geminicli.com/docs/get-started/)
  - Copilot CLI: [Official guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli)
- You also need `git`, `python3`, `perl`, and a YAML parser (`yq` or `python3 + pyyaml`).

> This project assumes your CLI environment is already usable. If not, set it up first with the official links above.

### 2) From clone to initial validation

```bash
git clone <your-fork-or-repo-url>
cd Multi-LLM-Agents-Orchestration

# Check only the tools you plan to use (example: codex + gemini)
./scripts/agent-cli/preflight.sh --tools codex,gemini
```

### 3) Mandatory preparation before using agent-collab

Before running `agent-collab`, prepare a **clear task request document**. If your task intent is ambiguous, orchestration quality and verification reliability will degrade.

At minimum, define:

- Goal
- Scope (allow / deny)
- Acceptance Criteria
- Verify Commands
- Constraints

Minimal template:

```md
# Task Request

- Goal:
- Scope (allow/deny):
- Acceptance Criteria:
- Verify Commands:
- Constraints:
```

### 4) Typical execution patterns

#### A. Full flow (Plan → Impl → Review)

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode all \
  --preflight .tmp/agent-collab/preflight.md \
  --goal "Implement approved plan"
```

#### B. Direct Task Packet pipeline

```bash
./scripts/agent-cli/dispatch.sh pipeline --task .tmp/task/<task-id> --plan auto
```

### 5) Customization after clone

#### Model routing

- Provider defaults and allowed models: `configs/servant/*.yaml`
- Stage-level model assignments: `configs/pipeline/*.yaml`
- Effective priority is roughly: `manifest override > stage model > purpose model > default model`

Recommended strategy:

- Use stronger models for impl/verify stages
- Use lower-cost models for review-heavy stages
- Use low-latency models for one-shot workflows

#### Behavior tuning

- Routing intent via `manifest.yaml` `routing.intent`
  - e.g. `safe_impl`, `one_shot_impl`, `design_only`, `review_cross`
- Timeout policy via `timeout_mode` (`enforce` or `wait_done`)
- Budget control via `budgets.paid_call_budget` and `budgets.retry_budget`
- Context compression via `context.digest_policy` (`off`, `auto`, `aggressive`)

#### Verification quality

- Keep `acceptance.commands[]` meaningful and executable
- Keep `acceptance.criteria[]` reviewable and concrete
- On failure, check `outputs/_summary.md` and `state/last_failure.json` first

### 6) Intent-to-pipeline guidance

- **Large implementation changes**: `safe_impl`
- **Small/focused change**: `one_shot_impl`
- **Design/research only**: `design_only`
- **Post-implementation quality hardening**: `review_cross` or `post_impl_review`

### 6.1) Recommended profile (starting point)

- **Default recommendation**: `safe_impl`
- **Conditional recommendation**: use `one_shot_impl` only for small, well-specified changes
- **Quality-hardening focus**: use `post_impl_review` when post-implementation assurance is the main goal

Example (`manifest.yaml`):

```yaml
routing:
  intent: safe_impl
```

### 7) Core references

- Task Packet spec: `docs/TOOLS/TASK_PACKET.md`
- Model routing policy: `docs/TOOLS/MODEL_ROUTING.md`
- Effective config snapshots: `configs/config-state.md`, `configs/config-state.yaml`
- Central execution entrypoint: `scripts/agent-cli/dispatch.sh`
