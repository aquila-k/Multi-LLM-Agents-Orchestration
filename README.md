# Multi-LLM Agents Orchestration

[日本語](./docs/README/README.ja.md)

This repository is a Task Packet-based orchestration framework where Claude acts as the orchestrator and delegates stage work to external CLIs (Codex / Gemini / GitHub Copilot).

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
