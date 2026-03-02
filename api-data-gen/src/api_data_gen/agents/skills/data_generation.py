"""
数据生成技能

提供测试数据生成的能力
"""
from __future__ import annotations

from typing import Any

from .decorator import skill

# 技能容器 - 通过 init_skills 初始化
_skill_container: dict[str, Any] = {}


def init_skills(
    ai_data_generation_service=None,
    ai_data_analysis_service=None,
    local_field_rule_service=None,
):
    """初始化技能容器"""
    global _skill_container
    _skill_container = {
        "ai_data_generation_service": ai_data_generation_service,
        "ai_data_analysis_service": ai_data_analysis_service,
        "local_field_rule_service": local_field_rule_service,
    }


@skill(
    name="generate_table_rows_ai",
    description="由外部模型生成测试数据行",
    category="generation",
)
def generate_table_rows_ai(
    table_name: str,
    table_schema: dict,
    scenario: dict,
    sample_rows: list[dict] | None = None,
    fixed_values: list[str] | None = None,
    generation_tag: str | None = None,
) -> list[dict]:
    """
    使用 AI 生成测试数据行。

    :param table_name: 表名
    :param table_schema: 表结构
    :param scenario: 场景信息
    :param sample_rows: 样本数据（可选）
    :param fixed_values: 固定值约束
    :param generation_tag: 生成标签
    :return: 生成的数据行列表
    """
    ai_data_generation_service = _skill_container.get("ai_data_generation_service")
    if ai_data_generation_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    from api_data_gen.domain.models import TableSchema as DomainTableSchema, Column

    # 转换表结构
    columns = [
        Column(
            name=col["name"],
            type=col.get("type", "varchar"),
            nullable=col.get("nullable", True),
            is_primary_key=col.get("is_primary_key", False),
            comment=col.get("comment", ""),
        )
        for col in table_schema.get("columns", [])
    ]
    schema = DomainTableSchema(
        table_name=table_name,
        columns=columns,
        primary_keys=table_schema.get("primary_keys", []),
    )

    # 调用服务
    result = ai_data_generation_service.generate(
        table_name=table_name,
        schema=schema,
        scenario=scenario,
        sample_rows=sample_rows or [],
        fixed_values=fixed_values or [],
        generation_tag=generation_tag,
    )

    # 返回生成的行
    return result if isinstance(result, list) else []


@skill(
    name="generate_table_rows_local",
    description="使用本地规则生成测试数据行",
    category="generation",
)
def generate_table_rows_local(
    table_name: str,
    table_schema: dict,
    column_plans: list[dict],
    row_count: int = 1,
) -> list[dict]:
    """
    使用本地规则生成测试数据行。

    :param table_name: 表名
    :param table_schema: 表结构
    :param column_plans: 列生成计划
    :param row_count: 生成行数
    :return: 生成的数据行列表
    """
    local_field_rule_service = _skill_container.get("local_field_rule_service")
    if local_field_rule_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    from api_data_gen.domain.models import TableSchema as DomainTableSchema, Column, ColumnPlan

    # 转换表结构
    columns = [
        Column(
            name=col["name"],
            type=col.get("type", "varchar"),
            nullable=col.get("nullable", True),
            is_primary_key=col.get("is_primary_key", False),
            comment=col.get("comment", ""),
        )
        for col in table_schema.get("columns", [])
    ]
    schema = DomainTableSchema(
        table_name=table_name,
        columns=columns,
        primary_keys=table_schema.get("primary_keys", []),
    )

    # 转换列计划
    plans = [
        ColumnPlan(
            column_name=p["column_name"],
            source=p.get("source", "generated"),
            required=p.get("required", True),
            suggested_values=p.get("suggested_values", []),
            rationale=p.get("rationale", ""),
        )
        for p in column_plans
    ]

    # 生成行
    rows = []
    for i in range(row_count):
        row = {}
        for plan in plans:
            value = local_field_rule_service.generate_value(
                schema=schema,
                column_name=plan.column_name,
                source=plan.source,
                suggested_values=plan.suggested_values,
                row_index=i,
            )
            row[plan.column_name] = value
        rows.append(row)

    return rows


@skill(
    name="merge_and_validate_rows",
    description="合并本地/AI结果并执行记录级校验",
    category="validation",
)
def merge_and_validate_rows(
    local_rows: list[dict],
    ai_rows: list[dict],
    table_schema: dict,
) -> dict:
    """
    合并本地和AI生成的数据，并进行校验。

    :param local_rows: 本地生成的数据行
    :param ai_rows: AI生成的数据行
    :param table_schema: 表结构
    :return: {validated_rows: [], checks: []}
    """
    # 合并行
    all_rows = []
    if local_rows:
        all_rows.extend(local_rows)
    if ai_rows:
        # AI行可能需要去重或特殊处理
        for row in ai_rows:
            if row not in all_rows:
                all_rows.append(row)

    # 简单校验：检查必填字段
    checks = []
    required_columns = [
        col["name"] for col in table_schema.get("columns", [])
        if not col.get("nullable", True)
    ]

    for idx, row in enumerate(all_rows):
        for col in required_columns:
            if col not in row or row[col] is None or row[col] == "":
                checks.append({
                    "type": "missing_required",
                    "row_index": idx,
                    "column": col,
                    "passed": False,
                })

    return {
        "validated_rows": all_rows,
        "checks": checks,
    }


@skill(
    name="render_insert_sql",
    description="把记录渲染为 INSERT SQL",
    category="sql",
)
def render_insert_sql(
    table_name: str,
    rows: list[dict],
    generation_tag: str | None = None,
) -> list[str]:
    """
    将数据行渲染为 INSERT SQL 语句。

    :param table_name: 表名
    :param rows: 数据行列表
    :param generation_tag: 生成标签
    :return: INSERT SQL 语句列表
    """
    from api_data_gen.services.insert_render_service import InsertRenderService

    renderer = InsertRenderService()
    sqls = []

    for row in rows:
        sql = renderer.render(
            table_name=table_name,
            row=row,
            generation_tag=generation_tag,
        )
        if sql:
            sqls.append(sql)

    return sqls
