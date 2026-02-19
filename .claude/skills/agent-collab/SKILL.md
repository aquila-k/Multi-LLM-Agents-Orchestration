---
name: agent-collab
description: Unified multi-LLM orchestrator for planning, implementation, and review workflows via a single runner. Invoke manually with a natural-language instruction, infer intent in this SKILL.md, then execute the matching mode.
disable-model-invocation: true
argument-hint: "<instruction> [--preflight <file>] [--goal <text>] [--task-dir <dir>]"
allowed-tools: Bash(./scripts/agent-cli/*), Bash(mkdir *), Bash(cp *), Bash(cat *), Bash(head *), Bash(date *), Bash(ls *), Read, Grep, Glob
compatibility: Requires bash, python3, and runnable Gemini/Codex/Copilot CLIs.
---

# Agent Collaboration (Unified Entry)

This skill is manual-only (`disable-model-invocation: true`).
Default behavior: infer intent and select one mode from `plan|impl|review`.
Use `scripts/agent-cli/run_agent_collab.sh` with the selected explicit mode.
Use `--mode all` only when the user explicitly requests an end-to-end run.

## Intent Routing (in SKILL.md only)

Infer mode from the user request before executing scripts:

- Plan:
  - Intent class: planning, requirement shaping, scoping, decomposition, design preparation
  - Run: `--mode plan`
- Impl:
  - Intent class: implement or modify code according to an agreed specification
  - Run: `--mode impl`
- Review:
  - Intent class: review, test, verify, validate, or audit existing implementation
  - Run: `--mode review`

Rules:

1. Do not delegate intent understanding to scripts.
2. Do not hardcode keyword routing in scripts.
3. Default priority: `review` > `plan` > `impl`.
4. If intent is ambiguous, ask one short clarification question.

## Required Conditions by Mode

- `plan`: `--preflight <file>`
- `impl`:
  - Existing task packet: `--task-dir <dir>` with `manifest.yaml`, or
  - Bootstrap from approved plan: `--plan-file <file> --goal "<text>"`
- `review`:
  - Existing task packet: `--task-dir <dir>`, or
  - Direct inputs: `--context-pack <file> --impl-report <file>`
- `all`: `--preflight <file> --goal "<text>"`

## Execution Commands

Plan:

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode plan \
  --preflight .tmp/agent-collab/preflight.md
```

Impl from approved plan:

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode impl \
  --plan-file .tmp/agent-collab/20260219-120000/plan/final.md \
  --goal "Implement the approved plan"
```

Review from existing task packet:

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode review \
  --task-dir .tmp/task/20260218-001
```

All phases:

```bash
./scripts/agent-cli/run_agent_collab.sh \
  --mode all \
  --preflight .tmp/agent-collab/preflight.md \
  --goal "Implement the approved plan"
```

## Quick Start (Plan Input)

```bash
mkdir -p .tmp/agent-collab
cp .claude/skills/agent-collab/preflight.template.md .tmp/agent-collab/preflight.md
# edit .tmp/agent-collab/preflight.md
```

## Output Layout

- Plan: `.tmp/agent-collab/<task-id>/plan/`
- Implementation: `.tmp/agent-collab/<task-id>/task/`
- Review: `.tmp/agent-collab/<task-id>/review/`

## Skill Resources

- `preflight.template.md`
- `stage1_draft.prompt.md`
- `stage2_enrich.prompt.md`
- `stage3_crossreview.prompt.md`
- `stage4_consolidate.prompt.md`
