from __future__ import annotations

import ast
import json
import re


def extract_json_text(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "[]"

    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1).strip()

    first_brace = min(
        [index for index in (stripped.find("["), stripped.find("{")) if index != -1],
        default=-1,
    )
    if first_brace == -1:
        return stripped
    balanced = _extract_balanced_json_fragment(stripped, first_brace)
    if balanced is not None:
        return balanced
    return stripped[first_brace:].strip()


def parse_json_payload(text: str) -> object:
    raw = extract_json_text(text)
    return _parse_relaxed_json(raw)


def salvage_json_array_objects(text: str) -> list[dict[str, object]]:
    raw = extract_json_text(text)
    start_index = raw.find("[")
    if start_index == -1:
        return []

    recovered: list[dict[str, object]] = []
    in_string = False
    escape = False
    array_depth = 0
    object_depth = 0
    object_start: int | None = None

    for index, char in enumerate(raw[start_index:], start=start_index):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "[":
            array_depth += 1
            continue
        if char == "]":
            array_depth = max(0, array_depth - 1)
            continue
        if char == "{":
            if array_depth == 1 and object_depth == 0:
                object_start = index
            if array_depth >= 1:
                object_depth += 1
            continue
        if char == "}" and object_depth > 0:
            object_depth -= 1
            if object_depth == 0 and object_start is not None:
                fragment = raw[object_start : index + 1]
                try:
                    payload = _parse_relaxed_json(fragment)
                except ValueError:
                    object_start = None
                    continue
                if isinstance(payload, dict):
                    recovered.append(payload)
                object_start = None
    return recovered


def _parse_relaxed_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        normalized = _normalize_relaxed_json(raw)
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            python_style = _to_python_literal(normalized)
            try:
                return ast.literal_eval(python_style)
            except (SyntaxError, ValueError) as exc:
                raise ValueError("Unable to parse JSON payload.") from exc


def _normalize_relaxed_json(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', normalized)
    normalized = re.sub(r",(\s*[}\]])", r"\1", normalized)
    normalized = re.sub(r"\bNone\b", "null", normalized)
    normalized = re.sub(r"\bTrue\b", "true", normalized)
    normalized = re.sub(r"\bFalse\b", "false", normalized)
    normalized = re.sub(
        r"'([^'\\]*(?:\\.[^'\\]*)*)'",
        lambda match: json.dumps(bytes(match.group(1), "utf-8").decode("unicode_escape")),
        normalized,
    )
    return normalized


def _to_python_literal(text: str) -> str:
    python_style = re.sub(r"\bnull\b", "None", text)
    python_style = re.sub(r"\btrue\b", "True", python_style)
    python_style = re.sub(r"\bfalse\b", "False", python_style)
    return python_style


def _extract_balanced_json_fragment(text: str, start_index: int) -> str | None:
    if start_index < 0 or start_index >= len(text):
        return None

    opening = text[start_index]
    if opening not in "[{":
        return None
    closing = "]" if opening == "[" else "}"

    in_string = False
    escape = False
    depth = 0

    for index, char in enumerate(text[start_index:], start=start_index):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1].strip()

    return None
