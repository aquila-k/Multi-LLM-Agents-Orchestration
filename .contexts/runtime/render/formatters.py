"""Render utilities: JSON, markdown, and collab-markdown formatters."""

import json


def to_json(data: dict) -> str:
    """json.dumps with ensure_ascii=False, no indent."""
    return json.dumps(data, ensure_ascii=False)


def to_markdown(context_data: dict) -> str:
    """
    Render context dict as markdown document.
    Section order matches context_render_default.md template.
    """
    lines = []

    lines.append("# Project Context")
    lines.append("")

    # Goal
    pp = context_data.get("project_profile")
    goal = ""
    non_goals = ""
    constraints = ""
    tools = ""
    if pp and isinstance(pp, dict):
        payload = pp.get("payload", pp)
        goal = payload.get("goal", "")
        non_goals = payload.get("non_goals", "")
        constraints = payload.get("constraints", "")
        tools = payload.get("tools", "")

    lines.append("## Goal")
    lines.append("")
    lines.append(goal if goal else "_Not set_")
    lines.append("")

    # Non-Goals
    lines.append("## Non-Goals")
    lines.append("")
    if non_goals:
        if isinstance(non_goals, list):
            for ng in non_goals:
                lines.append("- {}".format(ng))
        else:
            lines.append(str(non_goals))
    else:
        lines.append("_Not set_")
    lines.append("")

    # Constraints
    lines.append("## Constraints")
    lines.append("")
    if constraints:
        if isinstance(constraints, list):
            for c in constraints:
                lines.append("- {}".format(c))
        else:
            lines.append(str(constraints))
    else:
        lines.append("_None_")
    lines.append("")

    # Tools
    lines.append("## Tools")
    lines.append("")
    if tools:
        if isinstance(tools, list):
            for t in tools:
                lines.append("- {}".format(t))
        else:
            lines.append(str(tools))
    else:
        lines.append("_None_")
    lines.append("")

    # Active Decisions
    lines.append("## Active Decisions")
    lines.append("")
    decisions = context_data.get("decisions", [])
    if decisions:
        for d in decisions:
            payload = d.get("payload", d)
            dec_text = payload.get("decision", d.get("key", ""))
            key = d.get("key", "")
            lines.append("### {}".format(key))
            lines.append("")
            lines.append(dec_text)
            reason = payload.get("reason", "")
            if reason:
                lines.append("")
                lines.append("**Reason:** {}".format(reason))
            lines.append("")
    else:
        lines.append("_None_")
        lines.append("")

    # Procedural Rules
    lines.append("## Procedural Rules")
    lines.append("")
    rules = context_data.get("procedural_rules", [])
    if rules:
        for r in rules:
            payload = r.get("payload", r)
            name = payload.get("name", r.get("key", ""))
            lines.append("### {}".format(name))
            lines.append("")
            instructions = payload.get("instructions", "")
            if instructions:
                lines.append(instructions)
            when_to_use = payload.get("when_to_use", "")
            if when_to_use:
                lines.append("")
                lines.append("**When to use:** {}".format(when_to_use))
            lines.append("")
    else:
        lines.append("_None_")
        lines.append("")

    # Current Task
    lines.append("## Current Task")
    lines.append("")
    task = context_data.get("task_snapshot")
    if task:
        payload = task.get("payload", task)
        task_goal = payload.get("task_goal", "")
        lines.append(task_goal)
        current_plan = payload.get("current_plan", "")
        if current_plan:
            lines.append("")
            lines.append("**Plan:** {}".format(current_plan))
        blockers = payload.get("blockers", "")
        if blockers:
            lines.append("")
            lines.append("**Blockers:** {}".format(blockers))
        lines.append("")
    else:
        lines.append("_No active task_")
        lines.append("")

    # Current Session
    lines.append("## Current Session")
    lines.append("")
    session = context_data.get("session_snapshot")
    if session:
        payload = session.get("payload", session)
        session_goal = payload.get("session_goal", "")
        lines.append(session_goal)
        working_notes = payload.get("working_notes", "")
        if working_notes:
            lines.append("")
            lines.append("**Working Notes:** {}".format(working_notes))
        lines.append("")
    else:
        lines.append("_No active session_")
        lines.append("")

    # Recent Episodes
    episodes = context_data.get("episodes", [])
    if episodes:
        lines.append("## Recent Episodes")
        lines.append("")
        for ep in episodes:
            payload = ep.get("payload", ep)
            observation = payload.get("observation", "")
            lines.append("- {}".format(observation))
        lines.append("")

    # Policy Summary
    lines.append("## Policy Summary")
    lines.append("")
    policies = context_data.get("policies", [])
    if policies:
        for p in policies:
            key = p.get("key", "")
            enforcement = p.get("enforcement", "")
            match_pattern = p.get("match_pattern", "")
            lines.append("- **{}** [{}]: `{}`".format(key, enforcement, match_pattern))
        lines.append("")
    else:
        lines.append("_No active policies_")
        lines.append("")

    return "\n".join(lines)


def to_collab_markdown(context_data: dict) -> str:
    """
    Render as collab context-pack format.
    Headers match the 10 sections in context-pack.template.md.
    """
    lines = []
    lines.append("# Context Pack")
    lines.append("")

    pp = context_data.get("project_profile")
    goal = ""
    non_goals = ""
    constraints = ""
    tools = ""
    if pp and isinstance(pp, dict):
        payload = pp.get("payload", pp)
        goal = payload.get("goal", "")
        non_goals = payload.get("non_goals", "")
        constraints = payload.get("constraints", "")
        tools = payload.get("tools", "")

    # 0. Goal
    lines.append("## 0. Goal")
    lines.append("")
    lines.append(goal if goal else "_Not set_")
    lines.append("")

    # 1. Non-goals
    lines.append("## 1. Non-goals")
    lines.append("")
    if non_goals:
        if isinstance(non_goals, list):
            for ng in non_goals:
                lines.append("- {}".format(ng))
        else:
            lines.append(str(non_goals))
    else:
        lines.append("_Not set_")
    lines.append("")

    # 2. Scope (Constraints)
    lines.append("## 2. Scope")
    lines.append("")
    if constraints:
        if isinstance(constraints, list):
            for c in constraints:
                lines.append("- {}".format(c))
        else:
            lines.append(str(constraints))
    else:
        lines.append("_None_")
    lines.append("")

    # 3. Acceptance Criteria (from task if available)
    lines.append("## 3. Acceptance Criteria")
    lines.append("")
    task = context_data.get("task_snapshot")
    if task:
        payload = task.get("payload", task)
        criteria = payload.get("acceptance_criteria", "")
        if criteria:
            if isinstance(criteria, list):
                for c in criteria:
                    lines.append("- [ ] {}".format(c))
            else:
                lines.append(str(criteria))
        else:
            lines.append("_Not set_")
    else:
        lines.append("_Not set_")
    lines.append("")

    # 4. Fixed Decisions
    lines.append("## 4. Fixed Decisions")
    lines.append("")
    decisions = context_data.get("decisions", [])
    if decisions:
        for d in decisions:
            payload = d.get("payload", d)
            dec_text = payload.get("decision", d.get("key", ""))
            key = d.get("key", "")
            lines.append("- **{}**: {}".format(key, dec_text))
    else:
        lines.append("_None_")
    lines.append("")

    # 5. Files to Read (related_files from task/session)
    lines.append("## 5. Files to Read")
    lines.append("")
    related = []
    if task:
        rf = task.get("related_files", [])
        if rf:
            related.extend(rf)
    if related:
        for f in related:
            lines.append("- `{}`".format(f))
    else:
        lines.append("_None specified_")
    lines.append("")

    # 6. Prohibited Actions (policies with deny enforcement)
    lines.append("## 6. Prohibited Actions")
    lines.append("")
    policies = context_data.get("policies", [])
    deny_policies = [p for p in policies if p.get("enforcement") == "deny"]
    if deny_policies:
        for p in deny_policies:
            lines.append(
                "- {} (`{}`)".format(p.get("key", ""), p.get("match_pattern", ""))
            )
    else:
        lines.append("_None_")
    lines.append("")

    # 7. Current State (task + session snapshot)
    lines.append("## 7. Current State")
    lines.append("")
    if task:
        payload = task.get("payload", task)
        task_goal = payload.get("task_goal", "")
        lines.append("**Task:** {}".format(task_goal))
        current_plan = payload.get("current_plan", "")
        if current_plan:
            lines.append("")
            lines.append("**Plan:** {}".format(current_plan))
    session = context_data.get("session_snapshot")
    if session:
        payload = session.get("payload", session)
        session_goal = payload.get("session_goal", "")
        lines.append("")
        lines.append("**Session:** {}".format(session_goal))
    if not task and not session:
        lines.append("_No active task or session_")
    lines.append("")

    # 8. Open Questions
    lines.append("## 8. Open Questions")
    lines.append("")
    if task:
        payload = task.get("payload", task)
        oq = payload.get("open_questions", "")
        if oq:
            if isinstance(oq, list):
                for q in oq:
                    lines.append("- {}".format(q))
            else:
                lines.append(str(oq))
        else:
            lines.append("_None_")
    else:
        lines.append("_None_")
    lines.append("")

    # 9. Change History (episodes)
    lines.append("## 9. Change History")
    lines.append("")
    episodes = context_data.get("episodes", [])
    if episodes:
        lines.append("| Date | Change |")
        lines.append("| ---- | ------ |")
        for ep in episodes:
            payload = ep.get("payload", ep)
            obs = payload.get("observation", "")
            created = ep.get("created_at", "")
            lines.append("| {} | {} |".format(created, obs))
    else:
        lines.append("_No recorded episodes_")
    lines.append("")

    return "\n".join(lines)
