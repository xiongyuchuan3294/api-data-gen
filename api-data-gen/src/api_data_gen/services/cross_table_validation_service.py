from __future__ import annotations

from api_data_gen.domain.models import GeneratedTable, TableDataPlan, ValidationCheck


class CrossTableValidationService:
    def validate(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[ValidationCheck]:
        generated_by_table = {generated_table.table_name: generated_table for generated_table in generated_tables}
        checks: list[ValidationCheck] = []

        expected_by_column = _collect_expected_values(table_plans)
        for column_name, expected_values in sorted(expected_by_column.items()):
            involved_tables = _collect_involved_tables(table_plans, generated_by_table, column_name)
            if len(involved_tables) < 2:
                continue

            normalized_expected = sorted(expected_values)
            actual_by_table: dict[str, list[str]] = {}
            passed = len(normalized_expected) == 1
            if not passed:
                detail = (
                    f"conflicting fixed values for {column_name}: {', '.join(normalized_expected)}"
                )
                checks.append(
                    ValidationCheck(
                        name=f"cross_table:{column_name}",
                        passed=False,
                        detail=detail,
                    )
                )
                continue

            expected_value = normalized_expected[0]
            for table_name in involved_tables:
                actual_values = _collect_actual_values(generated_by_table[table_name], column_name)
                actual_by_table[table_name] = actual_values
                if not actual_values or any(value != expected_value for value in actual_values):
                    passed = False

            checks.append(
                ValidationCheck(
                    name=f"cross_table:{column_name}",
                    passed=passed,
                    detail=_build_detail(column_name, expected_value, actual_by_table),
                )
            )

        checks.extend(_build_shared_column_checks(table_plans, generated_by_table, expected_by_column))
        return checks


def _collect_expected_values(table_plans: list[TableDataPlan]) -> dict[str, set[str]]:
    expected_by_column: dict[str, set[str]] = {}
    for table_plan in table_plans:
        primary_keys = set(table_plan.primary_keys)
        for column_plan in table_plan.column_plans:
            if column_plan.column_name in primary_keys:
                continue
            if column_plan.source != "condition":
                continue
            values = {value for value in column_plan.suggested_values if value and value != "[NULL]"}
            if not values:
                continue
            expected_by_column.setdefault(column_plan.column_name, set()).update(values)
    return expected_by_column


def _collect_involved_tables(
    table_plans: list[TableDataPlan],
    generated_by_table: dict[str, GeneratedTable],
    column_name: str,
) -> list[str]:
    tables: list[str] = []
    for table_plan in table_plans:
        if table_plan.table_name not in generated_by_table:
            continue
        if any(column_plan.column_name == column_name for column_plan in table_plan.column_plans):
            tables.append(table_plan.table_name)
    return tables


def _collect_actual_values(generated_table: GeneratedTable, column_name: str) -> list[str]:
    ordered: list[str] = []
    for row in generated_table.rows:
        value = row.values.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered


def _build_detail(column_name: str, expected_value: str, actual_by_table: dict[str, list[str]]) -> str:
    actual_text = "; ".join(
        f"{table_name}={actual_by_table[table_name] or ['[NULL]']}"
        for table_name in sorted(actual_by_table)
    )
    return f"{column_name} expected {expected_value}; actual {actual_text}"


def _build_shared_column_checks(
    table_plans: list[TableDataPlan],
    generated_by_table: dict[str, GeneratedTable],
    expected_by_column: dict[str, set[str]],
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    primary_keys_by_table = {table_plan.table_name: set(table_plan.primary_keys) for table_plan in table_plans}
    columns_by_table: dict[str, list[str]] = {}
    for table_plan in table_plans:
        if table_plan.table_name not in generated_by_table:
            continue
        for column_plan in table_plan.column_plans:
            if column_plan.column_name in primary_keys_by_table[table_plan.table_name]:
                continue
            if column_plan.column_name in expected_by_column:
                continue
            columns_by_table.setdefault(column_plan.column_name, [])
            if table_plan.table_name not in columns_by_table[column_plan.column_name]:
                columns_by_table[column_plan.column_name].append(table_plan.table_name)

    for column_name, table_names in sorted(columns_by_table.items()):
        if len(table_names) < 2:
            continue
        actual_by_table = {
            table_name: _collect_actual_values(generated_by_table[table_name], column_name)
            for table_name in table_names
        }
        non_empty_sets = [set(values) for values in actual_by_table.values() if values]
        if len(non_empty_sets) < 2:
            continue
        shared_values = set(non_empty_sets[0])
        for values in non_empty_sets[1:]:
            shared_values &= values
        checks.append(
            ValidationCheck(
                name=f"shared_column:{column_name}",
                passed=bool(shared_values),
                detail=_build_shared_detail(column_name, actual_by_table, shared_values),
            )
        )
    return checks


def _build_shared_detail(column_name: str, actual_by_table: dict[str, list[str]], shared_values: set[str]) -> str:
    actual_text = "; ".join(
        f"{table_name}={actual_by_table[table_name] or ['[NULL]']}"
        for table_name in sorted(actual_by_table)
    )
    shared_text = sorted(shared_values) if shared_values else ["[EMPTY]"]
    return f"{column_name} shared intersection {shared_text}; actual {actual_text}"
