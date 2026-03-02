from __future__ import annotations

import re

from api_data_gen.domain.models import GeneratedRow, TableColumn, TableSchema
from api_data_gen.services.data_generation_service import DEFAULT_MARKER

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class InsertRenderService:
    def render_table(self, schema: TableSchema, rows: list[GeneratedRow]) -> str:
        if not rows:
            return ""

        columns = [column.name for column in schema.columns]
        column_sql = ", ".join(f"`{column_name}`" for column_name in columns)
        values_sql = ",\n".join(
            f"  ({self._render_row(schema.columns, row)})"
            for row in rows
        )
        return (
            f"INSERT INTO `{schema.table_name}` ({column_sql}) VALUES\n"
            f"{values_sql};"
        )

    def _render_row(self, columns: list[TableColumn], row: GeneratedRow) -> str:
        return ", ".join(
            self._render_value(row.values.get(column.name), column)
            for column in columns
        )

    def _render_value(self, value: str | None, column: TableColumn) -> str:
        if value is None:
            return "NULL"
        if value == DEFAULT_MARKER:
            return "DEFAULT"
        if _is_numeric_value(value, column.type):
            return value
        return f"'{_escape_sql(value)}'"


def _is_numeric_value(value: str, data_type: str) -> bool:
    lowered = data_type.lower()
    if not any(token in lowered for token in ("int", "decimal", "float", "double", "numeric")):
        return False
    return bool(_NUMBER_RE.fullmatch(value.strip()))


def _escape_sql(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")
