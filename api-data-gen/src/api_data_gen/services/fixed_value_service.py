from __future__ import annotations

import re

_FIXED_VALUE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*[:=]\s*['\"]?([^'\"（(]+?)['\"]?\s*(?:[（(].*?[）)])?\s*$"
)


def parse_fixed_values(items: list[str] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in items or []:
        match = _FIXED_VALUE_RE.match(item)
        if match is None:
            continue
        values[match.group(1)] = match.group(2).strip()
    return values


def format_fixed_value_lines(items: list[str] | None) -> str:
    return "\n".join(item.strip() for item in items or [] if item.strip())
