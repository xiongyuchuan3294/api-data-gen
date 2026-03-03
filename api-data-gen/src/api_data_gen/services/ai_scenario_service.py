from __future__ import annotations

import json
import re

from api_data_gen.domain.models import InterfaceInfo, ScenarioDraft, TableSchema
from api_data_gen.services.ai_utils import parse_json_payload, salvage_json_array_objects
from api_data_gen.services.fixed_value_service import format_fixed_value_lines

_SCENARIO_SCHEMA_COLUMN_LIMIT = 6
_SCENARIO_MAX_OUTPUT_TOKENS = 900
_SCENARIO_REPAIR_MAX_OUTPUT_TOKENS = 1200
_HIGH_VALUE_SCHEMA_FIELDS = {
    "cust_id",
    "fcust_id",
    "model_key",
    "result_key",
    "result_date",
    "alert_date",
    "ds",
    "transactionkey",
    "drft_no",
    "seq_no",
    "trans_time",
    "trans_amount",
    "receive_pay_cd",
    "cust_name",
    "req_nm",
    "rcv_nm",
    "last_req_nm",
    "drwr_nm",
}


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
        user_prompt = self._build_prompt(
            requirement_text=requirement_text,
            interface_infos=interface_infos,
            schemas=schemas,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一名金融测试场景设计专家，负责生成结构化数据库测试场景。",
            user_prompt=user_prompt,
            max_output_tokens=_SCENARIO_MAX_OUTPUT_TOKENS,
        )
        scenarios = self._parse_scenarios(user_prompt, response)
        issues = _multi_interface_issues(interface_infos, scenarios)
        if not issues:
            return scenarios

        retry_prompt = "\n".join(
            [
                user_prompt,
                "",
                "上一次输出未满足以下多接口联合约束，请重新生成：",
                *[f"- {issue}" for issue in issues],
                "",
                "请重新输出完整紧凑行格式，不要附加解释。",
            ]
        )
        retry_response = self._ai_chat_client.complete(
            system_prompt="你是一名金融测试场景设计专家，负责生成结构化数据库测试场景。",
            user_prompt=retry_prompt,
            max_output_tokens=_SCENARIO_MAX_OUTPUT_TOKENS,
        )
        repaired_scenarios = self._parse_scenarios(retry_prompt, retry_response)
        retry_issues = _multi_interface_issues(interface_infos, repaired_scenarios)
        if retry_issues:
            raise ValueError(
                "AI scenario generation did not satisfy multi-interface coverage: "
                + "; ".join(retry_issues)
            )
        return repaired_scenarios

    def _build_prompt(
        self,
        requirement_text: str,
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> str:
        is_multi_interface = len(interface_infos) > 1
        sections = [
            "请基于业务需求、接口 SQL 链路、表结构和固定值约束生成高价值的 P0 测试场景。",
            "",
            "业务需求:",
            requirement_text,
            "",
            "接口 SQL 链路:",
            _format_interface_sql_info(interface_infos),
            "",
            "表结构:",
            _format_table_schemas(schemas),
            "",
            "固定字段:",
            format_fixed_value_lines(fixed_values) or "[无]",
            "",
            "依赖固定值:",
            format_fixed_value_lines(dependent_fixed_values) or "[无]",
        ]
        if is_multi_interface:
            sections.extend(
                [
                    "",
                    "多接口联合测试要求:",
                    f"1. 当前共有 {len(interface_infos)} 个接口，必须从联合链路视角设计场景，而不是给每个接口分别生成一套重复场景。",
                    "2. 用尽量少的场景覆盖尽量多的接口，并保持客户、模型、日期、票据等关键字段在跨接口间一致。",
                    "3. 场景集合必须整体覆盖所有输入接口，且至少有 1 个场景同时覆盖 2 个及以上接口。",
                    "4. 优先设计能串起多个接口公共表、上下游表和跨表约束的场景。",
                ]
            )
        sections.extend(
            [
                "",
                "输出要求:",
                f"1. 优先输出紧凑行格式，最多 {self._max_scenarios} 个场景",
                "2. 紧凑行格式如下:",
                "   SCENARIO|场景名|场景描述",
                "   TABLE|表名|该表的数据要求",
                "   TABLE|表名|该表的数据要求",
                "   空行后开始下一个场景",
                "3. 如果确实无法输出紧凑行格式，再退回 JSON 数组",
                "4. 优先覆盖核心主链路、边界条件、字典约束和跨表一致性",
                "5. 不要输出数组外的解释文字",
            ]
        )
        if is_multi_interface:
            sections.append("6. 不要把每个接口机械拆成独立 baseline 场景，优先输出联合验证场景。")
        return "\n".join(sections)

    def _parse_scenarios(self, prompt: str, response: str) -> list[ScenarioDraft]:
        compact_scenarios = _parse_compact_scenarios(response, self._max_scenarios)
        if compact_scenarios:
            return compact_scenarios
        payload = self._load_payload(prompt, response)
        if not isinstance(payload, list):
            raise ValueError("AI scenario response must be a JSON array.")

        scenarios: list[ScenarioDraft] = []
        for index, item in enumerate(payload[: self._max_scenarios], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("name") or f"AI scenario {index}")
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

    def _load_payload(self, prompt: str, response: str) -> object:
        try:
            return parse_json_payload(response)
        except (json.JSONDecodeError, ValueError) as exc:
            recovered = salvage_json_array_objects(response)
            if recovered:
                return recovered
            repaired = self._repair_payload(prompt, response, str(exc))
            try:
                return parse_json_payload(repaired)
            except (json.JSONDecodeError, ValueError) as repaired_exc:
                recovered = salvage_json_array_objects(repaired)
                if recovered:
                    return recovered
                repaired_again = self._repair_payload(
                    prompt,
                    repaired,
                    (
                        "上一次修复后的内容仍不是合法 JSON。\n"
                        f"错误信息: {repaired_exc}\n"
                        "如果原始内容尾部被截断，请删除不完整对象，只保留可恢复的完整场景数组。"
                    ),
                )
                return parse_json_payload(repaired_again)

    def _repair_payload(self, prompt: str, response: str, error_detail: str) -> str:
        return self._ai_chat_client.complete(
            system_prompt="你是一位 JSON 修复助手，只负责把给定内容修复为合法 JSON。",
            user_prompt=(
                "下面是一次测试场景生成的模型输出，但它不是合法 JSON。\n"
                "请保留原有语义，只输出修复后的 JSON 数组，不要附加解释。\n"
                "如果字符串里包含换行，必须转义为 \\n。\n"
                "如果末尾对象明显被截断，请直接删除不完整尾部，只保留完整场景。\n"
                f"当前解析错误: {error_detail}\n\n"
                f"原始提示:\n{prompt}\n\n"
                f"待修复输出:\n{response}"
            ),
            max_output_tokens=_SCENARIO_REPAIR_MAX_OUTPUT_TOKENS,
        )


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
        primary_keys = ", ".join(schema.primary_keys) or "[无]"
        selected_columns = _select_scenario_columns(schema)
        column_parts: list[str] = []
        for column in selected_columns:
            constraints = []
            if not column.nullable:
                constraints.append("NN")
            if column.is_primary_key:
                constraints.append("PK")
            descriptor = f"{column.name}:{column.type}"
            if column.comment:
                descriptor = f"{descriptor}({column.comment})"
            if constraints:
                descriptor = f"{descriptor}[{'/'.join(constraints)}]"
            column_parts.append(descriptor)
        omitted_count = max(0, len(schema.columns) - len(selected_columns))
        summary = ", ".join(column_parts)
        if omitted_count:
            summary = f"{summary}, ...省略{omitted_count}列"
        parts.append(f"表: {table_name}; 主键: {primary_keys}; 关键字段: {summary}")
    return "\n".join(parts)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug or "scenario"


def _multi_interface_issues(
    interface_infos: list[InterfaceInfo],
    scenarios: list[ScenarioDraft],
) -> list[str]:
    if len(interface_infos) <= 1:
        return []
    if not scenarios:
        return ["未生成任何测试场景"]

    interface_tables = {
        _interface_label(interface): {
            sql_info.table_name
            for sql_info in interface.sql_infos
            if sql_info.table_name
        }
        for interface in interface_infos
    }
    covered_interfaces: set[str] = set()
    has_joint_scenario = False

    for scenario in scenarios:
        scenario_tables = set(scenario.tables) or set(scenario.table_requirements)
        covered_by_scenario = {
            label
            for label, tables in interface_tables.items()
            if tables and scenario_tables.intersection(tables)
        }
        covered_interfaces.update(covered_by_scenario)
        if len(covered_by_scenario) > 1:
            has_joint_scenario = True

    issues: list[str] = []
    missing_interfaces = [label for label in interface_tables if label not in covered_interfaces]
    if missing_interfaces:
        issues.append(f"未覆盖所有输入接口: {', '.join(missing_interfaces)}")
    if not has_joint_scenario:
        issues.append("没有任何场景同时覆盖两个及以上接口")
    return issues


def _interface_label(interface: InterfaceInfo) -> str:
    return interface.name or interface.path or "[unknown]"


def _parse_compact_scenarios(response: str, max_scenarios: int) -> list[ScenarioDraft]:
    lines = _compact_lines(response)
    if not any(line.startswith("SCENARIO|") for line in lines):
        return []

    scenarios: list[ScenarioDraft] = []
    current_name = ""
    current_description = ""
    current_requirements: dict[str, str] = {}

    def flush_current() -> None:
        nonlocal current_name, current_description, current_requirements
        if not current_name:
            return
        index = len(scenarios) + 1
        scenarios.append(
            ScenarioDraft(
                id=f"ai:{_slugify(current_name)}:{index}",
                title=current_name,
                api_name="multi_api",
                api_path="",
                objective=current_description or current_name,
                request_inputs={},
                fixed_conditions=[],
                assertions=[],
                tables=list(current_requirements),
                table_requirements=dict(current_requirements),
                generation_source="ai",
            )
        )
        current_name = ""
        current_description = ""
        current_requirements = {}

    for line in lines:
        if line.startswith("SCENARIO|"):
            flush_current()
            parts = _split_compact_fields(line, 3)
            if len(parts) < 3:
                continue
            current_name = parts[1]
            current_description = parts[2]
            if len(scenarios) >= max_scenarios:
                break
            continue
        if line.startswith("TABLE|") and current_name:
            parts = _split_compact_fields(line, 3)
            if len(parts) < 3:
                continue
            current_requirements[parts[1]] = parts[2]

    flush_current()
    return scenarios[:max_scenarios]


def _select_scenario_columns(schema: TableSchema) -> list:
    ranked_columns = sorted(
        schema.columns,
        key=lambda column: (
            _scenario_column_rank(column),
            schema.columns.index(column),
        ),
    )
    return ranked_columns[:_SCENARIO_SCHEMA_COLUMN_LIMIT]


def _scenario_column_rank(column) -> tuple[int, int]:
    name = column.name.lower()
    comment = column.comment.lower()
    keyword_score = 0
    if name in _HIGH_VALUE_SCHEMA_FIELDS:
        keyword_score -= 2
    if any(keyword in comment for keyword in ("客户", "模型", "日期", "时间", "票", "金额", "收付", "请求方", "接收方", "交易")):
        keyword_score -= 1
    return (
        0 if column.is_primary_key else 1,
        0 if name in _HIGH_VALUE_SCHEMA_FIELDS else 1,
        0 if keyword_score < 0 else 1,
        0 if not column.nullable else 1,
    )


def _compact_lines(text: str) -> list[str]:
    stripped = re.sub(r"```(?:text|json|yaml)?", "", text or "", flags=re.IGNORECASE)
    return [line.strip() for line in stripped.splitlines() if line.strip()]


def _split_compact_fields(line: str, max_parts: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escape = False
    for char in line:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == "|" and len(parts) < max_parts - 1:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts
