from __future__ import annotations

from api_data_gen.domain.models import RelationRule, ScenarioDraft, TableDataPlan

_CONSISTENT_FIELDS = {
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
}


class RelationRuleDerivationService:
    def derive(
        self,
        scenario: ScenarioDraft,
        table_plans: list[TableDataPlan],
    ) -> list[RelationRule]:
        relevant_plans = _select_relevant_plans(scenario, table_plans)
        if len(relevant_plans) < 2:
            return []

        grouped: dict[str, list[tuple[str, object]]] = {}
        for plan in relevant_plans:
            primary_keys = {name.lower() for name in plan.primary_keys}
            for column_plan in plan.column_plans:
                field_name = column_plan.column_name.strip()
                if not field_name or field_name.lower() in primary_keys:
                    continue
                if not _is_relation_candidate(field_name, column_plan.source):
                    continue
                grouped.setdefault(field_name.lower(), []).append((plan.table_name, column_plan))

        derived: list[RelationRule] = []
        for entries in grouped.values():
            if len({table_name for table_name, _ in entries}) < 2:
                continue
            source_table, source_column_plan = _select_source_entry(entries)
            reason = (
                "shared condition field across scenario tables"
                if any(column_plan.source == "condition" for _, column_plan in entries)
                else "shared business key field across scenario tables"
            )
            for target_table, target_column_plan in entries:
                if target_table == source_table:
                    continue
                derived.append(
                    RelationRule(
                        target_table=target_table,
                        target_field=target_column_plan.column_name,
                        source_table=source_table,
                        source_field=source_column_plan.column_name,
                        relation_type="same_value",
                        rationale=reason,
                        evidence={
                            "derived_by": "relation_rule_derivation",
                            "scenario_id": scenario.id,
                            "field_name": source_column_plan.column_name,
                        },
                    )
                )

        return _deduplicate_rules(derived)


def _select_relevant_plans(
    scenario: ScenarioDraft,
    table_plans: list[TableDataPlan],
) -> list[TableDataPlan]:
    scenario_tables = list(dict.fromkeys([*scenario.tables, *scenario.table_requirements.keys()]))
    if not scenario_tables:
        return list(table_plans)
    return [plan for plan in table_plans if plan.table_name in scenario_tables]


def _is_relation_candidate(field_name: str, source: str) -> bool:
    lowered = field_name.lower()
    if source == "condition":
        return True
    return lowered in _CONSISTENT_FIELDS


def _select_source_entry(entries: list[tuple[str, object]]) -> tuple[str, object]:
    for table_name, column_plan in entries:
        if getattr(column_plan, "source", "") == "condition":
            return table_name, column_plan
    return entries[0]


def _deduplicate_rules(rules: list[RelationRule]) -> list[RelationRule]:
    ordered: dict[tuple[str, str, str, str, str], RelationRule] = {}
    for rule in rules:
        ordered.setdefault(
            (
                rule.target_table,
                rule.target_field,
                rule.source_table,
                rule.source_field,
                rule.relation_type,
            ),
            rule,
        )
    return list(ordered.values())
