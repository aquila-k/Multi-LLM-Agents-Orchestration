# Multi-LLM Agents Orchestration

[日本語](README.ja.md)

A task orchestration runtime that routes work across multiple LLM providers (Codex, Copilot, Gemini) with structured phases, budget controls, and full artifact traceability.

This repository provides three related tools packaged as a single CLI:

| Tool               | CLI                | Purpose                                                                      |
| ------------------ | ------------------ | ---------------------------------------------------------------------------- |
| **Orchestration**  | `agentorch collab` | Routes tasks across LLMs through plan / impl / review / harden phases        |
| **Context Memory** | `agentorch ctx`    | Persists task knowledge, decisions, and snapshots in a local SQLite database |
| **Task Registry**  | `agentorch task`   | Tracks active tasks, provider participation, and parent/child task hierarchy |

Each tool stands on its own. Use `agentorch collab` without `ctx`, use `ctx` with any agent, or use all together for the full experience.

---

## Installation

### From git (recommended for now)

```bash
# Clone and install
git clone https://github.com/aquila-k/Multi-LLM-Agents-Orchestration.git
cd Multi-LLM-Agents-Orchestration
pip install -e .

# With vector search support (optional)
pip install -e ".[vector]"

# Verify
agentorch version
agentorch doctor
```

### Using uv

```bash
uv pip install "git+https://github.com/aquila-k/Multi-LLM-Agents-Orchestration.git"
```

### Prerequisites

- Python 3.11+
- At least one LLM CLI installed and authenticated:
  - `codex` (OpenAI Codex)
  - `copilot` (GitHub Copilot CLI)
  - `gemini` (Google Gemini CLI)

---

## Quick Start

### Initialize a project

```bash
cd your-project
agentorch init                # Sets up everything: configs, context DB, agent instructions
```

This creates:

- `.agentorch/configs/` — orchestration settings (editable)
- `.contexts/local/context.db` — context memory database (gitignored)
- `.claude/skills/`, `.agent/skills/`, `.github/instructions/` — per-agent instructions
- `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — agent instruction sections appended

You can also initialize each component separately:

```bash
agentorch collab init         # Orchestration configs + Claude Code instructions only
agentorch ctx init            # Context DB + all-agent instructions only
```

### Run a workflow

```bash
agentorch collab plan   --source /path/to/goal.md
agentorch collab impl   --source /path/to/task.json
agentorch collab review --source /path/to/task.md
agentorch collab harden --source /path/to/task.md
```

### Use context memory

```bash
# Register a task
TASK_ID=$(agentorch task create --summary "Fix auth bug" --provider claude)

# Search past decisions
agentorch ctx search-memory --query "authentication" --limit 10

# Record a decision
echo '{"decision": "Use JWT", "reason": "Stateless auth needed", "semantic_hint": "JWT auth decision"}' \
  | agentorch ctx log-decision --key auth-method --scope task/$TASK_ID --stdin

# Retrieve task context
agentorch ctx get-task-context --task-id $TASK_ID --include-project
```

---

## `agentorch collab` — Orchestration Runtime

### Source File Formats

Simple Markdown or structured JSON for fine-grained control:

```markdown
# Refactor authentication module

Consolidate auth helpers into a single AuthService class.
Keep backward compatibility with existing imports.
```

```json
{
  "summary": "Refactor authentication module",
  "targets": { "path": "src/auth/" },
  "constraints": { "disallowed_paths": ["src/legacy/"] },
  "selectors": { "strategy": "COLLAB_IMPL_PATCH_FIRST" }
}
```

### Optional flags

```bash
--strategy STRATEGY_ID    # Override automatic strategy selection
--with-harden             # Combine review + harden in one pass
--dry-run                 # Validate config without calling providers
```

### Phases & Strategies

| Phase      | Strategies                                                              | Purpose                       |
| ---------- | ----------------------------------------------------------------------- | ----------------------------- |
| **plan**   | `QUESTIONS_ONLY`, `MINIMAL`, `FULL`, `THOROUGH`                         | Generate implementation plans |
| **impl**   | `BATCH_SHOT`, `PATCH_FIRST`, `SPEC_PATCH`, `FILE_BY_FILE`, `SHIELD_FIX` | Apply code changes            |
| **review** | `LITE`, `MODE_A`, `MODE_B`, `STANDARD`, `STRICT`                        | Code review + findings        |
| **harden** | `LITE`, `STANDARD`, `FULL`                                              | Security hardening            |

All strategy names are prefixed with `COLLAB_{PHASE}_` (e.g., `COLLAB_PLAN_FULL`).

### Provider Routing

The routing engine automatically selects the best provider for each step:

1. **Filter** — eliminates candidates missing required capabilities
2. **Score** — ranks by context fit, tool fit, cost, and reliability
3. **Select** — picks the highest-scoring candidate
4. **Guard** — pauses execution if cost exceeds the hard budget cap

### Budget & Approval Gates

- **Soft cap**: Reranks providers toward cheaper options
- **Hard cap**: Pauses execution with `STOP_AND_CONFIRM`
- **Resume**: `agentorch collab resume --source resume.json`

### Artifacts

Every execution produces a complete JSON audit trail:

```
.agentorch/artifacts/tasks/<task_id>/
  ├── requests/        # Input requests
  ├── routing/         # Provider selection results
  ├── prompts/         # Assembled prompt bundles
  ├── responses/       # Raw provider responses
  ├── normalized/      # Canonicalized outputs
  ├── events.jsonl     # Event log
  └── manifests/       # Lineage manifest
```

### Configuration

```
.agentorch/configs/
  ├── plan.json       # Plan phase strategies & model presets
  ├── impl.json       # Impl phase strategies
  ├── review.json     # Review phase strategies
  ├── harden.json     # Harden phase strategies
  └── providers.json  # Default provider settings
```

---

## `agentorch ctx` — Context Memory

Persistent, SQLite-backed memory for AI coding agents. Works with any agent.

### Key Commands

```bash
# Retrieve context at task start
agentorch ctx get-task-context --task-id <id> --include-project

# Save progress during work
echo '<snapshot JSON>' | agentorch ctx update-task-context --task-id <id> --expected-revision 0 --stdin

# Record a design decision
echo '<decision JSON>' | agentorch ctx log-decision --key <key> --scope task/<id> --stdin

# Search past memory
agentorch ctx search-memory --query "keyword" --limit 10

# Semantic/hybrid search (requires vector setup)
agentorch ctx search-memory --query "why was this choice made" --mode hybrid

# Health check
agentorch ctx doctor
```

### Vector Search (Optional)

FTS5 keyword search works out of the box. Optional vector search adds semantic capabilities:

| Profile            | Requirements                            | Search modes                        |
| ------------------ | --------------------------------------- | ----------------------------------- |
| **core** (default) | Python 3.11+, SQLite                    | `fts` only                          |
| **vector-enabled** | Python 3.12+, `sqlite-vec`, `fastembed` | `fts`, `semantic`, `hybrid`, `auto` |

```bash
pip install -e ".[vector]"           # Install vector dependencies
agentorch ctx setup-vector           # Build the vector index
agentorch ctx vector-doctor          # Verify setup
agentorch ctx sync-vector-index      # Keep index up to date after writes
```

### Entry Types

| Type              | Scope        | Purpose                          |
| ----------------- | ------------ | -------------------------------- |
| `project_profile` | project      | Goals, constraints, architecture |
| `task_snapshot`   | task/session | Current plan, progress, blockers |
| `decision`        | any          | Design decisions with rationale  |
| `episode`         | task         | Phase observations and lessons   |
| `procedural_rule` | any          | Reusable process rules           |

---

## `agentorch task` — Task Registry

Tracks active tasks across agents and sessions.

```bash
# Create a task
TASK_ID=$(agentorch task create --summary "Refactor auth" --provider claude)

# Check current active task (useful after context compression)
agentorch task current

# Create a child task (for sub-goals or delegated work)
agentorch task create --summary "Plan: refactor auth" --parent $TASK_ID --provider claude

# List tasks
agentorch task list --status active

# Mark completed
agentorch task status $TASK_ID --set completed

# Find stale tasks (active but process gone)
agentorch task check
```

---

## Agent Instructions

`agentorch init` automatically generates instruction files for each agent:

| Agent       | Files generated                                                                 |
| ----------- | ------------------------------------------------------------------------------- |
| Claude Code | `.claude/skills/agentorch-{collab,ctx}/`, `.claude/rules/`, `CLAUDE.md` section |
| Codex       | `.agent/skills/agentorch-ctx/`, `AGENTS.md` section                             |
| Copilot     | `.github/instructions/agentorch-ctx.instructions.md`                            |
| Gemini      | `GEMINI.md` section                                                             |

Orchestration (`collab`) is Claude Code exclusive. Context memory (`ctx`) is available to all agents.

---

## Project Structure

```
agentorch_ctx/              # Python package (installed via pip)
  ├── __main__.py           # CLI: agentorch version|doctor|init|collab|ctx|task
  ├── runtime/              # Task runner, routing, providers, artifacts
  ├── contexts/             # Context management runtime
  │   ├── sql/              # Migration scripts
  │   ├── schemas/          # Entry payload schemas
  │   └── vector/           # Vector search extension (optional)
  ├── task_registry/        # Task tracking database
  ├── configs/              # Internal defaults + user config templates
  ├── templates/            # Agent instruction templates (generated by init)
  ├── schemas/              # JSON schemas for artifacts & configs
  └── tests/                # Unit, integration, regression tests

.agentorch/                 # Created by `agentorch init` (project-specific)
  ├── configs/              # User-editable phase & provider configs
  ├── artifacts/            # Task artifacts (gitignored)
  └── state/                # Runtime state (gitignored)

.contexts/                  # Created by `agentorch ctx init` (project-specific)
  ├── run                   # Backward-compatible wrapper script
  └── local/                # gitignored: DB, config, vector_python_path
```

## License

MIT
