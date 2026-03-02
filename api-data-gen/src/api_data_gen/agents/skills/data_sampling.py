"""
数据采样技能

提供从业务表采样数据的能力
"""
from __future__ import annotations

from typing import Any

from .decorator import skill

# 技能容器 - 通过 init_skills 初始化
_skill_container: dict[str, Any] = {}


def init_skills(
    sample_repository,
    schema_repository=None,
    interface_trace_service=None,
    schema_service=None,
):
    """初始化技能容器"""
    global _skill_container
    _skill_container = {
        "sample_repository": sample_repository,
        "schema_repository": schema_repository,
        "interface_trace_service": interface_trace_service,
        "schema_service": schema_service,
    }


@skill(
    name="sample_table_data",
    description="采样业务表数据供后续推理和补数使用",
    category="data",
)
def sample_table_data(
    table_name: str,
    limit: int = 3,
) -> list[dict]:
    """
    从业务表采样数据行。

    :param table_name: 表名
    :param limit: 采样行数，默认3行
    :return: 采样数据行列表
    """
    sample_repository = _skill_container.get("sample_repository")
    if sample_repository is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    rows = sample_repository.sample_rows(table_name, limit)
    return rows


@skill(
    name="sample_multiple_tables",
    description="批量采样多个表的数据",
    category="data",
)
def sample_multiple_tables(
    tables: list[str],
    limit: int = 3,
) -> dict[str, list[dict]]:
    """
    批量采样多个表的数据。

    :param tables: 表名列表
    :param limit: 每个表采样行数
    :return: {表名: 数据行列表} 的字典
    """
    sample_repository = _skill_container.get("sample_repository")
    if sample_repository is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    result = {}
    for table_name in tables:
        try:
            rows = sample_repository.sample_rows(table_name, limit)
            if rows:
                result[table_name] = rows
        except Exception as e:
            # 记录错误但继续处理其他表
            result[table_name] = {"error": str(e)}
    return result


@skill(
    name="load_table_schema",
    description="加载并标准化目标表 schema",
    category="schema",
)
def load_table_schema(table_name: str) -> dict | None:
    """
    加载表结构信息。

    :param table_name: 表名
    :return: 表结构信息字典，包含列、主键等
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


@skill(
    name="load_multiple_schemas",
    description="批量加载多个表的 schema",
    category="schema",
)
def load_multiple_schemas(tables: list[str]) -> dict[str, dict]:
    """
    批量加载多个表的结构信息。

    :param tables: 表名列表
    :return: {表名: schema信息} 的字典
    """
    schema_repository = _skill_container.get("schema_repository")
    if schema_repository is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    result = {}
    for table_name in tables:
        try:
            schema = schema_repository.get_table_schema(table_name)
            if schema:
                result[table_name] = {
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
        except Exception as e:
            result[table_name] = {"error": str(e)}
    return result
