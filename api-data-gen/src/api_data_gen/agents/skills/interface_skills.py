"""
接口和 Schema 技能

提供接口追踪和表结构相关的技能
"""
from __future__ import annotations

from typing import Any

from .decorator import skill

# 技能容器 - 通过 init_skills 初始化
_skill_container: dict[str, Any] = {}


def init_skills(
    interface_trace_service=None,
    schema_service=None,
    schema_repository=None,
):
    """初始化技能容器"""
    global _skill_container
    _skill_container = {
        "interface_trace_service": interface_trace_service,
        "schema_service": schema_service,
        "schema_repository": schema_repository,
    }


@skill(
    name="extract_interface_sql",
    description="提取接口 trace、SQL、表和过滤条件",
    category="interface",
)
def extract_interface_sql(
    api_name: str,
    api_path: str,
) -> dict:
    """
    从接口 trace 提取 SQL 链路信息。

    :param api_name: 接口名称
    :param api_path: 接口路径
    :return: 接口 SQL 链路信息
    """
    interface_trace_service = _skill_container.get("interface_trace_service")
    if interface_trace_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    result = interface_trace_service.get_table_info(api_name, api_path)

    return {
        "name": result.name,
        "path": result.path,
        "sql_infos": [
            {
                "table_name": sql.table_name,
                "operation": sql.operation,
                "conditions": sql.conditions,
            }
            for sql in result.sql_infos
        ],
    }


@skill(
    name="build_table_plans_local",
    description="根据 SQL 条件、schema 和样本构建表级造数计划",
    category="planning",
)
def build_table_plans_local(
    table_name: str,
    table_schema: dict,
    conditions: list[str] | None = None,
    sample_rows: list[dict] | None = None,
    fixed_values: list[str] | None = None,
) -> list[dict]:
    """
    构建表级造数计划。

    :param table_name: 表名
    :param table_schema: 表结构
    :param conditions: SQL 条件
    :param sample_rows: 样本数据
    :param fixed_values: 固定值
    :return: 列计划列表
    """
    from api_data_gen.domain.models import TableSchema, Column, ColumnPlan
    from api_data_gen.services.local_field_rule_service import LocalFieldRuleService

    local_field_rule_service = _skill_container.get("local_field_rule_service")
    if local_field_rule_service is None:
        # 创建临时服务
        from api_data_gen.services.dict_rule_resolver import DictRuleResolver
        from api_data_gen.infra.db.dict_repository import DictRepository
        from api_data_gen.config import load_settings
        settings = load_settings()
        # 这里简化处理
        local_field_rule_service = None

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
    schema = TableSchema(
        table_name=table_name,
        columns=columns,
        primary_keys=table_schema.get("primary_keys", []),
    )

    # 构建列计划
    column_plans = []

    # 从条件中提取值
    condition_values = _extract_condition_values(conditions or [])

    for column in schema.columns:
        # 检查是否来自条件
        if column.name in condition_values:
            column_plans.append({
                "column_name": column.name,
                "source": "condition",
                "required": True,
                "suggested_values": condition_values[column.name],
                "rationale": f"来自SQL过滤器: {conditions}",
            })
            continue

        # 检查是否为主键
        if column.is_primary_key:
            column_plans.append({
                "column_name": column.name,
                "source": "generated",
                "required": True,
                "suggested_values": [],
                "rationale": "主键应唯一生成",
            })
            continue

        # 从样本中提取值
        if sample_rows:
            sample_values = _extract_sample_values(sample_rows, column.name)
            if sample_values:
                column_plans.append({
                    "column_name": column.name,
                    "source": "sample",
                    "required": not column.nullable,
                    "suggested_values": sample_values[:5],
                    "rationale": "从采样的业务行中观察",
                })
                continue

        # 必填字段使用默认值
        if not column.nullable:
            column_plans.append({
                "column_name": column.name,
                "source": "default",
                "required": True,
                "suggested_values": [_default_value_for_type(column.type)],
                "rationale": "Non-null column without sample or dictionary value",
            })
        else:
            column_plans.append({
                "column_name": column.name,
                "source": "optional",
                "required": False,
                "suggested_values": [],
                "rationale": "Nullable column",
            })

    return column_plans


def _extract_condition_values(conditions: list[str]) -> dict[str, list[str]]:
    """从 SQL 条件中提取列值"""
    import re
    values = {}

    # 匹配格式: column = 'value'
    pattern = re.compile(r"`?(\w+)`?\s*=\s*'(.+?)'")

    for condition in conditions:
        match = pattern.search(condition)
        if match:
            col_name = match.group(1)
            value = match.group(2)
            if col_name not in values:
                values[col_name] = []
            if value not in values[col_name]:
                values[col_name].append(value)

    return values


def _extract_sample_values(sample_rows: list[dict], column_name: str) -> list[str]:
    """从样本中提取列值"""
    values = []
    for row in sample_rows:
        if column_name in row:
            value = row[column_name]
            if value and value not in ("[NULL]", "[DEFAULT]"):
                values.append(value)
    return list(dict.fromkeys(values))  # 去重保持顺序


def _default_value_for_type(data_type: str) -> str:
    """根据数据类型返回默认值"""
    lowered = data_type.lower()
    if "int" in lowered or "decimal" in lowered or "float" in lowered or "double" in lowered:
        return "0"
    if "date" in lowered or "time" in lowered:
        return "1970-01-01"
    return "[DEFAULT]"


@skill(
    name="load_table_schema",
    description="加载并标准化目标表 schema",
    category="schema",
)
def load_table_schema_skill(table_name: str) -> dict | None:
    """
    加载表结构信息。

    :param table_name: 表名
    :return: 表结构信息字典
    """
    schema_repository = _skill_container.get("schema_repository")
    if schema_repository is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    schema = schema_repository.get_table_schema(table_name)
    if schema is None:
        return None

    return {
        "table_name": schema.table_name,
        "columns": [
            {
                "name": col.name,
                "type": col.type,
                "nullable": col.nullable,
                "is_primary_key": col.is_primary_key,
                "comment": col.comment,
            }
            for col in schema.columns
        ],
        "primary_keys": schema.primary_keys,
    }
