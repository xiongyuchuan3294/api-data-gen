from __future__ import annotations

import json
import re

from api_data_gen.config import Settings
from api_data_gen.domain.models import (
    ColumnPlan,
    InterfaceInfo,
    InterfaceTarget,
    PlanningDraft,
    ScenarioDraft,
    TableDataPlan,
    TableSchema,
)
from api_data_gen.services.requirement_parser import RequirementParser

_CONDITION_RE = re.compile(r"`?([A-Za-z0-9_]+)`?\s*(=|<=|>=|<|>)\s*'{1,2}([^']*)'{1,2}")


class PlanningService:
    def __init__(
        self,
        settings: Settings,
        trace_repository,
        interface_trace_service,
        schema_service,
        sample_repository,
        dict_rule_resolver,
        requirement_parser: RequirementParser,
        ai_scenario_service=None,
    ):
        self._settings = settings
        self._trace_repository = trace_repository
        self._interface_trace_service = interface_trace_service
        self._schema_service = schema_service
        self._sample_repository = sample_repository
        self._dict_rule_resolver = dict_rule_resolver
        self._requirement_parser = requirement_parser
        self._ai_scenario_service = ai_scenario_service

    def build_draft(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        use_ai_scenarios: bool = False,
    ) -> PlanningDraft:
        requirement = self._requirement_parser.parse(requirement_text)
        interface_infos = [self._interface_trace_service.get_table_info(item.name, item.path) for item in interfaces]
        schemas = self._schema_service.get_all_table_schemas(interface_infos)
        table_samples = {table_name: self._sample_repository.sample_rows(table_name, sample_limit) for table_name in schemas}

        scenarios = self._build_scenarios(
            requirement_text=requirement_text,
            interfaces=interfaces,
            interface_infos=interface_infos,
            schemas=schemas,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
            use_ai_scenarios=use_ai_scenarios,
        )

        table_plans = [
            self._build_table_plan(
                table_name=table_name,
                schema=schema,
                conditions=_collect_table_conditions(interface_infos, table_name),
                sample_rows=table_samples[table_name],
                sample_limit=sample_limit,
            )
            for table_name, schema in schemas.items()
        ]

        return PlanningDraft(
            requirement=requirement,
            scenarios=scenarios,
            table_plans=table_plans,
        )

    def _build_scenarios(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        use_ai_scenarios: bool,
    ) -> list[ScenarioDraft]:
        if use_ai_scenarios and self._ai_scenario_service is not None:
            scenarios = self._ai_scenario_service.generate(
                requirement_text,
                interface_infos,
                schemas,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
            )
            if not scenarios:
                raise ValueError("AI scenario generation returned no scenarios.")
            return scenarios

        scenarios: list[ScenarioDraft] = []
        for target, interface_info in zip(interfaces, interface_infos):
            trace_request = self._trace_repository.find_latest_request(self._build_url_prefix(target.path))
            request_inputs = _extract_request_inputs(trace_request)
            scenarios.extend(
                self._build_interface_scenarios(
                    target=target,
                    interface_info=interface_info,
                    request_inputs=request_inputs,
                    schemas=schemas,
                )
            )
        return scenarios

    def _build_url_prefix(self, api_path: str) -> str:
        return f"{self._settings.system_base_url}{api_path}"

    def _build_interface_scenarios(
        self,
        target: InterfaceTarget,
        interface_info: InterfaceInfo,
        request_inputs: dict[str, str],
        schemas: dict[str, TableSchema],
    ) -> list[ScenarioDraft]:
        tables = [sql_info.table_name for sql_info in interface_info.sql_infos]
        fixed_conditions = _collect_interface_conditions(interface_info)
        scenarios = [
            ScenarioDraft(
                id=f"{target.name}:baseline",
                title=f"{target.name} 基线回放",
                api_name=target.name,
                api_path=target.path,
                objective="回放最新接口样例，验证核心 SQL 过滤条件与业务表联动。",
                request_inputs=request_inputs,
                fixed_conditions=fixed_conditions,
                assertions=_build_baseline_assertions(tables, fixed_conditions),
                tables=tables,
                table_requirements=_build_local_table_requirements(
                    tables,
                    "回放最新接口样例，满足核心 SQL 过滤条件与主链路表关联。",
                ),
            )
        ]

        if "pageSize" in request_inputs or "pageNum" in request_inputs:
            scenarios.append(
                ScenarioDraft(
                    id=f"{target.name}:pagination",
                    title=f"{target.name} 分页稳定性",
                    api_name=target.name,
                    api_path=target.path,
                    objective="在不改变业务过滤条件的前提下验证分页参数变化。",
                    request_inputs={key: request_inputs[key] for key in request_inputs if key in {"pageSize", "pageNum"}},
                    fixed_conditions=fixed_conditions,
                    assertions=[
                        "修改 pageSize 或 pageNum 时，cust_id/model_key 等业务过滤条件保持不变。",
                        "分页前后命中的业务表不应变化。",
                    ],
                    tables=tables,
                    table_requirements=_build_local_table_requirements(
                        tables,
                        "保持业务过滤条件不变，并确保分页前后链路表数据可稳定命中。",
                    ),
                )
            )

        dict_columns = _collect_interface_dict_columns(tables, schemas, self._dict_rule_resolver)
        if dict_columns:
            scenarios.append(
                ScenarioDraft(
                    id=f"{target.name}:dictionary",
                    title=f"{target.name} 字典一致性",
                    api_name=target.name,
                    api_path=target.path,
                    objective="验证码值字段只落在允许的字典候选集合中。",
                    request_inputs=request_inputs,
                    fixed_conditions=fixed_conditions,
                    assertions=[
                        f"{column_name} 必须使用以下值之一: {', '.join(values)}"
                        for column_name, values in dict_columns.items()
                    ],
                    tables=tables,
                    table_requirements=_build_local_table_requirements(
                        tables,
                        "字典字段应落在允许的码值集合中，同时保持跨表条件一致。",
                    ),
                )
            )

        return scenarios

    def _build_table_plan(
        self,
        table_name: str,
        schema: TableSchema,
        conditions: list[str],
        sample_rows: list[dict[str, str]],
        sample_limit: int,
    ) -> TableDataPlan:
        parsed_conditions = _parse_conditions(conditions)
        sample_values = _collect_sample_values(sample_rows)
        column_plans: list[ColumnPlan] = []

        for column in schema.columns:
            dict_values = self._dict_rule_resolver.resolve_code_values(column.name, column.comment)
            condition_matches = parsed_conditions.get(column.name, [])
            values_from_condition = [item["value"] for item in condition_matches]
            if values_from_condition:
                column_plans.append(
                    ColumnPlan(
                        column_name=column.name,
                        source="condition",
                        required=True,
                        suggested_values=_deduplicate(values_from_condition),
                        rationale=f"来自SQL过滤器: {'; '.join(item['raw'] for item in condition_matches)}",
                    )
                )
                continue

            if column.is_primary_key:
                column_plans.append(
                    ColumnPlan(
                        column_name=column.name,
                        source="generated",
                        required=True,
                        suggested_values=[],
                        rationale="主键应在插入渲染时唯一生成。",
                    )
                )
                continue

            if dict_values:
                column_plans.append(
                    ColumnPlan(
                        column_name=column.name,
                        source="dictionary",
                        required=not column.nullable,
                        suggested_values=dict_values[:sample_limit],
                        rationale="从导入/系统字典映射解析。",
                    )
                )
                continue

            if column.name in sample_values:
                column_plans.append(
                    ColumnPlan(
                        column_name=column.name,
                        source="sample",
                        required=not column.nullable,
                        suggested_values=sample_values[column.name][:sample_limit],
                        rationale="从采样的业务行中观察。",
                    )
                )
                continue

            if not column.nullable:
                column_plans.append(
                    ColumnPlan(
                        column_name=column.name,
                        source="default",
                        required=True,
                        suggested_values=[_default_value_for_type(column.type)],
                        rationale="非空列且没有样本或字典值。",
                    )
                )
                continue

            column_plans.append(
                ColumnPlan(
                    column_name=column.name,
                    source="optional",
                    required=False,
                    suggested_values=[],
                    rationale="可空列且在Phase 2草稿中没有固定来源。",
                )
            )

        return TableDataPlan(
            table_name=table_name,
            primary_keys=schema.primary_keys,
            fixed_conditions=conditions,
            row_hint=max(1, min(sample_limit, len(sample_rows) or 1)),
            column_plans=column_plans,
        )


def _extract_request_inputs(trace_request) -> dict[str, str]:
    if trace_request is None:
        return {}
    values: dict[str, str] = {}
    for payload in (trace_request.query_params, trace_request.request_body):
        values.update(_parse_json_object(payload))
    return values


def _parse_json_object(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): _stringify(value) for key, value in parsed.items()}


def _stringify(value: object) -> str:
    if value is None:
        return "[NULL]"
    return str(value)


def _collect_interface_conditions(interface_info: InterfaceInfo) -> list[str]:
    ordered: list[str] = []
    for sql_info in interface_info.sql_infos:
        for condition in sql_info.conditions:
            if condition not in ordered:
                ordered.append(condition)
    return ordered


def _collect_table_conditions(interface_infos: list[InterfaceInfo], table_name: str) -> list[str]:
    ordered: list[str] = []
    for interface_info in interface_infos:
        for sql_info in interface_info.sql_infos:
            if sql_info.table_name != table_name:
                continue
            for condition in sql_info.conditions:
                if condition not in ordered:
                    ordered.append(condition)
    return ordered


def _collect_interface_dict_columns(
    tables: list[str],
    schemas: dict[str, TableSchema],
    dict_rule_resolver,
) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for table_name in tables:
        schema = schemas.get(table_name)
        if schema is None:
            continue
        for column in schema.columns:
            dict_values = dict_rule_resolver.resolve_code_values(column.name, column.comment)
            if dict_values:
                values[column.name] = dict_values
    return values


def _build_baseline_assertions(tables: list[str], fixed_conditions: list[str]) -> list[str]:
    assertions: list[str] = []
    if tables:
        assertions.append(f"业务链路应命中表: {', '.join(tables)}")
    if fixed_conditions:
        assertions.append(f"核心过滤条件应保持一致: {'; '.join(fixed_conditions)}")
    assertions.append("至少一张业务表应能采到用于回放的样本数据。")
    return assertions


def _build_local_table_requirements(tables: list[str], requirement: str) -> dict[str, str]:
    return {table_name: requirement for table_name in tables}


def _parse_conditions(conditions: list[str]) -> dict[str, list[dict[str, str]]]:
    results: dict[str, list[dict[str, str]]] = {}
    for condition in conditions:
        cleaned = condition.strip().strip("()")
        match = _CONDITION_RE.search(cleaned)
        if match is None:
            continue
        column_name = match.group(1)
        operator = match.group(2)
        value = match.group(3)
        results.setdefault(column_name, []).append(
            {
                "operator": operator,
                "value": value,
                "raw": cleaned,
            }
        )
    return results


def _collect_sample_values(sample_rows: list[dict[str, str]]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for row in sample_rows:
        for key, value in row.items():
            if value in {"[NULL]", "[DEFAULT]"}:
                continue
            values.setdefault(key, [])
            if value not in values[key]:
                values[key].append(value)
    return values


def _default_value_for_type(data_type: str) -> str:
    lowered = data_type.lower()
    if "int" in lowered or "decimal" in lowered or "float" in lowered or "double" in lowered:
        return "0"
    if "date" in lowered or "time" in lowered:
        return "1970-01-01"
    return "[DEFAULT]"


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
