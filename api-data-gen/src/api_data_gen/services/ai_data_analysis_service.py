from __future__ import annotations

from api_data_gen.domain.models import TableSchema
from api_data_gen.services.fixed_value_service import format_fixed_value_lines


class AiDataAnalysisService:
    def __init__(self, ai_chat_client):
        self._ai_chat_client = ai_chat_client

    def analyze(
        self,
        table_name: str,
        schema: TableSchema,
        sample_rows: list[dict[str, str]],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> str:
        sample_preview = sample_rows[:5]
        prompt = (
            f"表名: {table_name}\n"
            f"表结构: {schema}\n"
            f"样本数据: {sample_preview}\n"
            f"固定字段: {format_fixed_value_lines(fixed_values) or '[无]'}\n"
            f"依赖固定值: {format_fixed_value_lines(dependent_fixed_values) or '[无]'}\n\n"
            "请分析字段格式、唯一性、常见取值模式、字段关联，并输出简洁JSON对象，键为字段名，值为生成建议。"
        )
        return self._ai_chat_client.complete(
            system_prompt="你是一位数据库测试数据分析专家，负责总结样本数据生成模式。",
            user_prompt=prompt,
        )
