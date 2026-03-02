from __future__ import annotations

import re

from api_data_gen.domain.models import TableColumn, TableSchema
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier

_LENGTH_RE = re.compile(r"\((\d+)")


class SchemaRepository:
    def __init__(self, client: QueryClient):
        self._client = client

    def get_table_schema(self, table_name: str) -> TableSchema:
        schema_name, local_name = self._client.resolve_table_location(table_name)
        quoted_schema = quote_identifier(schema_name)
        quoted_table = quote_identifier(local_name)

        status_query = f"SHOW TABLE STATUS FROM {quoted_schema} LIKE %s"
        columns_query = f"SHOW FULL COLUMNS FROM {quoted_table} FROM {quoted_schema}"
        primary_query = f"SHOW KEYS FROM {quoted_table} FROM {quoted_schema} WHERE Key_name = 'PRIMARY'"

        status = self._client.fetch_one(status_query, (local_name,))
        if status is None:
            raise ValueError(f"Table status not found for {schema_name}.{local_name}")

        primary_rows = self._client.fetch_all(primary_query)
        primary_keys = [str(row["Column_name"]) for row in primary_rows]
        primary_key_set = {key.lower() for key in primary_keys}

        columns: list[TableColumn] = []
        for row in self._client.fetch_all(columns_query):
            data_type = str(row["Type"])
            columns.append(
                TableColumn(
                    name=str(row["Field"]),
                    type=data_type,
                    nullable=str(row["Null"]).upper() == "YES",
                    default_value=None if row["Default"] is None else str(row["Default"]),
                    comment=str(row.get("Comment") or ""),
                    is_primary_key=str(row["Field"]).lower() in primary_key_set,
                    is_auto_primary_key="auto_increment" in str(row.get("Extra") or "").lower(),
                    max_length=_extract_max_length(data_type),
                )
            )

        return TableSchema(
            table_name=local_name,
            table_type=str(status.get("Engine") or "mysql").lower(),
            columns=columns,
            primary_keys=primary_keys,
        )

    def list_tables(self, schema_names: list[str]) -> list[str]:
        if not schema_names:
            return []

        placeholders = ", ".join(["%s"] * len(schema_names))
        query = f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema IN ({placeholders})
            ORDER BY table_schema, table_name
        """
        ordered: list[str] = []
        seen: set[str] = set()
        for row in self._client.fetch_all(query, tuple(schema_names)):
            table_name = str(row["table_name"])
            if table_name in seen:
                continue
            seen.add(table_name)
            ordered.append(table_name)
        return ordered

    def get_row_counts(self, table_names: list[str]) -> dict[str, int]:
        row_counts: dict[str, int] = {}
        for table_name in table_names:
            schema_name, local_name = self._client.resolve_table_location(table_name)
            query = (
                f"SELECT COUNT(1) AS cnt FROM "
                f"{quote_identifier(schema_name)}.{quote_identifier(local_name)}"
            )
            row = self._client.fetch_one(query)
            row_counts[table_name] = int((row or {}).get("cnt") or 0)
        return row_counts


def _extract_max_length(data_type: str) -> int:
    match = _LENGTH_RE.search(data_type)
    if match is None:
        return 0
    return int(match.group(1))
