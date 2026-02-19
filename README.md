# Multi-LLM Agents Orchestration

[日本語](./docs/README/README.ja.md)

A Claude Code skill that lets you delegate complex tasks to Codex, Gemini, and GitHub Copilot — orchestrated automatically.
You write what you want done. Claude Code handles the rest.

---

## How It Works

When you invoke `/agent-collab` in Claude Code, it runs a multi-stage pipeline:

1. **Plan** — Gemini drafts and refines an implementation plan
2. **Impl** — Codex or Copilot implements it
3. **Review** — Gemini reviews the output

Claude Code acts as the orchestrator throughout. You never need to call scripts directly.

---

## Prerequisites

**Claude Code** must be installed and running. Then install and authenticate at least one of the following CLIs:

| CLI | Install guide |
| --- | ------------- |
| Gemini CLI | [geminicli.com/docs/get-started](http://geminicli.com/docs/get-started/) |
| OpenAI Codex CLI | [developers.openai.com/codex/cli](https://developers.openai.com/codex/cli) |
| GitHub Copilot CLI | [GitHub Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli) |

You also need `python3` with `pyyaml` and `perl` (both are standard on macOS/Linux):

```bash
pip3 install pyyaml
```

> You only need the CLIs you plan to use. The skill will tell you which ones are missing if needed.

---

## Setup

```bash
git clone <this-repo-url>
cd Multi-LLM-Agents-Orchestration
```

Open this directory in Claude Code. The `/agent-collab` skill is automatically available.

---

## Usage

### Step 1 — Write your task document

Copy the template and fill it in:

```bash
mkdir -p .tmp/agent-collab
cp .claude/skills/agent-collab/preflight.template.md .tmp/agent-collab/preflight.md
# Edit .tmp/agent-collab/preflight.md
```

The document should describe:

| Field | What to write |
| ----- | ------------- |
| **Goal** | What must be achieved |
| **Scope** | What can / cannot be changed |
| **Acceptance Criteria** | Verifiable completion conditions |
| **Verification Commands** | Commands that confirm success |
| **Constraints** | Compatibility, performance, deadlines |

The clearer your document, the better the output. Vague goals lead to vague results.

### Step 2 — Invoke the skill

In Claude Code, type:

```text
/agent-collab
```

Claude Code will read your preflight document, infer whether you need planning, implementation, or review, and run the appropriate pipeline automatically.

### Step 3 — Review the output

Results are written to `.tmp/agent-collab/<run-id>/`. Claude Code will summarize the outcome and surface any failures.

---

## What Happens Automatically

- **Path resolution** — CLIs installed via NVM, Homebrew, or other non-standard locations are found automatically. If a CLI cannot be located, you will be asked to run `which <tool>` and provide the result.
- **Mode selection** — Claude Code infers `plan`, `impl`, or `review` from your request. You can also say explicitly: *"plan only"*, *"implement the approved plan"*, *"review the existing output"*.
- **Routing** — The right CLIs are selected based on task size and type. No configuration required for typical use.

---

## Advanced: Manual Mode Selection

If you want to control which phase runs, tell Claude Code explicitly when invoking the skill:

| What you want | What to say |
| ------------- | ----------- |
| Planning only | `/agent-collab` + *"plan only"* |
| Implement an existing plan | `/agent-collab` + *"implement the approved plan"* |
| Review existing output | `/agent-collab` + *"review the output"* |
| End-to-end (all phases) | `/agent-collab` + *"run all phases"* |

---

## Troubleshooting

**CLI not found** — The skill will print which binary is missing and what to run (`which <tool>`). Provide that output and Claude Code will retry.

**Poor output quality** — The most common cause is an underspecified preflight document. Add concrete acceptance criteria and verification commands.

**Timeout** — Large tasks may exceed default timeouts. Break the task into smaller pieces, or mention it when invoking the skill.
