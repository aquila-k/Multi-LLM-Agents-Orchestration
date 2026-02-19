# Context Pack Schema

This file defines the required section headers for a valid Context Pack.
`gate.sh` uses these headers to validate the brief role output.

## Required Sections (must appear as ## headings)

- `## 0. Goal`
- `## 1. Non-goals`
- `## 2. Scope`
- `## 3. Acceptance Criteria`
- `## 4. Fixed Decisions`
- `## 5. Files to Read`
- `## 6. Prohibited Actions`
- `## 7. Current State`
- `## 8. Open Questions`
- `## 9. Change History`

## Validation Rules

1. All 10 sections (0–9) must be present.
2. Each section must have at least one non-empty line of content.
3. The "Verify Commands" subsection under section 3 must include a fenced code block.
4. Section 4 (Fixed Decisions) must list at least one decision.
5. Section 6 (Prohibited Actions) must list at least one prohibition.

## Gate Check Command (for reference)

The gate checks these headers are present in the Updated Context Pack section
of the brief output using `grep -qF`:

```bash
for section in "## 0. Goal" "## 1. Non-goals" "## 2. Scope" \
               "## 3. Acceptance" "## 4. Fixed" "## 5. Files" \
               "## 6. Prohibited" "## 7. Current" "## 8. Open" "## 9. Change"; do
  grep -qF "$section" <output-file> || echo "MISSING: $section"
done
```
