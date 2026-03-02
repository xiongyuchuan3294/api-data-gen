"""
场景生成技能

提供测试场景生成的能力
"""
from __future__ import annotations

from typing import Any

from .decorator import skill

# 技能容器 - 通过 init_skills 初始化
_skill_container: dict[str, Any] = {}


def init_skills(
    ai_scenario_service=None,
    ai_data_generation_service=None,
    local_field_rule_service=None,
):
    """初始化技能容器"""
    global _skill_container
    _skill_container = {
        "ai_scenario_service": ai_scenario_service,
        "ai_data_generation_service": ai_data_generation_service,
        "local_field_rule_service": local_field_rule_service,
    }


@skill(
    name="generate_scenarios_ai",
    description="由外部模型直接生成测试场景",
    category="scenario",
)
def generate_scenarios_ai(
    requirement: str,
    interface_sql_info: list[dict],
    table_schemas: dict[str, dict],
    fixed_values: list[str] | None = None,
    dependent_fixed_values: list[str] | None = None,
) -> list[dict]:
    """
    基于业务需求、接口SQL链路、表结构生成高价值测试场景。

    :param requirement: 业务需求描述
    :param interface_sql_info: 接口SQL链路信息列表
    :param table_schemas: 表结构字典 {表名: {columns: [...], primary_keys: [...]}}
    :param fixed_values: 固定字段约束
    :param dependent_fixed_values: 依赖固定值约束
    :return: 场景列表 (JSON 序列化)
    """
    from api_data_gen.domain.models import InterfaceInfo, InterfaceSqlInfo, TableSchema, Column

    ai_scenario_service = _skill_container.get("ai_scenario_service")
    if ai_scenario_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    # 转换接口信息
    interface_infos = []
    for info in interface_sql_info:
        sql_infos = [
            InterfaceSqlInfo(
                table_name=sql.get("table_name", ""),
                operation=sql.get("operation", "SELECT"),
                conditions=sql.get("conditions", []),
            )
            for sql in info.get("sql_infos", [])
        ]
        interface_infos.append(
            InterfaceInfo(
                name=info.get("name", ""),
                path=info.get("path", ""),
                sql_infos=sql_infos,
            )
        )

    # 转换表结构
    schemas = {}
    for table_name, schema_dict in table_schemas.items():
        columns = [
            Column(
                name=col["name"],
                type=col.get("type", "varchar"),
                nullable=col.get("nullable", True),
                is_primary_key=col.get("is_primary_key", False),
                comment=col.get("comment", ""),
            )
            for col in schema_dict.get("columns", [])
        ]
        schemas[table_name] = TableSchema(
            table_name=table_name,
            columns=columns,
            primary_keys=schema_dict.get("primary_keys", []),
        )

    # 调用服务
    scenarios = ai_scenario_service.generate(
        requirement_text=requirement,
        interface_infos=interface_infos,
        schemas=schemas,
        fixed_values=fixed_values,
        dependent_fixed_values=dependent_fixed_values,
    )

    # 转换为可序列化的字典
    return [
        {
            "id": s.id,
            "title": s.title,
            "api_name": s.api_name,
            "api_path": s.api_path,
            "objective": s.objective,
            "tables": s.tables,
            "table_requirements": s.table_requirements,
            "fixed_conditions": s.fixed_conditions,
            "request_inputs": s.request_inputs,
        }
        for s in scenarios
    ]


@skill(
    name="generate_scenarios_local",
    description="基于接口行为和规则生成本地参考场景",
    category="scenario",
)
def generate_scenarios_local(
    requirement: str,
    interface_sql_info: list[dict],
    table_schemas: dict[str, dict],
) -> list[dict]:
    """
    基于接口 trace 信息和规则生成本地场景。

    :param requirement: 业务需求描述
    :param interface_sql_info: 接口SQL链路信息
    :param table_schemas: 表结构字典
    :return: 本地场景列表
    """
    # 这里简化处理，实际可以调用 PlanningService 的本地场景生成
    # 返回一个简单的 baseline 场景
    tables = set()
    for info in interface_sql_info:
        for sql in info.get("sql_infos", []):
            tables.add(sql.get("table_name", ""))

    return [
        {
            "id": "local:baseline",
            "title": "Baseline 回放场景",
            "objective": "回放接口最新样例，验证核心 SQL 过滤条件",
            "tables": list(tables),
            "table_requirements": {
                t: "满足接口 SQL 过滤条件"
                for t in tables
            },
        }
    ]


@skill(
    name="analyze_samples_ai",
    description="由外部模型分析样本特征与字段模式",
    category="analysis",
)
def analyze_samples_ai(
    table_name: str,
    sample_rows: list[dict],
    table_schema: dict | None = None,
) -> dict:
    """
    分析样本数据的特征和模式。

    :param table_name: 表名
    :param sample_rows: 样本数据行
    :param table_schema: 表结构信息（可选）
    :return: 分析结果字典
    """
    ai_data_analysis_service = _skill_container.get("ai_data_analysis_service")
    if ai_data_analysis_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    # 转换为领域模型
    from api_data_gen.domain.models import TableSchema, Column

    schema = None
    if table_schema:
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

    # 调用服务
    analysis = ai_data_analysis_service.analyze(
        table_name=table_name,
        sample_rows=sample_rows,
        schema=schema,
    )

    return analysis if isinstance(analysis, dict) else {}


@skill(
    name="resolve_local_generators",
    description="识别适合本地规则生成的字段",
    category="analysis",
)
def resolve_local_generators(table_schema: dict) -> list[str]:
    """
    识别适合使用本地规则生成的字段。

    :param table_schema: 表结构信息
    :return: 本地字段名列表
    """
    from api_data_gen.domain.models import TableSchema, Column

    local_field_rule_service = _skill_container.get("local_field_rule_service")
    if local_field_rule_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

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
        table_name=table_schema.get("table_name", ""),
        columns=columns,
        primary_keys=table_schema.get("primary_keys", []),
    )

    # 识别本地字段
    local_fields = local_field_rule_service.identify_local_fields(schema)

    return local_fields
