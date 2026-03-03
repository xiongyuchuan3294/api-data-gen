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
            "璇峰熀浜庝笟鍔￠渶姹傘€佹帴鍙QL閾捐矾銆佽〃缁撴瀯鍜屽浐瀹氬€肩害鏉燂紝鐢熸垚楂樹环鍊肩殑P0娴嬭瘯鍦烘櫙銆俓n\n"
            f"涓氬姟闇€姹?\n{requirement_text}\n\n"
            f"鎺ュ彛SQL閾捐矾:\n{sql_info}\n\n"
            f"琛ㄧ粨鏋?\n{schema_text}\n\n"
            f"鍥哄畾瀛楁:\n{format_fixed_value_lines(fixed_values) or '[鏃燷'}\n\n"
            f"渚濊禆鍥哄畾鍊?\n{format_fixed_value_lines(dependent_fixed_values) or '[鏃燷'}\n\n"
            "杈撳嚭瑕佹眰:\n"
            f"1. 杈撳嚭涓ユ牸JSON鏁扮粍锛屾渶澶歿self._max_scenarios}涓満鏅痋n"
            "2. 姣忎釜鍦烘櫙瀛楁: name, description, tableRequirements\n"
            "3. tableRequirements 涓哄璞★紝閿槸琛ㄥ悕锛屽€兼槸璇ヨ〃鐨勬暟鎹姹傛弿杩癨n"
            "4. 閬垮厤閲嶅鍦烘櫙锛屼紭鍏堣鐩栨牳蹇冩鍚戦摼璺€佸垎椤电ǔ瀹氭€с€佸瓧鍏镐竴鑷存€с€佽法琛ㄥ叧鑱斾竴鑷存€n"
        )
        response = self._ai_chat_client.complete(
            system_prompt="浣犳槸涓€浣嶈祫娣遍噾铻嶆祴璇曟灦鏋勫笀锛岃礋璐ｇ敓鎴愮粨鏋勫寲鏁版嵁搴撴祴璇曞満鏅€?,
            user_prompt=user_prompt,
        )
        payload = parse_json_payload(response)
        if not isinstance(payload, list):
            raise ValueError("AI scenario response must be a JSON array.")

        scenarios: list[ScenarioDraft] = []
        for index, item in enumerate(payload[: self._max_scenarios], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("name") or f"AI鍦烘櫙_{index}")
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
        parts.append(f"- 鎺ュ彛: {interface.name} {interface.path}")
        for sql_info in interface.sql_infos:
            conditions = "; ".join(sql_info.conditions) if sql_info.conditions else "[鏃犳潯浠禲"
            parts.append(f"  - 琛? {sql_info.table_name}; 鏉′欢: {conditions}")
    return "\n".join(parts)


def _format_table_schemas(schemas: dict[str, TableSchema]) -> str:
    parts: list[str] = []
    for table_name, schema in schemas.items():
        parts.append(f"琛? {table_name}; 涓婚敭: {', '.join(schema.primary_keys) or '[鏃燷'}")
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

