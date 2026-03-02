from __future__ import annotations

import re

from api_data_gen.domain.models import RequirementSummary

_KEYWORDS = (
    "测试场景",
    "造数",
    "接口",
    "SQL",
    "本地MySQL",
    "agent",
    "skill",
    "模块化",
    "LLM",
)


class RequirementParser:
    def parse(self, requirement_text: str) -> RequirementSummary:
        lines = [line.strip() for line in requirement_text.splitlines() if line.strip()]
        summary = self._extract_summary(lines)
        constraints = self._extract_constraints(lines)
        keywords = [keyword for keyword in _KEYWORDS if keyword.lower() in requirement_text.lower()]
        return RequirementSummary(summary=summary, constraints=constraints, keywords=keywords)

    @staticmethod
    def _extract_summary(lines: list[str]) -> str:
        for line in lines:
            normalized = re.sub(r"^(需求描述[:：]|【背景】|背景[:：])", "", line).strip()
            if normalized:
                return normalized
        return "未提供需求摘要"

    @staticmethod
    def _extract_constraints(lines: list[str]) -> list[str]:
        constraints: list[str] = []
        for line in lines:
            if any(token in line for token in ("要求", "建议", "不要", "分步", "本地")):
                constraints.append(re.sub(r"^\d+\.\s*", "", line).strip())
        return _deduplicate(constraints)


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
