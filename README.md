# Multi-LLM Agents Orchestration

[日本語](./docs/README/README.ja.md)

A Claude Code skill that lets you delegate complex tasks to Codex, Gemini, and GitHub Copilot — orchestrated automatically.
You write what you want done. Claude Code handles the rest.

---

## How It Works

Skills in this repository are **manual activation only**.
Each skill uses Claude frontmatter `disable-model-invocation: true`, so they run only when you explicitly invoke the skill name (for example `/agent-collab`).

When you invoke `/agent-collab` in Claude Code, it runs a multi-stage pipeline:

1. **Plan** — Gemini drafts and refines an implementation plan
2. **Impl** — Codex or Copilot implements it
3. **Review** — Gemini reviews the output

Claude Code acts as the orchestrator throughout. You never need to call scripts directly.

---

## Available Skills (Manual Activation)

| Skill                     | Purpose                                             |
| ------------------------- | --------------------------------------------------- |
| `/agent-collab`           | Router entrypoint (`plan`, `impl`, `review`, `all`) |
| `/plan-ping-pong`         | Plan phase only                                     |
| `/impl-pipeline`          | Implementation phase only                           |
| `/review-pipeline`        | Review phase only (parallel lenses + fix queue)     |
| `/security-lens-playbook` | Security lens operation and gate triage             |

These skills are not intended to auto-start from vague intent matching.
Use explicit skill invocation in your prompt.

---

## Skill Safety Headers

Each `SKILL.md` now includes:

1. **Frontmatter invocation control** — `disable-model-invocation: true` to enforce explicit user invocation
2. **Frontmatter tool policy** — `allowed-tools` is defined for skill execution scope
3. **Activation Policy** — explicit invocation requirement
4. **Execution Permission Header** — allowlisted script entrypoints for that skill

If a workflow needs scripts outside that allowlist, require explicit user confirmation first.

---

## Prerequisites

**Claude Code** must be installed and running. Then install and authenticate at least one of the following CLIs:

| CLI                | Install guide                                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------ |
| Gemini CLI         | [geminicli.com/docs/get-started](http://geminicli.com/docs/get-started/)                                     |
| OpenAI Codex CLI   | [developers.openai.com/codex/cli](https://developers.openai.com/codex/cli)                                   |
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

| Field                     | What to write                         |
| ------------------------- | ------------------------------------- |
| **Goal**                  | What must be achieved                 |
| **Scope**                 | What can / cannot be changed          |
| **Acceptance Criteria**   | Verifiable completion conditions      |
| **Verification Commands** | Commands that confirm success         |
| **Constraints**           | Compatibility, performance, deadlines |

The clearer your document, the better the output. Vague goals lead to vague results.

### Step 2 — Invoke the skill

In Claude Code, type:

```text
/agent-collab
```

Claude Code will read your preflight document, infer whether you need planning, implementation, or review, and run the appropriate pipeline.
If you want a phase-specific path, explicitly invoke `/plan-ping-pong`, `/impl-pipeline`, or `/review-pipeline`.

### Step 3 — Review the output

Results are written to `.tmp/agent-collab/<run-id>/`. Claude Code will summarize the outcome and surface any failures.

---

## What Happens Automatically

- **Path resolution** — CLIs installed via NVM, Homebrew, or other non-standard locations are found automatically. If a CLI cannot be located, you will be asked to run `which <tool>` and provide the result.
- **Mode selection** — Within an explicitly invoked skill, Claude Code infers `plan`, `impl`, or `review` from your request. You can also say explicitly: _"plan only"_, _"implement the approved plan"_, _"review the existing output"_.
- **Routing** — The right CLIs are selected based on task size and type. No configuration required for typical use.
- **Security lens** — Review runs can enable a dedicated security lens via runtime mode (`off|auto|always`) without extra config files.
- **Profile prompt overrides** — When a profile is selected, `prompts-src/profiles/<phase>/<profile>/<tool>/<role>.md` overrides default prompts automatically.
- **Prompt profile safety checks** — Preflight runs `prompt_profiles_audit.py` so missing profile prompts fail fast before execution.

---

## Advanced: Manual Mode Selection

If you want to control which phase runs, tell Claude Code explicitly when invoking the skill:

| What you want              | What to say                                       |
| -------------------------- | ------------------------------------------------- |
| Planning only              | `/agent-collab` + _"plan only"_                   |
| Implement an existing plan | `/agent-collab` + _"implement the approved plan"_ |
| Review existing output     | `/agent-collab` + _"review the output"_           |
| End-to-end (all phases)    | `/agent-collab` + _"run all phases"_              |

---

## Troubleshooting

**CLI not found** — The skill will print which binary is missing and what to run (`which <tool>`). Provide that output and Claude Code will retry.

**Poor output quality** — The most common cause is an underspecified preflight document. Add concrete acceptance criteria and verification commands.

**Timeout** — Large tasks may exceed default timeouts. Break the task into smaller pieces, or mention it when invoking the skill.
