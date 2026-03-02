from __future__ import annotations

from api_data_gen.domain.models import GeneratedRow, GeneratedTable, TableDataPlan


class CrossTableAlignmentService:
    def align(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[GeneratedTable]:
        rows_by_table = {
            generated_table.table_name: [dict(row.values) for row in generated_table.rows]
            for generated_table in generated_tables
        }
        tables_by_column = _collect_tables_by_column(table_plans)
        plans_by_table = {table_plan.table_name: table_plan for table_plan in table_plans}

        for column_name, table_names in sorted(tables_by_column.items()):
            involved_tables = [table_name for table_name in table_names if table_name in rows_by_table]
            if len(involved_tables) < 2:
                continue

            aligned_values = _resolve_aligned_values(
                column_name=column_name,
                involved_tables=involved_tables,
                plans_by_table=plans_by_table,
                rows_by_table=rows_by_table,
            )
            if not aligned_values:
                continue

            for table_name in involved_tables:
                for row_index, row in enumerate(rows_by_table[table_name]):
                    row[column_name] = aligned_values[row_index % len(aligned_values)]

        return [
            GeneratedTable(
                table_name=generated_table.table_name,
                row_count=generated_table.row_count,
                rows=[GeneratedRow(values=row) for row in rows_by_table[generated_table.table_name]],
                insert_sql=[],
            )
            for generated_table in generated_tables
        ]


def _collect_tables_by_column(table_plans: list[TableDataPlan]) -> dict[str, list[str]]:
    tables_by_column: dict[str, list[str]] = {}
    for table_plan in table_plans:
        primary_keys = set(table_plan.primary_keys)
        for column_plan in table_plan.column_plans:
            if column_plan.column_name in primary_keys:
                continue
            tables_by_column.setdefault(column_plan.column_name, [])
            if table_plan.table_name not in tables_by_column[column_plan.column_name]:
                tables_by_column[column_plan.column_name].append(table_plan.table_name)
    return tables_by_column


def _resolve_aligned_values(
    column_name: str,
    involved_tables: list[str],
    plans_by_table: dict[str, TableDataPlan],
    rows_by_table: dict[str, list[dict[str, str | None]]],
) -> list[str]:
    condition_values = _collect_condition_values(column_name, involved_tables, plans_by_table)
    if len(condition_values) == 1:
        return condition_values
    if len(condition_values) > 1:
        return []

    actual_values = [
        _collect_actual_values(rows_by_table[table_name], column_name)
        for table_name in involved_tables
    ]
    non_empty_values = [values for values in actual_values if values]
    if len(non_empty_values) < 2:
        return []
    return _ordered_intersection(non_empty_values)


def _collect_condition_values(
    column_name: str,
    involved_tables: list[str],
    plans_by_table: dict[str, TableDataPlan],
) -> list[str]:
    ordered: list[str] = []
    for table_name in involved_tables:
        table_plan = plans_by_table[table_name]
        for column_plan in table_plan.column_plans:
            if column_plan.column_name != column_name or column_plan.source != "condition":
                continue
            for value in column_plan.suggested_values:
                if value and value not in {"[NULL]", "[DEFAULT]"} and value not in ordered:
                    ordered.append(value)
    return ordered


def _collect_actual_values(rows: list[dict[str, str | None]], column_name: str) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        value = row.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered


def _ordered_intersection(values_by_table: list[list[str]]) -> list[str]:
    if not values_by_table:
        return []
    shared = set(values_by_table[0])
    for values in values_by_table[1:]:
        shared &= set(values)
    if not shared:
        return []
    return [value for value in values_by_table[0] if value in shared]
