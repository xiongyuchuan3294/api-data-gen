from __future__ import annotations

from api_data_gen.domain.models import FieldMatchRelation, GeneratedRow, GeneratedTable, TableDataPlan


class FieldMatchAlignmentService:
    def __init__(self, field_match_repository):
        self._field_match_repository = field_match_repository

    def align(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[GeneratedTable]:
        table_names = [generated_table.table_name for generated_table in generated_tables]
        relations = self._field_match_repository.list_relations(table_names)
        if not relations:
            return generated_tables

        rows_by_table = {
            generated_table.table_name: [dict(row.values) for row in generated_table.rows]
            for generated_table in generated_tables
        }
        plans_by_table = {table_plan.table_name: table_plan for table_plan in table_plans}

        for relation in relations:
            if relation.target_table not in rows_by_table or relation.source_table not in rows_by_table:
                continue
            if _is_condition_column(plans_by_table.get(relation.target_table), relation.target_field):
                continue

            source_values = _collect_values(rows_by_table[relation.source_table], relation.source_field)
            if not source_values:
                continue

            target_rows = rows_by_table[relation.target_table]
            for row_index, row in enumerate(target_rows):
                row[relation.target_field] = source_values[row_index % len(source_values)]

        return [
            GeneratedTable(
                table_name=generated_table.table_name,
                row_count=generated_table.row_count,
                rows=[GeneratedRow(values=row) for row in rows_by_table[generated_table.table_name]],
                insert_sql=[],
            )
            for generated_table in generated_tables
        ]


def _is_condition_column(table_plan: TableDataPlan | None, column_name: str) -> bool:
    if table_plan is None:
        return False
    return any(
        column_plan.column_name == column_name and column_plan.source == "condition"
        for column_plan in table_plan.column_plans
    )


def _collect_values(rows: list[dict[str, str | None]], column_name: str) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        value = row.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered
