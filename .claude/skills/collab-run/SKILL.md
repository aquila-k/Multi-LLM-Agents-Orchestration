---
name: collab-run
description: Run plan, impl, review, or harden tasks through the collab runtime. Use when the user asks to plan, implement, review, or harden code and you need to delegate to an external LLM provider (gemini, codex, copilot). Accepts a structured JSON task file or a freeform markdown goal.
compatibility: Requires python3, and at least one of gemini/codex/copilot installed. Run from the project root.
metadata:
  version: "1.0"
---

## Overview

This skill invokes `python3 -m collab <intent> --source <file>` to dispatch work to external LLM provider CLIs (gemini, codex, copilot). The runtime is fully self-contained:

- **Root is auto-detected** from the script's own location — never pass `--root`.
- **All task artifacts** land under `collab/artifacts/tasks/<task_id>/` within the project.
- **Structured options** are embedded in a JSON source file, not scattered across CLI flags.

## Invocation

Always use the **`collab/run` wrapper script**, not `python3 -m collab` directly.
The wrapper resolves the repo root from its own location and sets `PYTHONPATH` automatically,
so it works correctly regardless of your current working directory.

```bash
./collab/run <intent> --source /absolute/path/to/source.md
```

Use **absolute paths** for `--source` to avoid any CWD-dependent resolution.

## Step-by-step

### Step 1 — Create a task source file

For simple cases, write a markdown file:

```markdown
# Refactor the authentication module

Consolidate the three auth helpers in src/auth/ into a single AuthService class.
Keep backward compatibility with existing callers.
```

For structured cases (explicit strategy, targets, constraints), write a JSON file:

```json
{
  "summary": "Refactor the authentication module",
  "selectors": {
    "strategy": "COLLAB_IMPL_SAFE"
  },
  "targets": {
    "path": "src/auth/"
  },
  "constraints": {
    "disallowed_paths": ["src/auth/legacy/"]
  },
  "phase_options": {
    "with_harden": false
  }
}
```

Save the file anywhere on disk (e.g., `/tmp/task.json` or inside the project).

### Step 2 — Run the command

```bash
./collab/run plan   --source /absolute/path/to/task.md
./collab/run impl   --source /absolute/path/to/task.json
./collab/run review --source /absolute/path/to/task.md
./collab/run harden --source /absolute/path/to/task.md
./collab/run review --source /absolute/path/to/task.md --with-harden
```

`--dry-run` skips actual provider calls (useful for verifying artifact layout):

```bash
./collab/run plan --source /tmp/task.md --dry-run
```

### Step 3 — Read the output

A successful run prints:

```
task_id:   my-task-20260308T120000Z
phases:    plan
status:    partial
artifacts: /path/to/project/collab/artifacts/tasks/my-task-20260308T120000Z
run_log:   /path/to/project/collab/artifacts/tasks/my-task-20260308T120000Z/phase-runs/phase-run.json
```

`status: partial` is normal for plan/review/harden (no files applied). `status: blocked` means stop-and-confirm triggered.

To read what the provider produced:

```bash
# Shell digest (concise summary of what happened)
cat collab/artifacts/tasks/<task_id>/shell-digests/shell-digest-<phase>-*.json

# Full provider response
cat collab/artifacts/tasks/<task_id>/responses/response-<phase>-*.json

# Raw provider output text
cat collab/artifacts/tasks/<task_id>/adapter/raw-output-<phase>-*.txt
```

## Source file options reference

| Field                              | Type   | Description                                                       |
| ---------------------------------- | ------ | ----------------------------------------------------------------- |
| `summary`                          | string | Task description (used as task ID seed)                           |
| `selectors.strategy`               | string | Routing strategy ID (e.g. `COLLAB_PLAN_FULL`, `COLLAB_IMPL_SAFE`) |
| `targets.path`                     | string | Primary target directory or file for impl/review                  |
| `constraints.disallowed_paths`     | list   | Paths the provider must not modify                                |
| `phase_options.with_harden`        | bool   | Compose review+harden in one run (review only)                    |
| `phase_options.budget_profile_ref` | string | Budget profile (default: `budget-bootstrap`)                      |

## Handling STOP_AND_CONFIRM

If the task has approval gates, the runtime prints:

```
STOP_AND_CONFIRM: operator approval required before execution proceeds.
task_id:   <id>
state:     collab/state/tasks/<id>/controller-state.json
```

To resume after the user approves, create a JSON resume payload:

```json
{
  "task_id": "<the-blocked-task-id>",
  "summary": "Resuming after approval",
  "selectors": { "approval_continuation": "approved" }
}
```

Then run:

```bash
./collab/run resume --source /tmp/resume.json
```

## Common strategy IDs

| Intent | Strategy              | Description                    |
| ------ | --------------------- | ------------------------------ |
| plan   | `COLLAB_PLAN_FULL`    | Full multi-agent plan pipeline |
| plan   | `COLLAB_PLAN_MINIMAL` | Single-agent quick plan        |
| impl   | `COLLAB_IMPL_SAFE`    | Analyze → implement → verify   |
| review | `COLLAB_REVIEW_FULL`  | Multi-lens review with signoff |
| harden | `COLLAB_HARDEN_FULL`  | Threat model + fix + AI review |

Omit `selectors.strategy` to let the runtime auto-select based on task complexity.

---

## Workflow Continuity Rules (MANDATORY)

### Rule 1 — plan → impl → review → harden は必ず同一タスクIDで実行する

`./collab/run <intent> --source <file>` はタイムスタンプベースで毎回新しい `task_id` を生成する。
**plan の後に impl を別の `--source` で起動すると別タスクIDになり、artifact チェックで失敗する。**

`COLLAB_IMPL_PATCH_FIRST` などの strategy は `plans/` を `requiredArtifacts` に持つ。
この設定は設計上正しく、`optional` に変更してはならない。

### Rule 2 — フェーズ継続は resume JSON で行う

plan 完了後、impl を起動するには **resume JSON** を使い、同じ `task_id` に進む:

```json
{
  "task_id": "<plan で出力された task_id>",
  "summary": "...",
  "selectors": {
    "approval_continuation": "approved",
    "strategy": "COLLAB_IMPL_PATCH_FIRST",
    "phase": "impl",
    "step": "I0_analyze"
  }
}
```

```bash
./collab/run resume --source /tmp/resume-impl.json
```

同様に impl → review → harden も resume で継続する。

### Rule 3 — 途中フェーズから単独実行する場合（例外）

前フェーズの成果物が揃っていれば、途中フェーズから単独実行できる:

1. `collab/artifacts/tasks/<task_id>/` を手動で作成する
2. 前フェーズの出力に相当するファイルをタスクディレクトリ内に配置する
   例: impl から始める場合は `<task_root>/plans/` に plan report を置く
3. 成果物の構造・品質は前フェーズの出力に準じること

これは例外的な運用。**原則は resume フローによる同一タスク継続。**
