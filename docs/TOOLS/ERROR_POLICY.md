# Error Policy

## Error Classes

| Class                | Description                            | Auto-Retry                   | Manual Action                     |
| -------------------- | -------------------------------------- | ---------------------------- | --------------------------------- |
| `transient`          | Network/timing issue                   | Yes (once)                   | Re-run if retry exhausted         |
| `prompt_too_large`   | Prompt exceeded limit                  | Yes (with aggressive digest) | Reduce attachments; split task    |
| `auth`               | Authentication failed                  | **Never**                    | Re-authenticate CLI               |
| `tooling`            | Binary missing or env issue            | No                           | Run `preflight.sh`, reinstall     |
| `scope_violation`    | Gate detected out-of-scope changes     | No                           | Review `scope.deny` in manifest   |
| `contract_violation` | Gate: output missing required sections | No                           | Fix prompt template or split task |
| `unknown`            | Unclassified                           | Once (optimistically)        | Check `last_failure.json`         |

## Retry Policy (Autonomous)

The dispatcher applies these rules automatically:

```
transient (count=1)       → retry once
transient (count≥2)       → stop, report
prompt_too_large (count=1) → retry with aggressive digest
prompt_too_large (count≥2) → stop, suggest task split
auth (any count)           → stop immediately
tooling (count=1)          → stop, suggest preflight.sh
tooling (count≥2)          → stop
contract_violation (any)   → stop, report gate failure details
scope_violation (any)      → stop, report violated paths
```

## Paid Call Budget Enforcement

- Every wrapper invocation increments `stats.json:paid_calls_used`
- This includes failed calls (you paid for the attempt)
- If `paid_calls_used ≥ paid_call_budget`, the dispatcher stops with exit 1
- Manual reset: edit `state/stats.json` and set `paid_calls_used` to 0

## Error Signature Normalization

Error signatures are computed by:

1. Taking the first 100 lines of stderr
2. Stripping timestamps, task IDs, UUIDs, file paths, and tokens
3. SHA256-hashing the first 500 chars of the normalized content

The same logical error gets the same signature across retries,
enabling accurate count-based policy decisions.

## Reading Failure Details

```bash
# See last failure
cat .tmp/task/<id>/state/last_failure.json

# See full stats
cat .tmp/task/<id>/state/stats.json

# Read summary (Claude-facing)
cat .tmp/task/<id>/outputs/_summary.md
```

## Wrapper Exit Code Reference

| Wrapper                  | Timeout | General Fail | Missing Binary | Missing Input |
| ------------------------ | ------- | ------------ | -------------- | ------------- |
| `gemini_headless.sh`     | 13      | 12           | 10             | 11            |
| `copilot_tool.sh`        | 33      | 32           | 30             | 31            |
| `run_codex.sh`           | 124     | 12           | 13             | 2             |
| `wait_parallel_tasks.sh` | n/a     | 1            | n/a            | 2             |

Gemini-specific: exit 14 = input error (maps from Gemini's native exit 42).
