from __future__ import annotations

import re

from api_data_gen.domain.models import InterfaceInfo, ScenarioDraft, TableSchema
from api_data_gen.services.ai_utils import parse_json_payload
from api_data_gen.services.fixed_value_service import format_fixed_value_lines


class AiScenarioService:
    def __init__(self, ai_chat_client, max_scenarios: int = 5):
        self._ai_chat_client = ai_chat_client
        self._max_scenarios = max_scenarios

    def generate(
        self,
        requirement_text: str,
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> list[ScenarioDraft]:
        sql_info = _format_interface_sql_info(interface_infos)
        schema_text = _format_table_schemas(schemas)
        user_prompt = (
            "请基于业务需求、接口SQL链路、表结构和固定值约束，生成高价值的P0测试场景。\n\n"
            f"业务需求:\n{requirement_text}\n\n"
            f"接口SQL链路:\n{sql_info}\n\n"
            f"表结构:\n{schema_text}\n\n"
            f"固定字段:\n{format_fixed_value_lines(fixed_values) or '[无]'}\n\n"
            f"依赖固定值:\n{format_fixed_value_lines(dependent_fixed_values) or '[无]'}\n\n"
            "输出要求:\n"
            f"1. 输出严格JSON数组，最多{self._max_scenarios}个场景\n"
            "2. 每个场景字段: name, description, tableRequirements\n"
            "3. tableRequirements 为对象，键是表名，值是该表的数据要求描述\n"
            "4. 避免重复场景，优先覆盖核心正向链路、分页稳定性、字典一致性、跨表关联一致性\n"
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一位资深金融测试架构师，负责生成结构化数据库测试场景。",
            user_prompt=user_prompt,
        )
        payload = parse_json_payload(response)
        if not isinstance(payload, list):
            raise ValueError("AI scenario response must be a JSON array.")

        scenarios: list[ScenarioDraft] = []
        for index, item in enumerate(payload[: self._max_scenarios], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("name") or f"ai_scenario_{index}")
            description = str(item.get("description") or title)
            raw_table_requirements = item.get("tableRequirements") or {}
            if not isinstance(raw_table_requirements, dict):
                raw_table_requirements = {}
            table_requirements = {
                str(table_name): str(requirement)
                for table_name, requirement in raw_table_requirements.items()
            }
            scenarios.append(
                ScenarioDraft(
                    id=f"ai:{_slugify(title)}:{index}",
                    title=title,
                    api_name="multi_api",
                    api_path="",
                    objective=description,
                    request_inputs={},
                    fixed_conditions=[],
                    assertions=[],
                    tables=list(table_requirements),
                    table_requirements=table_requirements,
                    generation_source="ai",
                )
            )
        return scenarios


def _format_interface_sql_info(interface_infos: list[InterfaceInfo]) -> str:
    parts: list[str] = []
    for interface in interface_infos:
        parts.append(f"- 接口: {interface.name} {interface.path}")
        for sql_info in interface.sql_infos:
            conditions = "; ".join(sql_info.conditions) if sql_info.conditions else "[无条件]"
            parts.append(f"  - 表: {sql_info.table_name}; 条件: {conditions}")
    return "\n".join(parts)


def _format_table_schemas(schemas: dict[str, TableSchema]) -> str:
    parts: list[str] = []
    for table_name, schema in schemas.items():
        parts.append(f"表: {table_name}; 主键: {', '.join(schema.primary_keys) or '[无]'}")
        for column in schema.columns:
            constraints = []
            if not column.nullable:
                constraints.append("NOT NULL")
            if column.is_primary_key:
                constraints.append("PRIMARY KEY")
            suffix = f" [{' '.join(constraints)}]" if constraints else ""
            comment = f" // {column.comment}" if column.comment else ""
            parts.append(f"  - {column.name}: {column.type}{suffix}{comment}")
    return "\n".join(parts)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug or "scenario"
