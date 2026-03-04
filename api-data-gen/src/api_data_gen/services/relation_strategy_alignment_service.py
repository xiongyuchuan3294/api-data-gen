from __future__ import annotations

from api_data_gen.domain.models import GeneratedRow, GeneratedTable, TableDataPlan


class RelationStrategyAlignmentService:
    def __init__(self, reusable_strategy_service):
        self._reusable_strategy_service = reusable_strategy_service

    def align(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[GeneratedTable]:
        table_names = [generated_table.table_name for generated_table in generated_tables]
        relation_records = self._reusable_strategy_service.list_relation_strategies(table_names)
        if not relation_records:
            return generated_tables

        rows_by_table = {
            generated_table.table_name: [dict(row.values) for row in generated_table.rows]
            for generated_table in generated_tables
        }
        plans_by_table = {table_plan.table_name: table_plan for table_plan in table_plans}

        for record in relation_records:
            if record.target_table not in rows_by_table or record.source_table not in rows_by_table:
                continue
            if _is_condition_column(plans_by_table.get(record.target_table), record.target_field):
                continue

            source_values = _collect_values(rows_by_table[record.source_table], record.source_field)
            if not source_values:
                continue

            target_rows = rows_by_table[record.target_table]
            for row_index, row in enumerate(target_rows):
                row[record.target_field] = source_values[row_index % len(source_values)]

        return [
            GeneratedTable(
                table_name=generated_table.table_name,
                row_count=generated_table.row_count,
                rows=[GeneratedRow(values=row) for row in rows_by_table[generated_table.table_name]],
                insert_sql=[],
                scenario_id=generated_table.scenario_id,
                scenario_title=generated_table.scenario_title,
                scenario_objective=generated_table.scenario_objective,
                field_strategies=generated_table.field_strategies,
                field_generation_strategies=generated_table.field_generation_strategies,
                generation_source=generated_table.generation_source,
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
