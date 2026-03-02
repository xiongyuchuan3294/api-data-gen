from __future__ import annotations

import re

from api_data_gen.domain.models import SqlInfo

_FROM_RE = re.compile(r"\bFROM\b\s+([`\w\.]+)", re.IGNORECASE)
_WHERE_RE = re.compile(
    r"(?:WHERE|where)\s+(.*?)(?=(?:GROUP\s+BY|ORDER\s+BY|LIMIT|$))",
    re.IGNORECASE | re.DOTALL,
)


class SqlParser:
    def extract_sql_info(self, sql_text: str) -> SqlInfo:
        return SqlInfo(
            table_name=self.extract_table_name(sql_text),
            conditions=self.extract_filter_conditions(sql_text),
            operation=self.extract_operation_type(sql_text),
        )

    @staticmethod
    def extract_operation_type(sql_text: str) -> str:
        """Extract SQL operation type (SELECT, INSERT, UPDATE, DELETE)"""
        match = re.match(r"^\s*(\w+)", sql_text.strip(), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return "SELECT"

    @staticmethod
    def is_count_query(sql_text: str) -> bool:
        return bool(re.search(r"\bcount\s*\(", sql_text, re.IGNORECASE))

    @staticmethod
    def extract_table_name(sql_text: str) -> str:
        match = _FROM_RE.search(sql_text)
        if match is None:
            return "unknown_table"

        raw_table = match.group(1).replace("`", "")
        return raw_table.split(".")[-1]

    @staticmethod
    def extract_filter_conditions(sql_text: str) -> list[str]:
        without_comments = re.sub(r"--.*", "", sql_text)
        without_comments = re.sub(r"/\*.*?\*/", "", without_comments, flags=re.DOTALL)

        match = _WHERE_RE.search(without_comments)
        if match is None:
            return []

        condition_text = match.group(1).strip()
        conditions = re.split(r"(?i)\s+AND\s+|\s+OR\s+", condition_text)
        return [condition.strip() for condition in conditions if condition.strip()]
