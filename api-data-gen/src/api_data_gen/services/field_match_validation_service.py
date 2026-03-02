from __future__ import annotations

from api_data_gen.domain.models import GeneratedTable, TableDataPlan, ValidationCheck


class FieldMatchValidationService:
    def __init__(self, field_match_repository):
        self._field_match_repository = field_match_repository

    def validate(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[ValidationCheck]:
        table_names = [generated_table.table_name for generated_table in generated_tables]
        relations = self._field_match_repository.list_relations(table_names)
        if not relations:
            return []

        generated_by_table = {generated_table.table_name: generated_table for generated_table in generated_tables}
        checks: list[ValidationCheck] = []
        for relation in relations:
            target_table = generated_by_table.get(relation.target_table)
            source_table = generated_by_table.get(relation.source_table)
            if target_table is None or source_table is None:
                continue

            target_values = _collect_values(target_table, relation.target_field)
            source_values = _collect_values(source_table, relation.source_field)
            if not target_values and not source_values:
                continue

            passed = bool(source_values) and all(value in source_values for value in target_values)
            detail = (
                f"{relation.target_table}.{relation.target_field} <- "
                f"{relation.source_table}.{relation.source_field}; "
                f"target={target_values or ['[NULL]']}; source={source_values or ['[NULL]']}"
            )
            if relation.match_reason:
                detail = f"{detail}; reason={relation.match_reason}"
            checks.append(
                ValidationCheck(
                    name=(
                        f"field_match:{relation.target_table}.{relation.target_field}"
                        f"<-{relation.source_table}.{relation.source_field}"
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
