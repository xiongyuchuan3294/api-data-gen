from __future__ import annotations

from api_data_gen.domain.models import GeneratedTable, RelationRule, TableDataPlan, ValidationCheck


class CrossTableValidationService:
    def validate(
        self,
        table_plans: list[TableDataPlan],
        generated_tables: list[GeneratedTable],
        relation_rules: list[RelationRule] | None = None,
    ) -> list[ValidationCheck]:
        checks: list[ValidationCheck] = []
        excluded_columns = _collect_explicit_relation_columns(relation_rules or [])
        tables_by_column = _collect_condition_tables_by_column(table_plans, excluded_columns)
        generated_by_table = {generated_table.table_name: generated_table for generated_table in generated_tables}

        for column_name, table_names in sorted(tables_by_column.items()):
            involved_tables = [table_name for table_name in table_names if table_name in generated_by_table]
            if len(involved_tables) < 2:
                continue

            values_by_table: dict[str, list[str]] = {}
            for table_name in involved_tables:
                generated_table = generated_by_table[table_name]
                values = _collect_values(generated_table, column_name)
                if values:
                    values_by_table[table_name] = values

            if len(values_by_table) < 2:
                continue

            reference_table = next(iter(values_by_table))
            reference_values = values_by_table[reference_table]
            mismatched_details = []

            for table_name, values in values_by_table.items():
                if table_name == reference_table:
                    continue
                if not all(value in reference_values for value in values):
                    mismatched_details.append(f"{table_name} has values not in {reference_table}")

            if mismatched_details:
                checks.append(
                    ValidationCheck(
                        name=f"cross_table_alignment:{column_name}",
                        passed=False,
                        detail=f"Column '{column_name}' misalignment: {'; '.join(mismatched_details)}",
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        name=f"cross_table_alignment:{column_name}",
                        passed=True,
                        detail=f"Column '{column_name}' is aligned across tables: {', '.join(involved_tables)}",
                    )
                )

        return checks


def _collect_condition_tables_by_column(
    table_plans: list[TableDataPlan],
    excluded_columns: set[str] | None = None,
) -> dict[str, list[str]]:
    skipped = {column_name.lower() for column_name in (excluded_columns or set())}
    tables_by_column: dict[str, list[str]] = {}
    for table_plan in table_plans:
        for column_plan in table_plan.column_plans:
            if column_plan.source != "condition":
                continue
            if column_plan.column_name.lower() in skipped:
                continue
            tables_by_column.setdefault(column_plan.column_name, [])
            if table_plan.table_name not in tables_by_column[column_plan.column_name]:
                tables_by_column[column_plan.column_name].append(table_plan.table_name)
    return tables_by_column


def _collect_values(generated_table: GeneratedTable, column_name: str) -> list[str]:
    ordered: list[str] = []
    for row in generated_table.rows:
        value = row.values.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text and text not in ordered:
            ordered.append(text)
    return ordered


def _collect_explicit_relation_columns(relation_rules: list[RelationRule]) -> set[str]:
    columns: set[str] = set()
    for rule in relation_rules:
        if rule.target_field:
            columns.add(rule.target_field)
        if rule.source_field:
            columns.add(rule.source_field)
    return columns
