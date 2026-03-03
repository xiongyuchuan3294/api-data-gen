from __future__ import annotations

from api_data_gen.domain.models import GeneratedTable, TableDataPlan, ValidationCheck


class CrossTableValidationService:
    def validate(self, table_plans: list[TableDataPlan], generated_tables: list[GeneratedTable]) -> list[ValidationCheck]:
        """
        验证跨表字段对齐情况，确保跨表共享字段的值一致性。

        :param table_plans: 表数据计划列表
        :param generated_tables: 已生成的表数据列表
        :return: 验证检查列表
        """
        checks: list[ValidationCheck] = []
        tables_by_column = _collect_tables_by_column(table_plans)

        generated_by_table = {generated_table.table_name: generated_table for generated_table in generated_tables}

        for column_name, table_names in sorted(tables_by_column.items()):
            involved_tables = [table_name for table_name in table_names if table_name in generated_by_table]
            if len(involved_tables) < 2:
                continue

            # 收集各表在该列的值
            values_by_table: dict[str, list[str]] = {}
            for table_name in involved_tables:
                generated_table = generated_by_table[table_name]
                values = _collect_values(generated_table, column_name)
                if values:
                    values_by_table[table_name] = values

            # 如果少于2个表有值，跳过验证
            if len(values_by_table) < 2:
                continue

            # 验证值的一致性
            reference_table = next(iter(values_by_table))
            reference_values = values_by_table[reference_table]

            all_aligned = True
            mismatched_details = []

            for table_name, values in values_by_table.items():
                if table_name == reference_table:
                    continue

                # 检查当前表的值是否都是参考表值的子集
                if not all(value in reference_values for value in values):
                    all_aligned = False
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


def _collect_tables_by_column(table_plans: list[TableDataPlan]) -> dict[str, list[str]]:
    """收集包含相同列名的表"""
    tables_by_column: dict[str, list[str]] = {}
    for table_plan in table_plans:
        primary_keys = set(table_plan.primary_keys)
        for column_plan in table_plan.column_plans:
            # 跳过主键列
            if column_plan.column_name in primary_keys:
                continue
            tables_by_column.setdefault(column_plan.column_name, [])
            if table_plan.table_name not in tables_by_column[column_plan.column_name]:
                tables_by_column[column_plan.column_name].append(table_plan.table_name)
    return tables_by_column


def _collect_values(generated_table: GeneratedTable, column_name: str) -> list[str]:
    """从生成的表中收集指定列的所有非空唯一值"""
    ordered: list[str] = []
    for row in generated_table.rows:
        value = row.values.get(column_name)
        if value is None:
            continue
        text = str(value)
        if text and text not in ordered:
            ordered.append(text)
    return ordered
