from __future__ import annotations

from api_data_gen.domain.models import ScenarioDraft, TableSchema
from api_data_gen.services.ai_utils import parse_json_payload
from api_data_gen.services.fixed_value_service import format_fixed_value_lines


class AiDataGenerationService:
    def __init__(self, ai_chat_client):
        self._ai_chat_client = ai_chat_client

    def generate(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        prompt = self._build_prompt(
            scenario,
            schemas,
            sample_rows_by_table,
            local_generated_columns,
            analysis_by_table,
            fixed_values,
            dependent_fixed_values,
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一位数据库测试数据生成专家，负责为给定测试场景生成结构化表数据。",
            user_prompt=prompt,
        )
        payload = parse_json_payload(response)
        if not isinstance(payload, list):
            raise ValueError("AI data generation response must be a JSON array.")

        result: dict[str, list[dict[str, str]]] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            table_name = str(item.get("table") or "")
            if not table_name:
                continue
            raw_data = item.get("data")
            rows = _normalize_rows(raw_data)
            if rows:
                result.setdefault(table_name, []).extend(rows)
        return result

    def _build_prompt(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
    ) -> str:
        sections = [
            "测试场景:",
            f"- 名称: {scenario.title}",
            f"- 描述: {scenario.objective}",
            f"- 表需求: {scenario.table_requirements or {table: '' for table in scenario.tables}}",
            "",
            f"固定字段: {format_fixed_value_lines(fixed_values) or '[无]'}",
            f"依赖固定值: {format_fixed_value_lines(dependent_fixed_values) or '[无]'}",
            "",
            "以下字段由本地规则生成，不需要你输出:",
            str({table: sorted(values) for table, values in local_generated_columns.items()}),
            "",
        ]
        for table_name, schema in schemas.items():
            sections.extend(
                [
                    f"表: {table_name}",
                    f"结构: {schema}",
                    f"样本: {sample_rows_by_table.get(table_name, [])[:5]}",
                    f"分析建议: {analysis_by_table.get(table_name, '{}')}",
                    "",
                ]
            )
        sections.extend(
            [
                "输出要求:",
                "1. 严格输出 JSON 数组",
                "2. 每个元素格式为 {\"table\": \"表名\", \"data\": {...}} 或 {\"table\": \"表名\", \"data\": [{...}]}",
                "3. 只生成本地规则未覆盖的字段",
                "4. 保持跨表字段一致性，不要输出额外解释",
            ]
        )
        return "\n".join(sections)


def _normalize_rows(raw_data: object) -> list[dict[str, str]]:
    if isinstance(raw_data, dict):
        return [{str(key): str(value) for key, value in raw_data.items()}]
    if isinstance(raw_data, list):
        rows: list[dict[str, str]] = []
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            rows.append({str(key): str(value) for key, value in item.items()})
        return rows
    return []
