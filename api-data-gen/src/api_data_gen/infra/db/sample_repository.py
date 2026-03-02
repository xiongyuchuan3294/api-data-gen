from __future__ import annotations

from api_data_gen.domain.models import TableSchema
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier


class SampleRepository:
    def __init__(self, client: QueryClient, trace_schema: str, schema_repository=None):
        self._client = client
        self._trace_schema = trace_schema
        self._schema_repository = schema_repository

    def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
        schema_name, local_name = self._client.resolve_table_location(table_name)
        query = (
            f"SELECT * FROM {quote_identifier(schema_name)}.{quote_identifier(local_name)} LIMIT %s"
        )
        direct_rows = self._client.fetch_all(query, (limit,))
        if direct_rows:
            return [self._normalize_row(row) for row in direct_rows]

        return self._sample_from_matches(local_name, limit)

    def _sample_from_matches(self, table_name: str, limit: int) -> list[dict[str, str]]:
        query = f"""
            SELECT target_field, source_table, source_field
            FROM {quote_identifier(self._trace_schema)}.field_match_relations
            WHERE target_table = %s
        """
        relations = self._client.fetch_all(query, (table_name,))
        if not relations:
            return []

        samples_by_field: dict[str, list[str]] = {}
        for relation in relations:
            source_schema, source_table = self._client.resolve_table_location(str(relation["source_table"]))
            source_field = str(relation["source_field"])
            value_query = f"""
                SELECT DISTINCT {quote_identifier(source_field)}
                FROM {quote_identifier(source_schema)}.{quote_identifier(source_table)}
                WHERE {quote_identifier(source_field)} IS NOT NULL
                  AND {quote_identifier(source_field)} <> ''
                LIMIT %s
            """
            rows = self._client.fetch_all(value_query, (limit,))
            values = [str(row[source_field]) for row in rows if row.get(source_field) is not None]
            if values:
                samples_by_field[str(relation["target_field"])] = values

        if not samples_by_field:
            return []

        schema = None
        if self._schema_repository is not None:
            schema = self._schema_repository.get_table_schema(table_name)

        result: list[dict[str, str]] = []
        for index in range(limit):
            row: dict[str, str] = {}
            for field_name, values in samples_by_field.items():
                row[field_name] = values[index % len(values)]
            if schema is not None:
                _fill_missing_fields(row, schema)
            result.append(row)
        return result

    @staticmethod
    def _normalize_row(row: dict[str, object]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in row.items():
            normalized[str(key)] = "[NULL]" if value is None else str(value)
        return normalized


def _fill_missing_fields(row: dict[str, str], schema: TableSchema) -> None:
    for column in schema.columns:
        if column.name not in row:
            row[column.name] = _default_value_for_type(column.type)


def _default_value_for_type(data_type: str) -> str:
    lowered = data_type.lower()
    if "int" in lowered or "decimal" in lowered or "float" in lowered or "double" in lowered:
        return "0"
    if "date" in lowered or "time" in lowered:
        return "1970-01-01"
    return "[DEFAULT]"
