from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PHASE_ROLE_INSTRUCTIONS = {
    "plan": (
        "You are a planning assistant. Analyze the codebase and produce a "
        "structured implementation plan."
    ),
    "impl": (
        "You are an implementation assistant. Implement the requested changes "
        "as described."
    ),
    "review": "You are a code review assistant. Analyze the code and report findings.",
    "harden": (
        "You are a security hardening assistant. Identify and fix security issues."
    ),
}

_PHASE_GUIDANCE = {
    "plan": (
        "Produce a concrete implementation plan with assumptions, impacted files, "
        "ordered steps, and validation checks."
    ),
    "impl": (
        "Implement requested changes in scope, explain what changed, and include "
        "verification notes."
    ),
    "review": (
        "Report findings ordered by severity, include exact file references when "
        "possible, and call out risks/regressions."
    ),
    "harden": (
        "Identify security weaknesses, propose or apply mitigations, and explain "
        "residual risk."
    ),
}

_DEFAULT_ROLE = "You are a software engineering assistant. Solve the task accurately."
_DEFAULT_PHASE_GUIDANCE = (
    "Provide a clear and structured response with assumptions, actions, and results."
)

_GEMINI_TOKEN_LIMIT = 32_000
_CODEX_TOKEN_LIMIT = 100_000
_COPILOT_BYTE_LIMIT = 48_000
_MARKDOWN_SOURCE_LIMIT = 3_000
_JSON_SOURCE_FIELD_LIMIT = 1_500
_PRIOR_PHASE_SNIPPET_LIMIT = 2_000
_PRIOR_STEP_SNIPPET_LIMIT = 1_500
_STORED_CONTEXT_CLIP = 2_000
_STORED_CONTEXT_BLOCKERS_MAX = 3
_STORED_CONTEXT_DECISIONS_MAX = 5

_OUTPUT_INSTRUCTION_GEMINI = (
    "Output your response as plain text. Use markdown headings for structure."
)
_OUTPUT_INSTRUCTION_CODEX_IMPL = (
    "Output changes as unified diff patches in ```diff blocks. One block per file."
)
_OUTPUT_INSTRUCTION_CODEX_OTHER = (
    "Output your analysis as plain text with clear section headings."
)
_OUTPUT_INSTRUCTION_FULL_FILE = (
    "Output the complete, final content of each changed file in "
    "```path/to/file.py\n...\n``` fenced blocks. Do NOT use diff format."
)
_OUTPUT_INSTRUCTION_COPILOT = (
    "Be concise. Use bullet points for findings. Stay under 2000 words."
)


def build_prompt(
    *,
    request: dict[str, Any],
    resolved_config: dict[str, Any],
    step_id: str,
    provider: str,
    model_ref: str,
    effective_output_mode: str = "",
) -> str:
    phase = (
        str(resolved_config.get("phase") or request.get("workflow_intent") or "")
        .strip()
        .lower()
    )
    operator_context = (
        request.get("operator_context")
        if isinstance(request.get("operator_context"), dict)
        else {}
    )
    role_instruction = _PHASE_ROLE_INSTRUCTIONS.get(phase, _DEFAULT_ROLE)
    phase_guidance = _PHASE_GUIDANCE.get(phase, _DEFAULT_PHASE_GUIDANCE)
    summary_text = _safe_text(request.get("summary")) or "No summary provided."
    stored_context = operator_context.get("stored_context")
    prior_step_sections = _format_prior_step_outputs(
        operator_context.get("prior_step_outputs")
    )
    prior_step_artifact_refs = _format_prior_step_artifact_refs(
        operator_context.get("prior_step_artifact_refs"),
        operator_context.get("plan_artifact_ref"),
        operator_context.get("checklist_artifact_ref"),
    )
    estimated_used = len(summary_text.encode("utf-8"))
    remaining_context_budget = max(512, _STORED_CONTEXT_CLIP - estimated_used)

    sections = [
        "## Role\n"
        f"{role_instruction}\n"
        f"- Phase: `{phase or 'unknown'}`\n"
        f"- Step ID: `{step_id or 'unspecified'}`\n"
        f"- Provider: `{provider or 'unknown'}`\n"
        f"- Model: `{model_ref or 'default'}`",
        f"## Task Summary\n{summary_text}",
        _render_stored_context(stored_context, max_bytes=remaining_context_budget),
        f"## Target Scope\n{_format_targets(request.get('targets'))}",
        f"## Constraints\n{_format_constraints(request.get('constraints'))}",
        f"## Task Source\n{_format_task_source(request.get('source'), resolved_config.get('artifacts'))}",
        _format_prior_phase_context(operator_context.get("prior_phase_outputs")),
        *prior_step_sections,
        prior_step_artifact_refs,
        f"## Phase Guidance\n{phase_guidance}",
    ]
    base_prompt = "\n\n".join(section for section in sections if section.strip())
    return ProviderPromptAdapter(
        provider=provider,
        phase=phase,
        effective_output_mode=effective_output_mode,
    ).optimize(base_prompt)


class ProviderPromptAdapter:
    def __init__(
        self, *, provider: str, phase: str, effective_output_mode: str = ""
    ) -> None:
        self.provider = (provider or "").strip().lower()
        self.phase = (phase or "").strip().lower()
        self.effective_output_mode = (effective_output_mode or "").strip().lower()

    def optimize(self, prompt_text: str) -> str:
        if self.provider == "gemini":
            return self._optimize_gemini(prompt_text)
        if self.provider == "codex":
            return self._optimize_codex(prompt_text)
        if self.provider == "copilot":
            return self._optimize_copilot(prompt_text)
        return prompt_text

    def _optimize_gemini(self, prompt_text: str) -> str:
        if self.effective_output_mode == "full_file":
            output_instruction = _OUTPUT_INSTRUCTION_FULL_FILE
        else:
            output_instruction = _OUTPUT_INSTRUCTION_GEMINI
        output_section = (
            "## Output Format\n"
            f"{output_instruction}\n"
            "Prefer structured findings with clear sections (Summary, Findings, Risks, "
            "Next Steps).\n"
            "Append a final ```json block with keys: status, summary, findings, risks."
        )
        optimized = f"{prompt_text}\n\n{output_section}"
        return _enforce_token_budget(
            optimized,
            token_limit=_GEMINI_TOKEN_LIMIT,
            provider_name="gemini",
        )

    def _optimize_codex(self, prompt_text: str) -> str:
        if self.effective_output_mode == "full_file":
            output_instruction = _OUTPUT_INSTRUCTION_FULL_FILE
        elif self.effective_output_mode in {"patch", ""}:
            output_instruction = (
                _OUTPUT_INSTRUCTION_CODEX_IMPL
                if self.phase == "impl"
                else _OUTPUT_INSTRUCTION_CODEX_OTHER
            )
        else:
            output_instruction = _OUTPUT_INSTRUCTION_CODEX_OTHER
        output_section = (
            "## Output Format\n"
            f"{output_instruction}\n"
            "Prefer explicit, file-scoped results with minimal filler."
        )
        optimized = f"{prompt_text}\n\n{output_section}"
        return _enforce_token_budget(
            optimized,
            token_limit=_CODEX_TOKEN_LIMIT,
            provider_name="codex",
        )

    def _optimize_copilot(self, prompt_text: str) -> str:
        output_section = (
            "## Output Format\n"
            f"{_OUTPUT_INSTRUCTION_COPILOT}\n"
            "Prefer concise structured reports with clear action items."
        )
        optimized = f"{prompt_text}\n\n{output_section}"
        return _enforce_byte_budget(
            optimized,
            byte_limit=_COPILOT_BYTE_LIMIT,
            provider_name="copilot",
        )


def _format_targets(targets: Any) -> str:
    payload = targets if isinstance(targets, dict) else {}
    lines: list[str] = []

    scope_summary = _safe_text(payload.get("summary"))
    if scope_summary:
        lines.append(f"- Scope summary: {scope_summary}")

    paths = _coerce_string_list(payload.get("paths"))
    if paths:
        lines.append("- Target paths:")
        lines.extend(f"  - {path}" for path in paths)

    globs = _coerce_string_list(payload.get("globs"))
    if globs:
        lines.append("- Target globs:")
        lines.extend(f"  - {glob}" for glob in globs)

    if not lines:
        return (
            "- No explicit target paths or globs were provided.\n"
            "- Keep the scope minimal and infer likely files from the task summary."
        )
    return "\n".join(lines)


def _format_constraints(constraints: Any) -> str:
    payload = constraints if isinstance(constraints, dict) else {}
    lines: list[str] = []

    hard = _coerce_string_list(payload.get("hard"))
    if hard:
        lines.append("- Hard constraints:")
        lines.extend(f"  - {item}" for item in hard)

    soft = _coerce_string_list(payload.get("soft"))
    if soft:
        lines.append("- Soft constraints:")
        lines.extend(f"  - {item}" for item in soft)

    disallowed_paths = _coerce_string_list(payload.get("disallowed_paths"))
    if disallowed_paths:
        lines.append("- Disallowed paths:")
        lines.extend(f"  - {item}" for item in disallowed_paths)

    approvals_required = payload.get("approvals_required")
    approval_entries = _coerce_approval_entries(approvals_required)
    if approval_entries:
        lines.append("- Approvals required:")
        for item in approval_entries:
            operation_type = _safe_text(item.get("operationType")) or "unspecified"
            phase = _safe_text(item.get("phase")) or "unspecified"
            rationale = _safe_text(item.get("rationale"))
            scope = item.get("scope")
            target_files: list[str] = []
            if isinstance(scope, dict):
                target_files = _coerce_string_list(scope.get("targetFiles"))
            summary = f"{operation_type} (phase={phase})"
            if target_files:
                summary = f"{summary} targets={', '.join(target_files)}"
            lines.append(f"  - {summary}")
            if rationale:
                lines.append(f"    rationale: {rationale}")
    elif isinstance(approvals_required, list):
        if approvals_required:
            lines.append("- Approvals required:")
            lines.extend(
                f"  - {item}" for item in _coerce_string_list(approvals_required)
            )
    elif approvals_required:
        lines.append(f"- Approvals required: {approvals_required}")

    if not lines:
        return "- No explicit hard/soft constraints were provided."
    return "\n".join(lines)


def _format_task_source(source: Any, artifacts: Any) -> str:
    source_ref = source if isinstance(source, dict) else {}
    source_path = _safe_text(source_ref.get("path"))
    source_kind = _safe_text(source_ref.get("kind")).lower()
    effective_source_path, snapshot_ref = _resolve_task_source_path(
        source_path=source_path,
        source_kind=source_kind,
        artifacts=artifacts,
    )

    header_lines = [
        f"- Source path: `{source_path}`",
        f"- Source kind: `{source_kind or 'unknown'}`",
    ]
    if snapshot_ref:
        header_lines.append(f"- Source snapshot: `{snapshot_ref}`")
    if effective_source_path is None:
        return "\n".join([*header_lines, "- Source reference is not available."])
    if not effective_source_path.exists():
        return "\n".join([*header_lines, "- Source file is unavailable."])

    try:
        source_text = effective_source_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "\n".join([*header_lines, "- Source file is unavailable."])
    except OSError as exc:
        return "\n".join([*header_lines, f"- Source file could not be read: {exc}"])

    if source_kind == "json":
        return _format_json_source(
            source_text=source_text,
            header_lines=header_lines,
        )

    clipped = _truncate_with_notice(source_text, _MARKDOWN_SOURCE_LIMIT)
    return "\n".join([*header_lines, "```text", clipped, "```"])


def _resolve_task_source_path(
    *,
    source_path: str,
    source_kind: str,
    artifacts: Any,
) -> tuple[Path | None, str]:
    intake_dir = ""
    if isinstance(artifacts, dict):
        intake_dir = _safe_text(artifacts.get("intake_dir"))

    snapshot_path: Path | None = None
    if intake_dir:
        intake_dir_path = Path(intake_dir)
        if source_kind == "json":
            snapshot_path = intake_dir_path / "source-snapshot.json"
        elif source_kind == "markdown":
            snapshot_path = intake_dir_path / "source-snapshot.md"
        else:
            for candidate in (
                intake_dir_path / "source-snapshot.md",
                intake_dir_path / "source-snapshot.json",
            ):
                if candidate.exists():
                    snapshot_path = candidate
                    break
        if snapshot_path and snapshot_path.exists():
            return snapshot_path, str(snapshot_path)

    if not source_path:
        return None, ""
    return Path(source_path), ""


def _format_json_source(*, source_text: str, header_lines: list[str]) -> str:
    try:
        payload = json.loads(source_text)
    except json.JSONDecodeError:
        clipped = _truncate_with_notice(source_text, _MARKDOWN_SOURCE_LIMIT)
        return "\n".join([*header_lines, "```json", clipped, "```"])

    if not isinstance(payload, dict):
        clipped = _truncate_with_notice(source_text, _MARKDOWN_SOURCE_LIMIT)
        return "\n".join([*header_lines, "```json", clipped, "```"])

    source_summary = _truncate_with_notice(
        _safe_text(payload.get("summary")),
        _JSON_SOURCE_FIELD_LIMIT,
    )
    operator_context = payload.get("operator_context")
    operator_description = ""
    if isinstance(operator_context, dict):
        operator_description = _truncate_with_notice(
            _safe_text(operator_context.get("description")),
            _JSON_SOURCE_FIELD_LIMIT,
        )
    body_lines: list[str] = [*header_lines]
    if source_summary:
        body_lines.append(f"- Source summary: {source_summary}")
    if operator_description:
        body_lines.append("- Operator context description:")
        body_lines.append("```text")
        body_lines.append(operator_description)
        body_lines.append("```")
    if len(body_lines) == len(header_lines):
        clipped = _truncate_with_notice(source_text, _MARKDOWN_SOURCE_LIMIT)
        body_lines.extend(["```json", clipped, "```"])
    return "\n".join(body_lines)


def _format_prior_phase_context(prior_phase_outputs: Any) -> str:
    entries = _coerce_context_entries(prior_phase_outputs)
    if not entries:
        return ""

    lines = ["## Prior Phase Context"]
    for item in entries:
        phase = _safe_text(item.get("phase")) or "unknown"
        summary = _safe_text(item.get("summary")) or "No summary available."
        snippet = _truncate_with_notice(
            _safe_text(item.get("content_snippet")) or summary,
            _PRIOR_PHASE_SNIPPET_LIMIT,
        )
        lines.extend(
            [
                f"### Phase `{phase}`",
                f"- Summary: {summary}",
                "```text",
                snippet,
                "```",
            ]
        )
    return "\n".join(lines)


def _format_prior_step_outputs(prior_step_outputs: Any) -> list[str]:
    entries = _coerce_context_entries(prior_step_outputs)
    sections: list[str] = []
    for index, item in enumerate(entries, start=1):
        step = _safe_text(item.get("step")) or str(index)
        summary = _safe_text(item.get("summary"))
        snippet = _truncate_with_notice(
            _safe_text(item.get("content_snippet")) or summary,
            _PRIOR_STEP_SNIPPET_LIMIT,
        )
        lines = [f"## Prior Step Output (step {index})", f"- Step ID: `{step}`"]
        if summary:
            lines.append(f"- Summary: {summary}")
        if snippet:
            lines.extend(["```text", snippet, "```"])
        sections.append("\n".join(lines))
    return sections


def _format_prior_step_artifact_refs(
    refs: Any,
    plan_artifact_ref: Any,
    checklist_artifact_ref: Any,
) -> str:
    lines: list[str] = []
    if isinstance(refs, list):
        for entry in refs:
            if not isinstance(entry, dict):
                continue
            step = _safe_text(entry.get("step")) or "?"
            ref_type = _safe_text(entry.get("refType")) or "ref"
            ref = _safe_text(entry.get("ref"))
            if not ref:
                continue
            lines.append(f"- Step `{step}` {ref_type}: `{ref}`")

    plan_ref = _safe_text(plan_artifact_ref)
    if plan_ref:
        lines.append(f"- plan_artifact_ref: `{plan_ref}`")
    checklist_ref = _safe_text(checklist_artifact_ref)
    if checklist_ref:
        lines.append(f"- checklist_artifact_ref: `{checklist_ref}`")

    if not lines:
        return ""
    return "\n".join(["## Prior Step Artifact References", *lines])


def _coerce_context_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _coerce_approval_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _format_stored_context(stored: dict[str, Any] | None) -> str:
    return _render_stored_context(stored, max_bytes=_STORED_CONTEXT_CLIP)


def _render_stored_context(ctx: dict[str, Any] | None, max_bytes: int) -> str:
    """
    Convert .contexts/ JSON dict to markdown section.

    Section priority (drop lower priority on budget overflow):
      1. project_profile.goal + constraints
      2. active decisions
      3. task_snapshot (progress, blockers)
      4. procedural_rules
      5. recent episodes
    """
    if not isinstance(ctx, dict) or not ctx:
        return ""

    heading = "## Stored Context (from project memory)"
    sections: list[str] = []

    project_profile = ctx.get("project_profile")
    if not isinstance(project_profile, dict):
        project_context = ctx.get("project_context")
        if isinstance(project_context, dict):
            project_profile = project_context.get("project_profile", project_context)
    if isinstance(project_profile, dict):
        payload = project_profile.get("payload", project_profile)
        goal = _safe_text(payload.get("goal"))
        constraints = payload.get("constraints")
        lines: list[str] = []
        if goal:
            lines.append("### Project Goal")
            lines.append(goal)
        if constraints:
            lines.append("### Constraints")
            if isinstance(constraints, list):
                lines.extend(f"- {item}" for item in _coerce_string_list(constraints))
            else:
                lines.append(str(constraints))
        if lines:
            sections.append("\n".join(lines))

    decisions = [
        item for item in (ctx.get("decisions") or []) if isinstance(item, dict)
    ][:_STORED_CONTEXT_DECISIONS_MAX]
    if decisions:
        lines = ["### Active Decisions"]
        for item in decisions:
            payload = item.get("payload", item)
            key = _safe_text(item.get("key"))
            summary = _safe_text(
                payload.get("decision")
                or payload.get("summary")
                or item.get("summary")
                or item.get("content")
            )
            if key and summary:
                lines.append(f"- `{key}`: {summary}")
            elif summary:
                lines.append(f"- {summary}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    snapshot = ctx.get("task_snapshot")
    if isinstance(snapshot, dict):
        payload = snapshot.get("payload", snapshot)
        lines = []
        task_goal = _safe_text(payload.get("task_goal"))
        progress = _safe_text(payload.get("progress"))
        blockers = _coerce_string_list(payload.get("blockers"))[
            :_STORED_CONTEXT_BLOCKERS_MAX
        ]
        if task_goal:
            lines.append("### Task Goal")
            lines.append(task_goal)
        if progress:
            lines.append("### Progress")
            lines.append(progress)
        if blockers:
            lines.append("### Blockers")
            lines.extend(f"- {item}" for item in blockers)
        if lines:
            sections.append("\n".join(lines))

    rules = [
        item for item in (ctx.get("procedural_rules") or []) if isinstance(item, dict)
    ][:3]
    if rules:
        lines = ["### Procedural Rules"]
        for item in rules:
            payload = item.get("payload", item)
            name = _safe_text(payload.get("name") or item.get("key"))
            instructions = _safe_text(payload.get("instructions"))
            if name and instructions:
                lines.append(f"- **{name}**: {instructions}")
            elif name:
                lines.append(f"- **{name}**")
            elif instructions:
                lines.append(f"- {instructions}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    episodes = [item for item in (ctx.get("episodes") or []) if isinstance(item, dict)][
        :3
    ]
    if episodes:
        lines = ["### Recent Episodes"]
        for item in episodes:
            payload = item.get("payload", item)
            observation = _safe_text(payload.get("observation"))
            result = _safe_text(payload.get("result"))
            if observation and result:
                lines.append(f"- {observation} -> {result}")
            elif observation:
                lines.append(f"- {observation}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    if not sections:
        return ""

    included: list[str] = [heading]
    for section in sections:
        candidate = "\n\n".join([*included, section])
        if len(candidate.encode("utf-8")) <= max_bytes or len(included) == 1:
            included.append(section)
        else:
            break

    return "\n\n".join(included)


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _enforce_token_budget(
    text: str,
    *,
    token_limit: int,
    provider_name: str,
) -> str:
    if _estimate_tokens(text) <= token_limit:
        return text
    notice = (
        f"[PROMPT TRUNCATED for {provider_name}: approximate limit {token_limit} "
        "tokens reached.]"
    )
    char_budget = max(1, token_limit * 4 - len(notice) - 2)
    clipped = _truncate_at_whitespace(text, char_budget)
    return f"{clipped}\n\n{notice}"


def _enforce_byte_budget(text: str, *, byte_limit: int, provider_name: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_limit:
        return text
    suffix = f" [PROMPT TRUNCATED for {provider_name}]"
    suffix_bytes = suffix.encode("utf-8")
    available = max(0, byte_limit - len(suffix_bytes))
    clipped = encoded[:available].decode("utf-8", errors="ignore")
    clipped = _truncate_at_whitespace(clipped, len(clipped))
    candidate = f"{clipped}{suffix}" if clipped else suffix
    while len(candidate.encode("utf-8")) > byte_limit and clipped:
        clipped = clipped[:-1].rstrip()
        candidate = f"{clipped}{suffix}" if clipped else suffix
    return candidate


def _truncate_at_whitespace(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    last_break = max(
        clipped.rfind(" "),
        clipped.rfind("\n"),
        clipped.rfind("\t"),
        clipped.rfind("\r"),
    )
    if last_break > 0:
        return clipped[:last_break].rstrip()
    return clipped


def _truncate_with_notice(text: str, max_chars: int) -> str:
    if not text:
        return ""
    clipped = _truncate_at_whitespace(text, max_chars)
    if clipped == text:
        return clipped
    return f"{clipped} [TRUNCATED]"
