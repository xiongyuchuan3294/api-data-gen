from __future__ import annotations

import re

from api_data_gen.domain.models import FieldMatchRelation, TableColumn, TableSchema

_TYPE_NAME_RE = re.compile(r"^[a-zA-Z]+")


class FieldMatchDiscoveryService:
    def __init__(
        self,
        schema_repository,
        field_match_repository,
        candidate_schema_names: list[str],
        ignored_tables: set[str] | None = None,
    ):
        self._schema_repository = schema_repository
        self._field_match_repository = field_match_repository
        self._candidate_schema_names = list(candidate_schema_names)
        self._ignored_tables = set(ignored_tables or set())

    def discover(self, target_table: str) -> list[FieldMatchRelation]:
        existing_relations = [
            relation
            for relation in self._field_match_repository.list_relations([target_table])
            if relation.target_table == target_table
        ]
        if existing_relations:
            return existing_relations

        candidate_tables = [
            table_name
            for table_name in self._schema_repository.list_tables(self._candidate_schema_names)
            if table_name != target_table and table_name not in self._ignored_tables
        ]
        if not candidate_tables:
            return []

        row_counts = self._schema_repository.get_row_counts(candidate_tables)
        sorted_tables = sorted(
            (table_name for table_name in candidate_tables if row_counts.get(table_name, 0) > 0),
            key=lambda table_name: row_counts[table_name],
            reverse=True,
        )
        if not sorted_tables:
            return []

        target_schema = self._schema_repository.get_table_schema(target_table)
        source_schemas = {
            table_name: self._schema_repository.get_table_schema(table_name)
            for table_name in sorted_tables
        }

        relations: list[FieldMatchRelation] = []
        matched_columns: set[str] = set()
        for source_table in sorted_tables:
            source_schema = source_schemas[source_table]
            for target_column in target_schema.columns:
                if target_column.name in matched_columns:
                    continue
                if target_column.is_primary_key:
                    continue

                matched = _match_same_name(target_column, source_schema)
                if matched is None:
                    matched = _match_same_comment(target_column, source_schema)
                if matched is None:
                    continue

                source_column, reason = matched
                relations.append(
                    FieldMatchRelation(
                        target_table=target_table,
                        target_field=target_column.name,
                        source_table=source_table,
                        source_field=source_column.name,
                        match_reason=reason,
                    )
                )
                matched_columns.add(target_column.name)

        if relations:
            self._field_match_repository.replace_target_relations(target_table, relations)
        return relations


def _match_same_name(target_column: TableColumn, source_schema: TableSchema) -> tuple[TableColumn, str] | None:
    for source_column in source_schema.columns:
        if source_column.name != target_column.name:
            continue
        if _is_type_compatible(source_column.type, target_column.type):
            return source_column, "same_column_name"
    return None


def _match_same_comment(target_column: TableColumn, source_schema: TableSchema) -> tuple[TableColumn, str] | None:
    target_comment = target_column.comment.strip()
    if not target_comment:
        return None
    for source_column in source_schema.columns:
        if source_column.comment.strip() != target_comment:
            continue
        if _is_type_compatible(source_column.type, target_column.type):
            return source_column, f"same_comment:{target_comment}"
    return None


def _is_type_compatible(source_type: str, target_type: str) -> bool:
    source_base = _normalize_type_name(source_type)
    target_base = _normalize_type_name(target_type)
    if not source_base or not target_base:
        return False
    if source_base == target_base:
        return True

    groups = [
        {"int", "tinyint", "smallint", "mediumint", "bigint", "decimal", "numeric"},
        {"char", "varchar", "text", "tinytext", "mediumtext", "longtext"},
        {"float", "double", "real"},
        {"date", "datetime", "timestamp", "year", "time"},
    ]
    return any(source_base in group and target_base in group for group in groups)


def _normalize_type_name(data_type: str) -> str:
    match = _TYPE_NAME_RE.search((data_type or "").lower())
    if match is None:
        return ""
    return match.group(0)
