from __future__ import annotations

from dataclasses import replace
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
from api_data_gen.services.relation_rule_derivation_service import RelationRuleDerivationService

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
        ai_cache_service=None,
        relation_rule_derivation_service: RelationRuleDerivationService | None = None,
    ):
        self._settings = settings
        self._trace_repository = trace_repository
        self._interface_trace_service = interface_trace_service
        self._schema_service = schema_service
        self._sample_repository = sample_repository
        self._dict_rule_resolver = dict_rule_resolver
        self._requirement_parser = requirement_parser
        self._ai_scenario_service = ai_scenario_service
        self._ai_cache_service = ai_cache_service
        self._relation_rule_derivation_service = relation_rule_derivation_service or RelationRuleDerivationService()

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

        scenarios = self._build_scenarios(
            requirement_text=requirement_text,
            interfaces=interfaces,
            interface_infos=interface_infos,
            schemas=schemas,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
            use_ai_scenarios=use_ai_scenarios,
        )
        scenarios = self._attach_relation_rules(scenarios, table_plans)

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
        if use_ai_scenarios:
            cached_scenarios = None
            if self._ai_cache_service is not None:
                cached_scenarios = self._ai_cache_service.load_scenarios(
                    requirement_text=requirement_text,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                )
            if cached_scenarios:
                return cached_scenarios
            if self._ai_scenario_service is None:
                raise ValueError("AI scenario generation requested but AI scenario service is unavailable.")
            scenarios = self._ai_scenario_service.generate(
                requirement_text,
                interface_infos,
                schemas,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
            )
            if not scenarios:
                raise ValueError("AI scenario generation returned no scenarios.")
            if self._ai_cache_service is not None:
                self._ai_cache_service.save_scenarios(
                    requirement_text=requirement_text,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                    scenarios=scenarios,
                )
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
                title=f"{target.name} baseline replay",
                api_name=target.name,
                api_path=target.path,
                objective="Replay the latest interface sample and verify the core SQL filters and business-table chain.",
                request_inputs=request_inputs,
                fixed_conditions=fixed_conditions,
                assertions=_build_baseline_assertions(tables, fixed_conditions),
                tables=tables,
                table_requirements=_build_local_table_requirements(
                    tables,
                    "Replay the latest interface sample and satisfy the core SQL filters on the main path tables.",
                ),
            )
        ]

        if "pageSize" in request_inputs or "pageNum" in request_inputs:
            scenarios.append(
                ScenarioDraft(
                    id=f"{target.name}:pagination",
                    title=f"{target.name} pagination stability",
                    api_name=target.name,
                    api_path=target.path,
                    objective="Verify pagination parameter changes without changing the business filters.",
                    request_inputs={key: request_inputs[key] for key in request_inputs if key in {"pageSize", "pageNum"}},
                    fixed_conditions=fixed_conditions,
                    assertions=[
                        "Changing pageSize or pageNum must not change business filters such as cust_id or model_key.",
                        "The business tables hit before and after pagination changes should stay consistent.",
                    ],
                    tables=tables,
                    table_requirements=_build_local_table_requirements(
                        tables,
                        "Keep the business filters unchanged and ensure the linked tables can still be hit consistently across pagination changes.",
                    ),
                )
            )

        dict_columns = _collect_interface_dict_columns(tables, schemas, self._dict_rule_resolver)
        if dict_columns:
            scenarios.append(
                ScenarioDraft(
                    id=f"{target.name}:dictionary",
                    title=f"{target.name} dictionary consistency",
                    api_name=target.name,
                    api_path=target.path,
                    objective="Verify coded fields stay within the allowed dictionary values.",
                    request_inputs=request_inputs,
                    fixed_conditions=fixed_conditions,
                    assertions=[
                        f"{column_name} must use one of: {', '.join(values)}"
                        for column_name, values in dict_columns.items()
                    ],
                    tables=tables,
                    table_requirements=_build_local_table_requirements(
                        tables,
                        "Dictionary-backed fields must stay within the allowed value set while preserving cross-table consistency.",
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
                        rationale=f"Derived from SQL filter: {'; '.join(item['raw'] for item in condition_matches)}",
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
                        rationale="Primary keys should be generated uniquely when rendering inserts.",
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
                        rationale="Resolved from imported or system dictionary mappings.",
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
                        rationale="Observed from sampled business rows.",
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
                        rationale="Non-null column with no sample or dictionary value available.",
                    )
                )
                continue

            column_plans.append(
                ColumnPlan(
                    column_name=column.name,
                    source="optional",
                    required=False,
                    suggested_values=[],
                    rationale="Nullable column with no fixed source in the draft.",
                )
            )

        return TableDataPlan(
            table_name=table_name,
            primary_keys=schema.primary_keys,
            fixed_conditions=conditions,
            row_hint=max(1, min(sample_limit, len(sample_rows) or 1)),
            column_plans=column_plans,
        )

    def _attach_relation_rules(
        self,
        scenarios: list[ScenarioDraft],
        table_plans: list[TableDataPlan],
    ) -> list[ScenarioDraft]:
        if self._relation_rule_derivation_service is None:
            return scenarios
        enriched: list[ScenarioDraft] = []
        for scenario in scenarios:
            derived_rules = self._relation_rule_derivation_service.derive(scenario, table_plans)
            merged_rules = _merge_relation_rules(scenario.relation_rules, derived_rules)
            enriched.append(
                replace(
                    scenario,
                    relation_rules=merged_rules,
                    tables=_normalize_scenario_tables(scenario, merged_rules),
                )
            )
        return enriched


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


def _normalize_scenario_tables(
    scenario: ScenarioDraft,
    relation_rules,
) -> list[str]:
    ordered = list(dict.fromkeys([*scenario.tables, *scenario.table_requirements.keys()]))
    for rule in relation_rules:
        if rule.target_table and rule.target_table not in ordered:
            ordered.append(rule.target_table)
        if rule.source_table and rule.source_table not in ordered:
            ordered.append(rule.source_table)
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
        assertions.append(f"Business chain should hit tables: {', '.join(tables)}")
    if fixed_conditions:
        assertions.append(f"Core filter conditions should stay aligned: {'; '.join(fixed_conditions)}")
    assertions.append("At least one business table should have sample rows available for replay.")
    return assertions


def _build_local_table_requirements(tables: list[str], requirement: str) -> dict[str, str]:
    return {table_name: requirement for table_name in tables}


def _merge_relation_rules(existing_rules, derived_rules):
    ordered = {}
    for rule in [*existing_rules, *derived_rules]:
        key = (
            rule.target_table,
            rule.target_field,
            rule.source_table,
            rule.source_field,
            rule.relation_type,
        )
        ordered.setdefault(key, rule)
    return list(ordered.values())


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
