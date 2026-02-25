# Config V2 Snapshot

> Auto-generated summary of the current configs-v2 state.

- config_root: `/Users/kosugiakira/Multi-LLM-Agents-Orchestration/configs-v2`
- version: `2`

## Skills

### `plan`

- source: `configs-v2/skills/plan.yaml`
- default_method_ids: `["PLAN-METHOD-A"]`
- methods:
  - `PLAN-METHOD-A` enabled=`True` gate_profile=`standard` steps=`["parse_task", "gemini_draft", "codex_analyze", "copilot_analyze", "synthesize", "copilot_draft", "finalize"]` allowed_tools=`["gemini", "copilot"]`
  - `PLAN-METHOD-B` enabled=`True` gate_profile=`standard` steps=`["parse_task", "gemini_draft", "codex_analyze", "copilot_analyze", "synthesize", "codex_enrich", "gemini_research", "finalize"]` allowed_tools=`["gemini", "codex", "copilot"]`
  - `PLAN-METHOD-HYBRID` enabled=`True` gate_profile=`strict` steps=`["parse_task", "gemini_draft", "codex_analyze", "copilot_analyze", "synthesize", "codex_enrich", "gemini_research", "copilot_draft", "finalize"]` allowed_tools=`["gemini", "codex", "copilot"]`
- step_defaults:
  - `parse_task` — Parse and organize task requirements (Gemini) tool=`gemini` mode=`normal` web_research_mode=`off`
  - `gemini_draft` — Generate initial plan draft (Gemini) tool=`gemini` mode=`normal` web_research_mode=`off`
  - `codex_analyze` — Analyze feasibility and technical constraints (Codex, web search enabled) tool=`codex` mode=`normal` web_research_mode=`codex_explicit`
  - `copilot_analyze` — Gather supplementary analysis and references (Copilot, MCP tools enabled) tool=`copilot` mode=`normal` web_research_mode=`copilot_mcp`
  - `synthesize` — Merge and review analysis results from multiple agents (Gemini) tool=`gemini` mode=`analysis_only` web_research_mode=`off`
  - `codex_enrich` — Enrich plan with technical details and refinements (Codex, web search enabled) tool=`codex` mode=`normal` web_research_mode=`codex_explicit`
  - `gemini_research` — Gather up-to-date information via web research (Gemini) tool=`gemini` mode=`normal` web_research_mode=`gemini_auto`
  - `copilot_draft` — Generate plan draft (Copilot, MCP tools enabled) tool=`copilot` mode=`normal` web_research_mode=`copilot_mcp`
  - `finalize` — Produce and format the final plan document (Gemini) tool=`gemini` mode=`normal` web_research_mode=`off`

### `impl`

- source: `configs-v2/skills/impl.yaml`
- default_method_ids: `["IMPL-PROFILE-SAFE"]`
- methods:
  - `IMPL-PROFILE-SAFE` enabled=`True` gate_profile=`standard` steps=`["read_context", "research", "implement", "review_draft", "fix", "summarize"]` allowed_tools=`["gemini", "codex"]`
  - `IMPL-PROFILE-ONE_SHOT` enabled=`True` gate_profile=`standard` steps=`["read_context", "research", "implement", "review_draft", "fix", "summarize"]` allowed_tools=`["gemini", "copilot", "codex"]`
  - `IMPL-PROFILE-DESIGN_ONLY` enabled=`True` gate_profile=`minimal` steps=`["read_context", "research", "implement", "summarize"]` allowed_tools=`["gemini"]`
  - `IMPL-S1` enabled=`True` gate_profile=`standard` steps=`["implement"]` allowed_tools=`["codex"]`
  - `IMPL-S2` enabled=`True` gate_profile=`standard` steps=`["implement"]` allowed_tools=`["gemini"]`
  - `IMPL-S3` enabled=`True` gate_profile=`standard` steps=`["implement"]` allowed_tools=`["copilot"]`
  - `IMPL-S4` enabled=`True` gate_profile=`strict` steps=`["implement", "fix"]` allowed_tools=`["codex", "gemini"]`
  - `IMPL-S5` enabled=`True` gate_profile=`strict` steps=`["implement", "verify", "fix"]` allowed_tools=`["codex"]`
- step_defaults:
  - `read_context` — Load existing code and specifications as context (Gemini) tool=`gemini` mode=`analysis_only` web_research_mode=`off`
  - `research` — Gather reference materials and prior implementations via web search (Codex) tool=`codex` mode=`normal` web_research_mode=`codex_explicit`
  - `implement` — Code implementation — main step (Codex) tool=`codex` mode=`normal` web_research_mode=`codex_explicit`
  - `review_draft` — Self-review of implementation — detect bugs and oversights (Codex) tool=`codex` mode=`normal` web_research_mode=`off`
  - `fix` — Apply fixes for review findings (Codex) tool=`codex` mode=`normal` web_research_mode=`off`
  - `verify` — Final validation and test execution (Codex) tool=`codex` mode=`normal` web_research_mode=`off`
  - `summarize` — Generate implementation summary and changelist (Gemini) tool=`gemini` mode=`analysis_only` web_research_mode=`off`

### `review`

- source: `configs-v2/skills/review.yaml`
- default_method_ids: `["REVIEW-MODE-A", "REVIEW-PRESET-STANDARD", "REVIEW-PROFILE-REVIEW_ONLY"]`
- methods:
  - `REVIEW-MODE-A` enabled=`True` gate_profile=`finding-first` steps=`["read_context", "gemini_review_web", "gemini_review", "codex_review_web", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex", "copilot"]`
  - `REVIEW-MODE-B` enabled=`True` gate_profile=`standard` steps=`["read_context", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex"]`
  - `REVIEW-PRESET-LITE` enabled=`True` gate_profile=`minimal` steps=`["read_context", "apply_fixes", "consolidate"]` allowed_tools=`["gemini"]`
  - `REVIEW-PRESET-STANDARD` enabled=`True` gate_profile=`standard` steps=`["read_context", "gemini_review_web", "gemini_review", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex"]`
  - `REVIEW-PRESET-STRICT` enabled=`True` gate_profile=`strict` steps=`["read_context", "gemini_review_web", "gemini_review", "codex_review_web", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex", "copilot"]`
  - `REVIEW-PROFILE-REVIEW_CROSS` enabled=`True` gate_profile=`standard` steps=`["read_context", "gemini_review_web", "gemini_review", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex", "copilot"]`
  - `REVIEW-PROFILE-POST_IMPL_REVIEW` enabled=`True` gate_profile=`standard` steps=`["read_context", "gemini_review_web", "gemini_review", "codex_review_web", "apply_fixes", "verify", "consolidate"]` allowed_tools=`["gemini", "codex"]`
  - `REVIEW-PROFILE-REVIEW_ONLY` enabled=`True` gate_profile=`minimal` steps=`["read_context", "apply_fixes", "consolidate"]` allowed_tools=`["gemini"]`
  - `REVIEW-PROFILE-CODEX_ONLY` enabled=`True` gate_profile=`minimal` steps=`["read_context", "apply_fixes", "consolidate"]` allowed_tools=`["codex"]`
- step_defaults:
  - `read_context` — Load reviewed code and implementation summary as context (Gemini) tool=`gemini` mode=`analysis_only` web_research_mode=`off`
  - `gemini_review_web` — Gemini review — reference latest best practices via web search tool=`gemini` mode=`analysis_only` web_research_mode=`gemini_auto`
  - `gemini_review` — Gemini standard review — evaluate code quality, design, and security tool=`gemini` mode=`analysis_only` web_research_mode=`off`
  - `codex_review_web` — Codex review — evaluate with implementation pattern references via web search tool=`codex` mode=`analysis_only` web_research_mode=`codex_explicit`
  - `apply_fixes` — Apply fixes for review findings (Codex) tool=`codex` mode=`normal` web_research_mode=`off`
  - `verify` — Post-fix validation and test execution (Codex) tool=`codex` mode=`normal` web_research_mode=`off`
  - `consolidate` — Merge all review results and produce final report (Gemini) tool=`gemini` mode=`analysis_only` web_research_mode=`off`

## Servants

### `codex`

- source: `configs-v2/servants/codex.yaml`
- default_model: `gpt-5.3-codex`
- allowed_models: `["gpt-5.3-codex", "gpt-5.2-codex", "gpt-5-codex", "gpt-5.3-codex-spark"]`
- wrapper_defaults: `{"effort": "high", "timeout_ms": 600000, "timeout_mode": "wait_done"}`
- web_modes: `["off", "codex_explicit"]`

### `gemini`

- source: `configs-v2/servants/gemini.yaml`
- default_model: `pro`
- allowed_models: `["auto", "pro", "flash", "flash-lite", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-pro-preview"]`
- wrapper_defaults: `{"approval_mode": "default", "sandbox": false, "timeout_ms": 600000, "timeout_mode": "wait_done"}`
- web_modes: `["off", "gemini_auto"]`

### `copilot`

- source: `configs-v2/servants/copilot.yaml`
- default_model: `claude-sonnet-4.6`
- allowed_models: `["auto", "claude-sonnet-4.6", "claude-opus-4.6", "claude-sonnet-4.5", "claude-opus-4.5", "claude-haiku-4.5", "gpt-5-codex", "gpt-5.2-codex", "gpt-5.1-codex", "gpt-5.1-codex-mini", "GPT-5-mini"]`
- wrapper_defaults: `{"timeout_ms": 600000, "timeout_mode": "wait_done"}`
- web_modes: `["off", "copilot_mcp"]`

## Policies

### `routing`

- source: `configs-v2/policies/routing.yaml`
- stop_policy.conditions: `[{"impact_surface": "high", "confidence": "low", "action": "STOP_AND_CONFIRM"}, {"reason_codes_contain": "BLOCK", "action": "STOP_AND_CONFIRM"}, {"strict_evidence_violation": true, "action": "STOP_AND_CONFIRM"}]`
- stop_policy.on_stop: `write_reason_codes_to_routing_result`
- confidence_policy: `{"values": ["high", "medium", "low"], "default": "medium"}`
- hard_stop_reason_map keys: `["BLOCK_MISSING_PLAN", "BLOCK_NO_EVIDENCE", "BLOCK_SCHEMA_INVALID", "BLOCK_SCOPE_VIOLATION", "BLOCK_SESSION_MISMATCH", "ROUTING_NON_DETERMINISTIC"]`
- reproducibility_policy: `{"deterministic_required": true, "on_mismatch": "record_ROUTING_NON_DETERMINISTIC_and_stop"}`
- route_decider_policy: `{"phase_prompt_paths": {"plan": "prompts-src/routing/plan-route-decider.md", "impl": "prompts-src/routing/impl-route-decider.md", "review": "prompts-src/routing/review-route-decider.md"}, "schema_version": 2}`

### `review_parallel`

- source: `configs-v2/policies/review_parallel.yaml`
- config: `{"version": 2, "mode": "finding-first", "join_barrier": "required", "apply_order": "sequential", "worker_output_mode": "analysis_only", "merge_required": true, "artifacts": {"findings_dir": "review_findings", "merged": "review_merged_findings.json", "queue": "review_fix_queue.json"}}`

### `web_evidence`

- source: `configs-v2/policies/web_evidence.yaml`
- config: `{"version": 2, "strictness": "strict", "required_fields": ["evidence_id", "url", "accessed_at", "claim_summary"], "reason_code_map": {"WEB_EVIDENCE_MISSING": "Finding uses external evidence but evidence_ids is empty", "WEB_EVIDENCE_UNVERIFIABLE": "Referenced evidence_id not found in web-evidence.json", "WEB_EVIDENCE_STALE": "Evidence accessed_at older than allowed threshold"}, "gate_action_on_violation": "reject_and_stop"}`
