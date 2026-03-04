from __future__ import annotations

from api_data_gen.domain.models import GeneratedTable, TableDataPlan, ValidationCheck


class RelationStrategyValidationService:
    def __init__(self, reusable_strategy_service):
        self._reusable_strategy_service = reusable_strategy_service

    def validate(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[ValidationCheck]:
        table_names = [generated_table.table_name for generated_table in generated_tables]
        relation_records = self._reusable_strategy_service.list_relation_strategies(table_names)
        if not relation_records:
            return []

        generated_by_table = {generated_table.table_name: generated_table for generated_table in generated_tables}
        checks: list[ValidationCheck] = []
        for record in relation_records:
            target_table = generated_by_table.get(record.target_table)
            source_table = generated_by_table.get(record.source_table)
            if target_table is None or source_table is None:
                continue

            target_values = _collect_values(target_table, record.target_field)
            source_values = _collect_values(source_table, record.source_field)
            if not target_values and not source_values:
                continue

            passed = bool(source_values) and all(value in source_values for value in target_values)
            detail = (
                f"{record.target_table}.{record.target_field} <- "
                f"{record.source_table}.{record.source_field}; "
                f"target={target_values or ['[NULL]']}; source={source_values or ['[NULL]']}"
            )
            if record.relation_reason:
                detail = f"{detail}; reason={record.relation_reason}"
            checks.append(
                ValidationCheck(
                    name=(
                        f"relation_strategy:{record.target_table}.{record.target_field}"
                        f"<-{record.source_table}.{record.source_field}"
                    ),
                    passed=passed,
                    detail=detail,
                )
            )
        return checks


def _collect_values(generated_table: GeneratedTable, column_name: str) -> list[str]:
    ordered: list[str] = []
    for row in generated_table.rows:
        value = row.values.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered
