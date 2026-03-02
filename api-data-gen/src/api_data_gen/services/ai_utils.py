from __future__ import annotations

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
    return stripped[first_brace:].strip()


def parse_json_payload(text: str) -> object:
    return json.loads(extract_json_text(text))
