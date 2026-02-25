Run a strict implementation-oriented review.

Focus:

1. behavior-affecting defects
2. unsafe assumptions in edge cases
3. fragile or non-deterministic logic
4. security-sensitive mistakes in execution paths

Rules:

1. attach concrete code evidence
2. provide minimal patch direction
3. flag verification commands needed after fixes
4. keep recommendations scoped to affected files

Output sections:

1. Findings
2. Test gaps
3. Breaking changes
4. Minimal fix
