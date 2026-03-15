from __future__ import annotations

from typing import Any


def render_markdown_document(*, title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for key, value in payload.items():
        _render_value(lines, key=_label(key), value=value, depth=2)
    return "\n".join(lines).rstrip() + "\n"


def _render_value(lines: list[str], *, key: str, value: Any, depth: int) -> None:
    heading = "#" * min(depth, 6)
    if isinstance(value, dict):
        lines.append(f"{heading} {key}")
        lines.append("")
        if not value:
            lines.append("_empty_")
            lines.append("")
            return
        for nested_key, nested_value in value.items():
            _render_value(
                lines, key=_label(nested_key), value=nested_value, depth=depth + 1
            )
        return
    if isinstance(value, list):
        lines.append(f"{heading} {key}")
        lines.append("")
        if not value:
            lines.append("- _empty_")
            lines.append("")
            return
        for item in value:
            if isinstance(item, dict):
                lines.append("-")
                for nested_key, nested_value in item.items():
                    if isinstance(nested_value, (dict, list)):
                        lines.append(f"  {nested_key}:")
                        _render_nested_block(lines, nested_value, indent="    ")
                    else:
                        lines.append(f"  {nested_key}: {nested_value}")
            else:
                lines.append(f"- {item}")
        lines.append("")
        return
    lines.append(f"{heading} {key}")
    lines.append("")
    lines.append(str(value))
    lines.append("")


def _render_nested_block(lines: list[str], value: Any, *, indent: str) -> None:
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            if isinstance(nested_value, (dict, list)):
                lines.append(f"{indent}{nested_key}:")
                _render_nested_block(lines, nested_value, indent=indent + "  ")
            else:
                lines.append(f"{indent}{nested_key}: {nested_value}")
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}-")
                _render_nested_block(lines, item, indent=indent + "  ")
            else:
                lines.append(f"{indent}- {item}")
        return
    lines.append(f"{indent}{value}")


def _label(key: str) -> str:
    return key.replace("_", " ").replace("-", " ")
