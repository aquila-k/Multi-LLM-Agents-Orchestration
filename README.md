# Multi-LLM Agents Orchestration

[日本語](docs/README/README.ja.md)

A task orchestration runtime that routes work across multiple LLM providers (Codex, Copilot, Gemini) with structured phases, budget controls, and full artifact traceability.

This repository contains two independent tools that can also work together:

| Tool             | Purpose                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| **`collab/`**    | Orchestration runtime — routes tasks across LLMs through plan → impl → review → harden phases  |
| **`.contexts/`** | Context manager — persists task knowledge, decisions, and snapshots in a local SQLite database |

Each tool stands on its own. Use `collab/` without `.contexts/`, use `.contexts/` with any agent, or use both together for the full experience.

---

## `collab/` — Orchestration Runtime

### Prerequisites

- Python 3.13+
- At least one LLM CLI installed and authenticated:
  - `codex` (OpenAI Codex)
  - `copilot` (GitHub Copilot CLI)
  - `gemini` (Google Gemini CLI)

### Quick Start

**Write a goal:**

```markdown
# Refactor authentication module

Consolidate auth helpers into a single AuthService class.
Keep backward compatibility with existing imports.
```

Save as `goal.md`, then run:

```bash
./collab/run plan --source /path/to/goal.md
./collab/run impl --source /path/to/goal.md
```

The runtime selects providers, assembles prompts, executes steps, and stores artifacts automatically.

### Optional flags

```bash
--strategy STRATEGY_ID    # Override automatic strategy selection
--with-harden             # Combine review + harden in one pass
--dry-run                 # Validate config without calling providers
```

### Source File Formats

Simple Markdown or structured JSON for fine-grained control:

```json
{
  "summary": "Refactor authentication module",
  "targets": { "path": "src/auth/" },
  "constraints": { "disallowed_paths": ["src/legacy/"] },
  "selectors": { "strategy": "COLLAB_IMPL_PATCH_FIRST" }
}
```

### Phases & Strategies

Each phase has predefined strategies — multi-step workflows optimized for different scenarios.

| Phase      | Strategies                                                              | Purpose                       |
| ---------- | ----------------------------------------------------------------------- | ----------------------------- |
| **plan**   | `QUESTIONS_ONLY`, `MINIMAL`, `FULL`, `THOROUGH`                         | Generate implementation plans |
| **impl**   | `BATCH_SHOT`, `PATCH_FIRST`, `SPEC_PATCH`, `FILE_BY_FILE`, `SHIELD_FIX` | Apply code changes            |
| **review** | `LITE`, `MODE_A`, `MODE_B`, `STANDARD`, `STRICT`                        | Code review + findings        |
| **harden** | `LITE`, `STANDARD`, `FULL`                                              | Security hardening            |

All strategy names are prefixed with `COLLAB_{PHASE}_` (e.g., `COLLAB_PLAN_FULL`).

### Provider Routing

The routing engine automatically selects the best provider for each step:

1. **Filter** — eliminates candidates missing required capabilities (session resume, JSON schema, etc.)
2. **Score** — ranks by context fit, tool fit, cost, and reliability
3. **Select** — picks the highest-scoring candidate
4. **Guard** — pauses execution if cost exceeds the hard budget cap

Providers and model presets are configured in `collab/configs/user/`.

### Budget & Approval Gates

- **Soft cap**: Reranks providers toward cheaper options
- **Hard cap**: Pauses execution with `STOP_AND_CONFIRM`
- **Resume**: Create a resume JSON with `approval_continuation: approved` and run `./collab/run resume --source resume.json`

### Artifacts

Every execution produces a complete JSON audit trail:

```
collab/artifacts/tasks/<task_id>/
  ├── requests/        # Input requests
  ├── routing/         # Provider selection results
  ├── prompts/         # Assembled prompt bundles
  ├── responses/       # Raw provider responses
  ├── normalized/      # Canonicalized outputs
  ├── checkpoints/     # Git state snapshots
  ├── events.jsonl     # Event log
  └── manifests/       # Lineage manifest
```

Artifacts are project-specific runtime data, excluded from the repository via `.gitignore`.

### Configuration

```
collab/configs/user/
  ├── plan.json       # Plan phase strategies & model presets
  ├── impl.json       # Impl phase strategies
  ├── review.json     # Review phase strategies
  ├── harden.json     # Harden phase strategies
  └── providers.json  # Default provider settings
```

Each config defines `$presets` (model shortcuts) and `strategies` (step sequences). The `default` key sets the fallback preset.

---

## `.contexts/` — Context Manager

**Works independently** from `collab/`. Drop it into any project to give your AI agents persistent memory across sessions.

### Setup

```bash
.contexts/run init
```

Creates `.contexts/local/` (git-ignored) with a SQLite database.

### Key Commands

```bash
# Retrieve context at task start
.contexts/run get-task-context --task-id <id> --include-project --format markdown

# Save progress during work
.contexts/run update-task-context --task-id <id> --expected-revision 0 < snapshot.json

# Record a design decision
.contexts/run log-decision --key <key> --scope task/<id> < decision.json

# Search past memory (keyword)
.contexts/run search-memory --query "keyword" --limit 10

# Search past memory (semantic or hybrid — requires vector search to be set up)
.contexts/run search-memory --query "keyword" --mode hybrid --limit 10

# Maintenance
.contexts/run doctor          # Health check
.contexts/run render-context  # Render markdown summary for a scope
```

### Vector Search (Optional)

`.contexts/` ships with **FTS5 keyword search** out of the box. An optional **vector (semantic) search** layer can be added without affecting the existing database or any existing commands.

| Profile | Requirements | Search modes |
| --- | --- | --- |
| **core** (default) | Python 3.8+, SQLite | `fts` only |
| **vector-enabled** | Python 3.12, `sqlite-vec`, `fastembed` | `fts`, `semantic`, `hybrid`, `auto` |

#### Setting up the vector-enabled profile

`.contexts/run` is a single unified entry point. Once vector search is set up, it is used automatically — no separate command or entry point is needed.

```bash
# See what will be installed (disk/time warnings, no changes made)
.contexts/run setup-vector --dry-run

# Install locally (creates .venv-vector/ next to .contexts/)
.contexts/run setup-vector

# Install globally to share dependencies across projects (~400 MB saved per project)
.contexts/run setup-vector --global

# Install to a custom location
.contexts/run setup-vector --venv-path /path/to/venv

# Verify setup
.contexts/run vector-doctor
```

Notes:

- First run downloads ~90 MB embedding model to `~/.cache/huggingface/`
- Total disk: ~400 MB packages + ~90 MB model weights
- Initial index build takes 1–3 minutes
- FTS keyword search works immediately without any setup
- With `--global`, Python packages are shared across repos; the vector index stays project-local

#### Using vector search

After setup, all search commands use the same `.contexts/run` entry point:

```bash
# Auto-select best mode (hybrid when vector available, fts otherwise)
.contexts/run search-memory --query "why was this choice made" --mode auto

# Semantic search (meaning-based, language-independent)
.contexts/run search-memory --query "authentication approach" --mode semantic

# Hybrid search (FTS + semantic, merged via reciprocal rank fusion)
.contexts/run search-memory --query "database schema decision" --mode hybrid

# Keep the index up to date after writes
.contexts/run sync-vector-index
```

If `semantic` or `hybrid` is requested but vector search is not set up, the response falls back to FTS and includes a `setup_hint` field.

### Using `.contexts/` with Any Agent

Add a few lines to your agent's instruction file to enable automatic context retrieval:

**Claude** (`CLAUDE.md` or `.github/copilot-instructions.md`):

```markdown
## Context

Before starting work: `.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown`
After completing work: `.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json`
```

**Codex** (`.codex/instructions.md`):

```markdown
Before starting any task, retrieve context:
.contexts/run get-task-context --task-id <TASK_ID> --include-project
After completing work, save progress:
.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json
```

**Gemini** (`GEMINI.md`):

```markdown
On task start: `.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown`
On task end: `.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json`
```

### Entry Types

| Type              | Scope        | Purpose                          |
| ----------------- | ------------ | -------------------------------- |
| `project_profile` | project      | Goals, constraints, architecture |
| `task_snapshot`   | task/session | Current plan, progress, blockers |
| `decision`        | any          | Design decisions with rationale  |
| `episode`         | task         | Phase observations and lessons   |
| `procedural_rule` | any          | Reusable process rules           |

### Scoping Hierarchy

```
project → branch → task → session
```

More specific scopes inherit from broader ones. Entries at `task`/`session` scope auto-activate; `project`/`branch` scope requires operator approval.

---

## Project Structure

```
collab/                     # Orchestration runtime (standalone)
  ├── run                   # CLI entry point
  ├── runtime/              # Task runner, routing, providers, artifacts
  ├── configs/user/         # User-editable phase configs
  ├── schemas/              # JSON schemas for artifacts & configs
  ├── docs/                 # Design policy documents
  └── tests/                # Unit, integration, stub-e2e, regression

.contexts/                  # Context manager (standalone)
  ├── run                   # Unified CLI entry point (auto-detects venv, falls back to python3)
  ├── runtime/
  │   └── vector/           # Vector search extension (optional)
  ├── sql/                  # Migration scripts
  ├── schemas/              # Entry payload schemas
  └── local/                # git-ignored; DB, config, and vector_python_path live here

.venv-vector/               # git-ignored; optional repo-local vector venv (created by setup-vector)
```

## License

MIT
