from __future__ import annotations

from api_data_gen.config import Settings
from api_data_gen.domain.models import FieldMatchRelation
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier, quote_literal


class FieldMatchRepository:
    def __init__(self, client: QueryClient, settings: Settings):
        self._client = client
        self._settings = settings

    def list_relations(self, table_names: list[str]) -> list[FieldMatchRelation]:
        unique_tables = _deduplicate(table_names)
        if not unique_tables:
            return []

        placeholders = ", ".join(["%s"] * len(unique_tables))
        schema_name = quote_identifier(self._settings.trace_schema)
        query = f"""
            SELECT target_table, target_field, source_table, source_field, match_reason
            FROM {schema_name}.field_match_relations
            WHERE target_table IN ({placeholders}) OR source_table IN ({placeholders})
            ORDER BY id
        """
        params = tuple(unique_tables + unique_tables)
        return [
            FieldMatchRelation(
                target_table=str(row["target_table"]),
                target_field=str(row["target_field"]),
                source_table=str(row["source_table"]),
                source_field=str(row["source_field"]),
                match_reason=str(row.get("match_reason") or ""),
            )
            for row in self._client.fetch_all(query, params)
        ]

    def replace_target_relations(self, target_table: str, relations: list[FieldMatchRelation]) -> None:
        schema_name = quote_identifier(self._settings.trace_schema)
        statements = [
            f"DELETE FROM {schema_name}.field_match_relations WHERE target_table = {quote_literal(target_table)}"
        ]
        for relation in relations:
            statements.append(
                f"""
                INSERT INTO {schema_name}.field_match_relations
                (target_table, target_field, source_table, source_field, match_reason, source_row_count)
                VALUES (
                    {quote_literal(relation.target_table)},
                    {quote_literal(relation.target_field)},
                    {quote_literal(relation.source_table)},
                    {quote_literal(relation.source_field)},
                    {quote_literal(relation.match_reason)},
                    NULL
                )
                """.strip()
            )
        self._client.execute_statements(self._settings.trace_schema, statements)


def _deduplicate(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
