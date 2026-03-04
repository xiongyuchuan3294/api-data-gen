from __future__ import annotations

import json
import re

from api_data_gen.domain.models import InterfaceInfo, RelationRule, ScenarioDraft, TableSchema
from api_data_gen.services.ai_utils import parse_json_payload, salvage_json_array_objects
from api_data_gen.services.fixed_value_service import format_fixed_value_lines

_SCENARIO_SCHEMA_COLUMN_LIMIT = 6
_SCENARIO_MAX_OUTPUT_TOKENS = 900
_SCENARIO_REPAIR_MAX_OUTPUT_TOKENS = 1200
_GENERIC_SCENARIO_TITLE_RE = re.compile(r"^(?:ai\s*)?scenario\s*\d+$", re.IGNORECASE)
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
            system_prompt=(
                "You design high-value database test scenarios for API-linked test data generation. "
                "Return only structured scenario output."
            ),
            user_prompt=user_prompt,
            max_output_tokens=_SCENARIO_MAX_OUTPUT_TOKENS,
        )
        scenarios = self._parse_scenarios(user_prompt, response)
        diversity_issues = (
            _scenario_diversity_issues(scenarios, requirement_text=requirement_text) if len(interface_infos) > 1 else []
        )
        content_issues = _scenario_content_issues(scenarios)
        issues = [
            *_multi_interface_issues(interface_infos, scenarios),
            *diversity_issues,
            *content_issues,
        ]
        if not issues:
            return scenarios

        retry_prompt = "\n".join(
            [
                user_prompt,
                "",
                "The previous output did not satisfy these multi-interface constraints. Regenerate the full scenario set:",
                *[f"- {issue}" for issue in issues],
                "",
                "Return compact lines when possible. Use exactly this shape:",
                "SCENARIO|scenario name|scenario description",
                "TABLE|table_name|data requirement",
                "RELATION|target_table|target_field|source_table|source_field|same_value|why",
                "If compact lines are impossible, return a JSON array only.",
                "Do not include markdown fences or any explanation.",
            ]
        )
        retry_response = self._ai_chat_client.complete(
            system_prompt=(
                "You design high-value database test scenarios for API-linked test data generation. "
                "Return only structured scenario output."
            ),
            user_prompt=retry_prompt,
            max_output_tokens=_SCENARIO_MAX_OUTPUT_TOKENS,
        )
        repaired_scenarios = self._parse_scenarios(retry_prompt, retry_response)
        retry_diversity_issues = (
            _scenario_diversity_issues(repaired_scenarios, requirement_text=requirement_text)
            if len(interface_infos) > 1
            else []
        )
        retry_content_issues = _scenario_content_issues(repaired_scenarios)
        hard_retry_issues = [
            *_multi_interface_issues(interface_infos, repaired_scenarios),
            *retry_content_issues,
        ]
        if hard_retry_issues:
            raise ValueError(
                "AI scenario generation did not satisfy multi-interface coverage: "
                + "; ".join(hard_retry_issues)
            )
        # Diversity issues are soft constraints: force one retry, then continue with best-effort result.
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
            "Generate high-value P0 database test scenarios from the business requirement, API SQL chain, schema summary, and fixed-value constraints.",
            "",
            "Business Requirement:",
            requirement_text,
            "",
            "API SQL Chain:",
            _format_interface_sql_info(interface_infos),
            "",
            "Table Schemas:",
            _format_table_schemas(schemas),
            "",
            "Fixed Values:",
            format_fixed_value_lines(fixed_values) or "[none]",
            "",
            "Dependent Fixed Values:",
            format_fixed_value_lines(dependent_fixed_values) or "[none]",
        ]
        if is_multi_interface:
            sections.extend(
                [
                    "",
                    "Multi-Interface Requirements:",
                    f"1. There are {len(interface_infos)} interfaces. Design shared end-to-end scenarios instead of separate duplicated baselines.",
                    "2. Use as few scenarios as possible while keeping customer, model, date, ticket, and similar key fields aligned across interfaces.",
                    "3. The scenario set must cover every input interface, and at least one scenario must cover two or more interfaces together.",
                    "4. CRITICAL: Each scenario MUST include at least the main business table for each interface it covers. Do NOT create scenarios with only shared/lookup tables.",
                    "5. CRITICAL: When a scenario description says an interface 'returns data' or similar, the scenario MUST include that interface's main business table in its tables list.",
                    "6. CRITICAL: When a scenario description says an interface 'returns empty' or 'no data', the scenario should still include other interfaces' tables that DO return data.",
                    "7. Prefer scenarios that connect shared tables, upstream/downstream tables, and reusable cross-table relations.",
                    "8. Scenarios must be mutually distinguishable. Do not output two scenarios with nearly identical business objective, key filter pattern, and expected interface outcomes.",
                    "9. If one scenario is a normal hit baseline, the remaining scenarios must prioritize different branches such as boundary/edge, competing-order candidates, or non-hit/no-data behavior.",
                ]
            )
        sections.extend(
            [
                "",
                "Output Requirements:",
                f"1. Prefer compact line format and output at most {self._max_scenarios} scenarios.",
                "2. Compact line format:",
                "   SCENARIO|scenario name|scenario description",
                "   TABLE|table_name|data requirement",
                "   TABLE|table_name|data requirement",
                "   RELATION|target_table|target_field|source_table|source_field|same_value|why",
                "   Blank line before the next scenario.",
                "3. If compact lines are impossible, return a JSON array only.",
                "4. Prioritize core chains, edge conditions, dictionary constraints, and cross-table consistency.",
                "5. Do not output explanations outside the compact lines or JSON array.",
                "6. CRITICAL: The tables list in each scenario MUST match the scenario description. If description mentions an interface returning data, include that interface's table.",
                "7. Scenario names must reflect the concrete test point. Do not use generic names like 'AI scenario 1'.",
                "8. The scenario set must include boundary-condition coverage, such as empty/no-data branches, threshold edges, date/time window edges, ordering/recency edges, pagination limits, or optional-field missing cases, chosen according to the given requirement and SQL semantics.",
                "9. Scenario logic must be derived from requirement semantics, not by blindly copying SQL literal filters.",
                "10. For each core business function, cover three data branches when applicable: qualifying data, boundary-edge data, and non-qualifying/no-hit data.",
                "11. Scenario de-duplication rule: each scenario must differ in at least one of the following dimensions: branch type, key condition pattern, temporal candidate set, or expected per-interface hit/no-hit outcome.",
                "12. For recency/order-by-time semantics, include a scenario with multiple temporal candidates and explicitly indicate which candidate is expected to win and which is expected to lose.",
            ]
        )
        if is_multi_interface:
            sections.append(
                "13. Do not split each interface into an isolated baseline scenario when a joint scenario can cover them together."
            )
        return "\n".join(sections)

    def _parse_scenarios(self, prompt: str, response: str) -> list[ScenarioDraft]:
        compact_scenarios = _parse_compact_scenarios(response, self._max_scenarios, prompt)
        if compact_scenarios:
            return compact_scenarios
        payload = self._load_payload(prompt, response)
        if not isinstance(payload, list):
            raise ValueError("AI scenario response must be a JSON array.")

        scenarios: list[ScenarioDraft] = []
        for index, item in enumerate(payload[: self._max_scenarios], start=1):
            if not isinstance(item, dict):
                continue
            raw_title = str(item.get("name") or "")
            description = str(item.get("description") or raw_title or f"Scenario {index}")
            title = _resolve_scenario_title(
                raw_title=raw_title,
                description=description,
                requirement_text=prompt,
                index=index,
            )
            raw_table_requirements = item.get("tableRequirements") or {}
            if not isinstance(raw_table_requirements, dict):
                raw_table_requirements = {}
            table_requirements = {
                str(table_name): str(requirement)
                for table_name, requirement in raw_table_requirements.items()
            }
            relation_rules = _normalize_relation_rules_payload(item.get("relationRules") or item.get("relations"))
            scenario_tables = list(
                dict.fromkeys(
                    [
                        *table_requirements,
                        *[rule.target_table for rule in relation_rules],
                        *[rule.source_table for rule in relation_rules],
                    ]
                )
            )
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
                    tables=scenario_tables,
                    table_requirements=table_requirements,
                    relation_rules=relation_rules,
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
                        "The repaired content is still not valid JSON.\n"
                        f"Parse error: {repaired_exc}\n"
                        "If the tail is truncated, remove the incomplete tail and keep only complete scenario objects."
                    ),
                )
                return parse_json_payload(repaired_again)

    def _repair_payload(self, prompt: str, response: str, error_detail: str) -> str:
        return self._ai_chat_client.complete(
            system_prompt="You repair malformed JSON. Return only a valid JSON array.",
            user_prompt=(
                "The following model output should describe test scenarios, but it is not valid JSON.\n"
                "Keep the original meaning, return only a repaired JSON array, and do not add explanations.\n"
                "Escape embedded newlines inside JSON strings as \\n.\n"
                "If the tail of the content is truncated, drop the incomplete tail and keep only complete scenario objects.\n"
                f"Current parse error: {error_detail}\n\n"
                f"Original prompt:\n{prompt}\n\n"
                f"Malformed output:\n{response}"
            ),
            max_output_tokens=_SCENARIO_REPAIR_MAX_OUTPUT_TOKENS,
        )


def _format_interface_sql_info(interface_infos: list[InterfaceInfo]) -> str:
    parts: list[str] = []
    for interface in interface_infos:
        parts.append(f"- Interface: {interface.name} {interface.path}")
        if interface.sql_infos:
            parts.append(f"  MAIN BUSINESS TABLES for this interface:")
            for sql_info in interface.sql_infos:
                conditions = "; ".join(sql_info.conditions) if sql_info.conditions else "[no conditions]"
                parts.append(f"  - {sql_info.table_name} (Conditions: {conditions})")
        else:
            parts.append(f"  [No SQL tables found for this interface]")
    return "\n".join(parts)


def _format_table_schemas(schemas: dict[str, TableSchema]) -> str:
    parts: list[str] = []
    for table_name, schema in schemas.items():
        primary_keys = ", ".join(schema.primary_keys) or "[none]"
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
            summary = f"{summary}, ...{omitted_count} more"
        parts.append(f"Table: {table_name}; PK: {primary_keys}; Key Columns: {summary}")
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
        return ["No scenarios were generated."]

    interface_tables = {
        _interface_label(interface): {
            sql_info.table_name
            for sql_info in interface.sql_infos
            if sql_info.table_name
        }
        for interface in interface_infos
    }
    required_tables = _required_tables_by_interface(interface_tables)
    covered_interfaces: set[str] = set()
    has_joint_scenario = False

    for scenario in scenarios:
        scenario_tables = set(scenario.tables) or set(scenario.table_requirements)
        covered_by_scenario = {
            label
            for label, tables in required_tables.items()
            if tables and scenario_tables.intersection(tables)
        }
        covered_interfaces.update(covered_by_scenario)
        if len(covered_by_scenario) > 1:
            has_joint_scenario = True

    issues: list[str] = []
    missing_interfaces = [label for label in interface_tables if label not in covered_interfaces]
    if missing_interfaces:
        issues.append(f"Missing interface coverage: {', '.join(missing_interfaces)}")
    if not has_joint_scenario:
        issues.append("No scenario covers two or more interfaces together.")
    return issues


def _required_tables_by_interface(
    interface_tables: dict[str, set[str]],
) -> dict[str, set[str]]:
    required_tables: dict[str, set[str]] = {}
    for label, tables in interface_tables.items():
        other_tables = set().union(
            *(other for other_label, other in interface_tables.items() if other_label != label)
        )
        distinguishing_tables = tables - other_tables
        required_tables[label] = distinguishing_tables or set(tables)
    return required_tables

def _interface_label(interface: InterfaceInfo) -> str:
    return interface.name or interface.path or "[unknown]"


def _scenario_diversity_issues(scenarios: list[ScenarioDraft], requirement_text: str = "") -> list[str]:
    if len(scenarios) < 2:
        if _requires_branch_pair(requirement_text):
            return [
                "Scenario set is too small for this requirement. Provide at least two orthogonal scenarios (for example baseline and boundary/recency or non-hit)."
            ]
        return []

    issues: list[str] = []
    branch_types = {_scenario_branch_type(scenario) for scenario in scenarios}
    branch_types.discard("unknown")
    if len(branch_types) < 2:
        issues.append(
            "Scenario branches are not diverse. Include at least two distinct branches such as qualifying, boundary-edge, or non-hit/no-data."
        )

    signatures = [_scenario_similarity_signature(scenario) for scenario in scenarios]
    for left_index in range(len(signatures)):
        for right_index in range(left_index + 1, len(signatures)):
            table_similarity = _jaccard_similarity(signatures[left_index][0], signatures[right_index][0])
            token_similarity = _jaccard_similarity(signatures[left_index][1], signatures[right_index][1])
            if table_similarity >= 0.8 and token_similarity >= 0.82:
                issues.append(
                    f"Scenario {left_index + 1} and scenario {right_index + 1} are near-duplicates in tables and data characteristics; make them orthogonal."
                )
                return issues
    return issues


def _scenario_content_issues(scenarios: list[ScenarioDraft]) -> list[str]:
    issues: list[str] = []
    for index, scenario in enumerate(scenarios, start=1):
        if not scenario.table_requirements:
            issues.append(
                f"Scenario {index} has empty tableRequirements. Each scenario must provide concrete per-table data requirements."
            )
    return issues


def _requires_branch_pair(requirement_text: str) -> bool:
    text = str(requirement_text or "").lower()
    tokens = (
        "latest",
        "recent",
        "recency",
        "order by",
        "boundary",
        "edge",
        "threshold",
        "最新",
        "最近",
        "排序",
        "边界",
        "临界",
        "<=",
        ">=",
    )
    return any(token in text for token in tokens)


def _scenario_branch_type(scenario: ScenarioDraft) -> str:
    text = " ".join(
        [
            str(scenario.title or ""),
            str(scenario.objective or ""),
            " ".join(str(value) for value in scenario.table_requirements.values()),
        ]
    ).lower()
    no_hit_tokens = (
        "no data",
        "empty",
        "no-hit",
        "non-hit",
        "not hit",
        "non-qualifying",
        "无数据",
        "空结果",
        "不命中",
        "未命中",
    )
    boundary_tokens = (
        "boundary",
        "edge",
        "latest",
        "recent",
        "order by",
        "recency",
        "candidate",
        "competing",
        "threshold",
        "边界",
        "临界",
        "最新",
        "最近",
        "排序",
        "候选",
    )
    qualifying_tokens = (
        "qualifying",
        "baseline",
        "return data",
        "returns data",
        "hit data",
        "core path",
        "命中",
        "有数据",
        "主路径",
        "正常返回",
    )

    if any(token in text for token in no_hit_tokens):
        return "non_hit"
    if any(token in text for token in boundary_tokens):
        return "boundary"
    if any(token in text for token in qualifying_tokens):
        return "qualifying"
    return "unknown"


def _scenario_similarity_signature(scenario: ScenarioDraft) -> tuple[set[str], set[str]]:
    tables = set(scenario.tables) or set(scenario.table_requirements)
    text = " ".join(
        [
            str(scenario.objective or ""),
            " ".join(str(value) for value in scenario.table_requirements.values()),
        ]
    ).lower()
    tokens = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text))
    stop_tokens = {
        "and",
        "or",
        "the",
        "a",
        "an",
        "with",
        "for",
        "to",
        "of",
        "is",
        "are",
        "in",
        "on",
        "at",
        "接口",
        "场景",
        "数据",
        "table",
        "tables",
    }
    return tables, {token for token in tokens if token and token not in stop_tokens}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _parse_compact_scenarios(response: str, max_scenarios: int, prompt: str = "") -> list[ScenarioDraft]:
    lines = _compact_lines(response)
    if not any(line.startswith("SCENARIO|") for line in lines):
        return []

    scenarios: list[ScenarioDraft] = []
    current_name = ""
    current_description = ""
    current_requirements: dict[str, str] = {}
    current_relations: list[RelationRule] = []

    def flush_current() -> None:
        nonlocal current_name, current_description, current_requirements, current_relations
        if not current_name:
            return
        index = len(scenarios) + 1
        scenario_tables = list(
            dict.fromkeys(
                [
                    *current_requirements,
                    *[rule.target_table for rule in current_relations],
                    *[rule.source_table for rule in current_relations],
                ]
            )
        )
        # Apply title resolution logic to use meaningful description instead of generic titles
        title = _resolve_scenario_title(
            raw_title=current_name,
            description=current_description or current_name,
            requirement_text=prompt,
            index=index,
        )
        scenarios.append(
            ScenarioDraft(
                id=f"ai:{_slugify(title)}:{index}",
                title=title,
                api_name="multi_api",
                api_path="",
                objective=current_description or current_name,
                request_inputs={},
                fixed_conditions=[],
                assertions=[],
                tables=scenario_tables,
                table_requirements=dict(current_requirements),
                relation_rules=list(current_relations),
                generation_source="ai",
            )
        )
        current_name = ""
        current_description = ""
        current_requirements = {}
        current_relations = []

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
            continue
        if line.startswith("RELATION|") and current_name:
            rule = _parse_compact_relation_rule(line)
            if rule is not None:
                current_relations.append(rule)

    flush_current()
    return scenarios[:max_scenarios]


def _parse_compact_relation_rule(line: str) -> RelationRule | None:
    parts = _split_compact_fields(line, 7)
    if len(parts) < 5:
        return None
    target_table = parts[1] if len(parts) > 1 else ""
    target_field = parts[2] if len(parts) > 2 else ""
    source_table = parts[3] if len(parts) > 3 else ""
    source_field = parts[4] if len(parts) > 4 else ""
    relation_type = parts[5] if len(parts) > 5 and parts[5] else "same_value"
    rationale = parts[6] if len(parts) > 6 else ""
    if not (target_table and target_field and source_table and source_field):
        return None
    return RelationRule(
        target_table=target_table,
        target_field=target_field,
        source_table=source_table,
        source_field=source_field,
        relation_type=relation_type or "same_value",
        rationale=rationale,
    )


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


def _is_generic_scenario_title(title: str) -> bool:
    normalized = " ".join(str(title or "").split())
    if not normalized:
        return True
    return bool(_GENERIC_SCENARIO_TITLE_RE.fullmatch(normalized))


def _extract_requirement_headline(requirement_text: str) -> str:
    lines = str(requirement_text or "").splitlines()
    capture = False
    candidates: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped and capture and candidates:
            break
        if stripped == "Business Requirement:":
            capture = True
            continue
        if capture:
            candidates.append(stripped)
    if not candidates:
        candidates = [line.strip() for line in lines]
    for raw_line in candidates:
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        line = re.sub(r"^(?:test\s+requirement|requirement)\s*[:?-]?\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^????\s*[:?-]?\s*", "", line)
        if line:
            return line[:80].rstrip(" .;,-")
    return ""


def _description_to_title(description: str) -> str:
    normalized = " ".join(str(description or "").split())
    if not normalized:
        return ""
    for separator in (" - ", "; ", ". ", ", "):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0].strip()
            break
    return normalized[:80].rstrip(" .;,-")


def _resolve_scenario_title(raw_title: str, description: str, requirement_text: str, index: int) -> str:
    normalized_title = " ".join(str(raw_title or "").split())
    if normalized_title and not _is_generic_scenario_title(normalized_title):
        return normalized_title

    description_title = _description_to_title(description)
    requirement_title = _extract_requirement_headline(requirement_text)

    if requirement_title and description_title:
        description_lower = description_title.lower()
        requirement_lower = requirement_title.lower()
        if description_lower not in requirement_lower and requirement_lower not in description_lower:
            return f"{requirement_title} - {description_title}"[:120].rstrip(" .;,-")
    if description_title:
        return description_title
    if requirement_title:
        return requirement_title
    return f"Scenario {index}"


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



def _normalize_relation_rules_payload(raw_data: object) -> list[RelationRule]:
    if not isinstance(raw_data, list):
        return []
    rules: list[RelationRule] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        target_table = str(item.get("target_table") or item.get("targetTable") or "").strip()
        target_field = str(item.get("target_field") or item.get("targetField") or "").strip()
        source_table = str(item.get("source_table") or item.get("sourceTable") or "").strip()
        source_field = str(item.get("source_field") or item.get("sourceField") or "").strip()
        if not (target_table and target_field and source_table and source_field):
            continue
        rules.append(
            RelationRule(
                target_table=target_table,
                target_field=target_field,
                source_table=source_table,
                source_field=source_field,
                relation_type=str(item.get("relation_type") or item.get("relationType") or "same_value").strip() or "same_value",
                rationale=str(item.get("rationale") or item.get("reason") or "").strip(),
                evidence=item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
            )
        )
    return rules
