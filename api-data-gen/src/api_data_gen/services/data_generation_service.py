from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import re

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    GeneratedRow,
    GeneratedTable,
    GenerationReport,
    InterfaceTarget,
    ScenarioDraft,
    StoredRelationStrategy,
    ScenarioGeneration,
    TableColumn,
    TableDataPlan,
    TableSchema,
    ValidationCheck,
)
from api_data_gen.services.cross_table_validation_service import CrossTableValidationService
from api_data_gen.services.fixed_value_service import parse_fixed_values
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService
from api_data_gen.services.record_validation_service import RecordValidationService
from api_data_gen.services.relation_strategy_alignment_service import RelationStrategyAlignmentService
from api_data_gen.services.relation_strategy_validation_service import RelationStrategyValidationService

DEFAULT_MARKER = "[DEFAULT]"
_UNRESOLVED = object()
_REQUIREMENT_IN_RE = re.compile(r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_REQUIREMENT_EQ_RE = re.compile(
    r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:=|:)\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^,;，；]+)",
    re.IGNORECASE,
)


class DataGenerationService:
    def __init__(
        self,
        planning_service,
        schema_repository,
        insert_render_service,
        sample_repository=None,
        cross_table_validation_service: CrossTableValidationService | None = None,
        relation_strategy_alignment_service: RelationStrategyAlignmentService | None = None,
        relation_strategy_validation_service: RelationStrategyValidationService | None = None,
        local_field_rule_service: LocalFieldRuleService | None = None,
        record_validation_service: RecordValidationService | None = None,
        ai_data_analysis_service=None,
        ai_data_generation_service=None,
        ai_cache_service=None,
        reusable_strategy_service=None,
    ):
        self._planning_service = planning_service
        self._schema_repository = schema_repository
        self._insert_render_service = insert_render_service
        self._sample_repository = sample_repository
        self._cross_table_validation_service = cross_table_validation_service or CrossTableValidationService()
        self._relation_strategy_alignment_service = relation_strategy_alignment_service
        self._relation_strategy_validation_service = relation_strategy_validation_service
        self._local_field_rule_service = local_field_rule_service or LocalFieldRuleService()
        self._record_validation_service = record_validation_service or RecordValidationService()
        self._ai_data_analysis_service = ai_data_analysis_service
        self._ai_data_generation_service = ai_data_generation_service
        self._ai_cache_service = ai_cache_service
        self._reusable_strategy_service = reusable_strategy_service

    def generate(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        generation_tag: str | None = None,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        use_ai_scenarios: bool = False,
        use_ai_data: bool = False,
        use_ai_field_decisions: bool = False,
        imported_field_decisions: dict[str, AiTableGenerationAdvice] | None = None,
    ) -> GenerationReport:
        # Scenario source controls whether row values come from AI or local rules.
        if use_ai_data:
            generation_source = "ai"
        elif use_ai_scenarios or use_ai_field_decisions:
            generation_source = "hybrid"  # Scenarios may come from AI while rows are still generated locally.
        else:
            generation_source = "local"

        normalized_generation_tag = _normalize_generation_tag(generation_tag)
        try:
            draft = self._planning_service.build_draft(
                requirement_text,
                interfaces,
                sample_limit,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
                use_ai_scenarios=use_ai_scenarios,
            )
        except TypeError:
            draft = self._planning_service.build_draft(requirement_text, interfaces, sample_limit)
        fixed_value_map = parse_fixed_values(fixed_values)
        scenarios = draft.scenarios or [
            ScenarioDraft(
                id="default",
                title="default generation",

                api_name="default",
                api_path="",
                objective="default generation",

                tables=[table_plan.table_name for table_plan in draft.table_plans],
                table_requirements={
                    table_plan.table_name: "default generation"

                    for table_plan in draft.table_plans
                },
            )
        ]

        scenario_generations: list[ScenarioGeneration] = []
        generated_tables: list[GeneratedTable] = []
        validation_checks: list[ValidationCheck] = []
        ai_sample_cache: dict[str, list[dict[str, str]]] = {}
        ai_analysis_cache: dict[str, str] = {}
        ai_local_field_cache: dict[str, set[str]] = {}
        prior_field_decisions: dict[str, AiTableGenerationAdvice] = {
            table_name: advice
            for table_name, advice in (imported_field_decisions or {}).items()
        }

        for scenario_index, scenario in enumerate(scenarios, start=1):
            scenario_tag = _scenario_generation_tag(
                normalized_generation_tag,
                scenario,
                scenario_index,
                len(scenarios),
            )
            relevant_plans = _select_table_plans(draft.table_plans, scenario)
            scenario_requirement_overrides = self._derive_scenario_requirement_overrides(
                scenario=scenario,
                relevant_plans=relevant_plans,
            )
            self._persist_reusable_relation_strategies(scenario, relevant_plans)
            scenario_field_decisions = self._decide_ai_field_strategies_for_scenario(
                requirement_text=requirement_text,
                scenario=scenario,
                relevant_plans=relevant_plans,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
                use_ai_field_decisions=use_ai_field_decisions,
                local_field_cache=ai_local_field_cache,
                imported_field_decisions=imported_field_decisions,
                prior_field_decisions=prior_field_decisions,
            )
            scenario_context: dict[str, list[str | None]] = {}
            ai_advice_by_table = self._generate_ai_rows(
                scenario=scenario,
                relevant_plans=relevant_plans,
                sample_limit=sample_limit,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
                use_ai_data=use_ai_data,
                sample_cache=ai_sample_cache,
                analysis_cache=ai_analysis_cache,
                local_field_cache=ai_local_field_cache,
            )
            scenario_tables: list[GeneratedTable] = []
            scenario_checks: list[ValidationCheck] = []

            for table_plan in relevant_plans:
                ai_advice = _merge_ai_advice(
                    scenario_field_decisions.get(
                        table_plan.table_name,
                        AiTableGenerationAdvice(table_name=table_plan.table_name),
                    ),
                    ai_advice_by_table.get(
                        table_plan.table_name,
                        AiTableGenerationAdvice(table_name=table_plan.table_name),
                    ),
                )
                table_result, record_checks = self._generate_table(
                    table_plan=table_plan,
                    scenario=scenario,
                    generation_tag=scenario_tag,
                    fixed_value_map=fixed_value_map,
                    ai_advice=ai_advice,
                    generation_source=generation_source,
                    scenario_context=scenario_context,
                    requirement_overrides=scenario_requirement_overrides.get(table_plan.table_name, {}),
                )
                scenario_tables.append(table_result)
                _update_scenario_context(scenario_context, table_result)
                scenario_checks.extend(record_checks)

            if self._relation_strategy_alignment_service is not None:
                scenario_tables = self._relation_strategy_alignment_service.align(relevant_plans, scenario_tables)

            rendered_tables: list[GeneratedTable] = []
            for generated_table in scenario_tables:
                rendered_table, record_checks = self._render_validated_table(
                    scenario=scenario,
                    generated_table=generated_table,
                )
                rendered_tables.append(rendered_table)
                scenario_checks.extend(record_checks)

            scenario_checks.extend(
                self._cross_table_validation_service.validate(
                    relevant_plans,
                    rendered_tables,
                    relation_rules=scenario.relation_rules,
                )
            )
            if self._relation_strategy_validation_service is not None:
                scenario_checks.extend(self._relation_strategy_validation_service.validate(relevant_plans, rendered_tables))

            namespaced_checks = _namespace_checks(scenario.id, scenario_checks)
            scenario_generations.append(
                ScenarioGeneration(
                    scenario_id=scenario.id,
                    scenario_title=scenario.title,
                    generated_tables=rendered_tables,
                    validation_checks=namespaced_checks,
                )
            )
            generated_tables.extend(rendered_tables)
            validation_checks.extend(namespaced_checks)

        return GenerationReport(
            requirement=draft.requirement,
            scenarios=scenarios,
            table_plans=draft.table_plans,
            generated_tables=generated_tables,
            scenario_generations=scenario_generations,
            validation_checks=validation_checks,
            generation_tag=normalized_generation_tag or "",
        )

    def _decide_ai_field_strategies_for_scenario(
        self,
        requirement_text: str,
        scenario: ScenarioDraft,
        relevant_plans: list[TableDataPlan],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        use_ai_field_decisions: bool,
        local_field_cache: dict[str, set[str]] | None = None,
        imported_field_decisions: dict[str, AiTableGenerationAdvice] | None = None,
        prior_field_decisions: dict[str, AiTableGenerationAdvice] | None = None,
    ) -> dict[str, AiTableGenerationAdvice]:
        if local_field_cache is None:
            local_field_cache = {}
        if prior_field_decisions is None:
            prior_field_decisions = {}

        decisions: dict[str, AiTableGenerationAdvice] = {}
        pending_requests: list[dict[str, object]] = []

        supports_single_decision = hasattr(self._ai_data_generation_service, "decide_table_field_strategies")
        supports_batch_decision = hasattr(self._ai_data_generation_service, "decide_tables_field_strategies")

        for table_plan in relevant_plans:
            table_name = table_plan.table_name
            imported_advice = (imported_field_decisions or {}).get(table_name)
            if imported_advice is not None:
                decisions[table_name] = imported_advice
                prior_field_decisions[table_name] = imported_advice
                continue

            schema = self._schema_repository.get_table_schema(table_name)
            local_fields = local_field_cache.setdefault(
                table_name,
                self._local_field_rule_service.identify_local_fields(schema),
            )

            reusable_advice = (
                self._reusable_strategy_service.load_table_advice(
                    table_name=table_name,
                    available_tables=[plan.table_name for plan in relevant_plans],
                )
                if self._reusable_strategy_service is not None
                else AiTableGenerationAdvice(table_name=table_name)
            )
            merged_prior_advice = _merge_ai_advice(
                reusable_advice,
                prior_field_decisions.get(table_name, AiTableGenerationAdvice(table_name=table_name)),
            )
            prior_advice = _normalize_prior_advice(merged_prior_advice)
            if not use_ai_field_decisions:
                decisions[table_name] = prior_advice or AiTableGenerationAdvice(table_name=table_name)
                continue

            if self._ai_data_generation_service is None or (not supports_single_decision and not supports_batch_decision):
                decisions[table_name] = prior_advice or AiTableGenerationAdvice(table_name=table_name)
                continue

            pending_requests.append(
                {
                    "table_name": table_name,
                    "schema": schema,
                    "scenario_summaries": [
                        f"{scenario.title}: {scenario.objective}; Table requirement: {scenario.table_requirements.get(table_name, '') or 'default generation'}"
                    ],
                    "local_generated_columns": local_fields,
                    "prior_advice": prior_advice,
                }
            )

        if supports_batch_decision and pending_requests:
            try:
                batch_decisions = self._ai_data_generation_service.decide_tables_field_strategies(
                    requirement_text=requirement_text,
                    table_requests=pending_requests,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                )
            except Exception:
                batch_decisions = {}
            for request in pending_requests:
                table_name = str(request["table_name"])
                current_advice = batch_decisions.get(table_name)
                if current_advice is None:
                    continue
                merged_advice = _merge_ai_advice(
                    request.get("prior_advice") or AiTableGenerationAdvice(table_name=table_name),
                    current_advice,
                )
                decisions[table_name] = merged_advice
                prior_field_decisions[table_name] = merged_advice
                self._persist_reusable_field_strategies(table_name, merged_advice)

        if supports_single_decision:
            for request in pending_requests:
                table_name = str(request["table_name"])
                if table_name in decisions:
                    continue
                current_advice = self._ai_data_generation_service.decide_table_field_strategies(
                    requirement_text=requirement_text,
                    table_name=table_name,
                    schema=request["schema"],
                    scenario_summaries=request["scenario_summaries"],
                    local_generated_columns=request["local_generated_columns"],
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                    prior_advice=request.get("prior_advice"),
                )
                merged_advice = _merge_ai_advice(
                    request.get("prior_advice") or AiTableGenerationAdvice(table_name=table_name),
                    current_advice,
                )
                decisions[table_name] = merged_advice
                prior_field_decisions[table_name] = merged_advice
                self._persist_reusable_field_strategies(table_name, merged_advice)

        for request in pending_requests:
            table_name = str(request["table_name"])
            if table_name in decisions:
                continue
            fallback_advice = request.get("prior_advice") or AiTableGenerationAdvice(table_name=table_name)
            decisions[table_name] = fallback_advice
            prior_field_decisions[table_name] = fallback_advice
            self._persist_reusable_field_strategies(table_name, fallback_advice)

        return decisions

    def _persist_reusable_field_strategies(
        self,
        table_name: str,
        advice: AiTableGenerationAdvice,
    ) -> None:
        if self._reusable_strategy_service is None:
            return
        self._reusable_strategy_service.save_generic_field_strategies(table_name, advice)

    def _persist_reusable_relation_strategies(
        self,
        scenario: ScenarioDraft,
        relevant_plans: list[TableDataPlan],
    ) -> None:
        if self._reusable_strategy_service is None or not scenario.relation_rules:
            return
        available_tables = {plan.table_name for plan in relevant_plans}
        records: list[StoredRelationStrategy] = []
        for rule in scenario.relation_rules:
            if rule.target_table not in available_tables or rule.source_table not in available_tables:
                continue
            if rule.relation_type not in {"same_value", "copy_from_context"}:
                continue
            records.append(
                StoredRelationStrategy(
                    target_table=rule.target_table,
                    target_field=rule.target_field,
                    source_table=rule.source_table,
                    source_field=rule.source_field,
                    strategy=FieldGenerationStrategy(
                        executor="local",
                        generator="copy_from_context",
                        params={
                            "source_table": rule.source_table,
                            "source_field": rule.source_field,
                        },
                        rationale=rule.rationale,
                    ),
                    relation_reason=rule.rationale or rule.relation_type,
                    strategy_source="scenario_inferred",
                    relation_type=rule.relation_type or "same_value",
                    evidence=dict(rule.evidence),
                )
            )
        if records:
            self._reusable_strategy_service.save_relation_strategies(records)

    def _generate_ai_rows(
        self,
        scenario: ScenarioDraft,
        relevant_plans: list[TableDataPlan],
        sample_limit: int,
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        use_ai_data: bool,
        sample_cache: dict[str, list[dict[str, str]]] | None = None,
        analysis_cache: dict[str, str] | None = None,
        local_field_cache: dict[str, set[str]] | None = None,
    ) -> dict[str, AiTableGenerationAdvice]:
        if not use_ai_data or self._ai_data_generation_service is None or self._sample_repository is None:
            return {}

        if sample_cache is None:
            sample_cache = {}
        if analysis_cache is None:
            analysis_cache = {}
        if local_field_cache is None:
            local_field_cache = {}
        schemas = {
            table_plan.table_name: self._schema_repository.get_table_schema(table_plan.table_name)
            for table_plan in relevant_plans
        }
        local_generated_columns = {
            table_name: local_field_cache.setdefault(
                table_name,
                self._local_field_rule_service.identify_local_fields(schema),
            )
            for table_name, schema in schemas.items()
        }
        visible_samples = {
            table_name: sample_cache.setdefault(
                table_name,
                self._sample_repository.sample_rows(table_name, sample_limit),
            )
            for table_name in schemas
        }
        analysis_by_table: dict[str, str] = {}
        if self._ai_data_analysis_service is not None:
            for table_name, schema in schemas.items():
                if table_name not in analysis_cache:
                    try:
                        analysis_cache[table_name] = self._ai_data_analysis_service.analyze(
                            table_name=table_name,
                            schema=schema,
                            sample_rows=visible_samples[table_name],
                            fixed_values=fixed_values,
                            dependent_fixed_values=dependent_fixed_values,
                        )
                    except Exception:
                        analysis_cache[table_name] = "{}"
                analysis_by_table[table_name] = analysis_cache[table_name]
        return self._ai_data_generation_service.generate(
            scenario=scenario,
            schemas=schemas,
            sample_rows_by_table=visible_samples,
            local_generated_columns=local_generated_columns,
            analysis_by_table=analysis_by_table,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
        )

    def _decide_ai_field_strategies(
        self,
        requirement_text: str,
        scenarios: list[ScenarioDraft],
        table_plans: list[TableDataPlan],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        use_ai_field_decisions: bool,
        local_field_cache: dict[str, set[str]] | None = None,
        imported_field_decisions: dict[str, AiTableGenerationAdvice] | None = None,
    ) -> dict[str, AiTableGenerationAdvice]:
        decisions: dict[str, AiTableGenerationAdvice] = {
            table_name: advice
            for table_name, advice in (imported_field_decisions or {}).items()
            if _has_explicit_field_decisions(advice)
        }
        if not use_ai_field_decisions or self._ai_data_generation_service is None:
            return decisions
        supports_single_decision = hasattr(self._ai_data_generation_service, "decide_table_field_strategies")
        supports_batch_decision = hasattr(self._ai_data_generation_service, "decide_tables_field_strategies")
        if not supports_single_decision and not supports_batch_decision:
            return decisions

        if local_field_cache is None:
            local_field_cache = {}

        scenario_context_by_table: dict[str, list[str]] = {}
        for scenario in scenarios:
            for table_plan in _select_table_plans(table_plans, scenario):
                requirement = scenario.table_requirements.get(table_plan.table_name, "") or "default generation"
                scenario_context_by_table.setdefault(table_plan.table_name, []).append(
                    f"{scenario.title}: {scenario.objective}; Table requirement: {requirement}"
                )

        pending_requests: list[dict[str, object]] = []
        for table_plan in table_plans:
            table_name = table_plan.table_name
            if table_name in decisions:
                continue
            schema = self._schema_repository.get_table_schema(table_name)
            local_fields = local_field_cache.setdefault(
                table_name,
                self._local_field_rule_service.identify_local_fields(schema),
            )
            pending_requests.append(
                {
                    "table_name": table_name,
                    "schema": schema,
                    "scenario_summaries": scenario_context_by_table.get(table_name, []),
                    "local_generated_columns": local_fields,
                }
            )

        if supports_batch_decision and pending_requests:
            try:
                batch_decisions = self._ai_data_generation_service.decide_tables_field_strategies(
                    requirement_text=requirement_text,
                    table_requests=pending_requests,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                )
                for table_name, advice in batch_decisions.items():
                    if _has_explicit_field_decisions(advice):
                        decisions[table_name] = advice
            except Exception:
                pass

        if not supports_single_decision:
            return decisions

        for request in pending_requests:
            table_name = str(request["table_name"])
            if table_name in decisions:
                continue
            decisions[table_name] = self._ai_data_generation_service.decide_table_field_strategies(
                requirement_text=requirement_text,
                table_name=table_name,
                schema=request["schema"],
                scenario_summaries=request["scenario_summaries"],
                local_generated_columns=request["local_generated_columns"],
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
            )
        return decisions

    def _generate_table(
        self,
        table_plan: TableDataPlan,
        scenario: ScenarioDraft,
        generation_tag: str | None,
        fixed_value_map: dict[str, str],
        ai_advice: AiTableGenerationAdvice,
        generation_source: str = "local",
        scenario_context: dict[str, list[str | None]] | None = None,
        requirement_overrides: dict[str, list[str]] | None = None,
    ) -> tuple[GeneratedTable, list[ValidationCheck]]:
        schema = self._schema_repository.get_table_schema(table_plan.table_name)
        field_generation_strategies = _resolve_table_generation_strategies(
            schema=schema,
            table_plan=table_plan,
            fixed_value_map=fixed_value_map,
            ai_advice=ai_advice,
            local_field_rule_service=self._local_field_rule_service,
        )
        field_generation_strategies = _apply_requirement_overrides_to_generation_strategies(
            schema=schema,
            field_generation_strategies=field_generation_strategies,
            requirement_overrides=requirement_overrides or {},
        )
        rows = self.generate_table_rows(
            table_plan=table_plan,
            schema=schema,
            generation_tag=generation_tag,
            fixed_value_map=fixed_value_map,
            ai_advice=ai_advice,
            field_generation_strategies=field_generation_strategies,
            scenario_context=scenario_context,
            requirement_overrides=requirement_overrides,
        )
        field_strategies = _resolve_table_field_strategies(field_generation_strategies)
        return (
            GeneratedTable(
                table_name=table_plan.table_name,
                row_count=len(rows),
                rows=rows,
                insert_sql=[],
                scenario_id=scenario.id,
                scenario_title=scenario.title,
                scenario_objective=scenario.objective,
                field_strategies=field_strategies,
                field_generation_strategies=field_generation_strategies,
                generation_source=generation_source,
            ),
            [],
        )

    def _derive_scenario_requirement_overrides(
        self,
        scenario: ScenarioDraft,
        relevant_plans: list[TableDataPlan],
    ) -> dict[str, dict[str, list[str]]]:
        overrides_by_table: dict[str, dict[str, list[str]]] = {}
        for table_plan in relevant_plans:
            requirement_text = str(scenario.table_requirements.get(table_plan.table_name, "") or "").strip()
            if not requirement_text:
                continue
            schema = self._schema_repository.get_table_schema(table_plan.table_name)
            parsed = _parse_requirement_overrides(requirement_text, schema)
            if parsed:
                overrides_by_table[table_plan.table_name] = parsed
        return overrides_by_table

    def _render_validated_table(
        self,
        scenario: ScenarioDraft,
        generated_table: GeneratedTable,
    ) -> tuple[GeneratedTable, list[ValidationCheck]]:
        schema = self._schema_repository.get_table_schema(generated_table.table_name)
        rows, record_checks = self._record_validation_service.validate_table(
            schema,
            generated_table.rows,
            check_prefix=f"record_validation:{generated_table.table_name}",
        )
        insert_sql = self._insert_render_service.render_table(schema, rows)
        return (
            GeneratedTable(
                table_name=generated_table.table_name,
                row_count=len(rows),
                rows=rows,
                insert_sql=[insert_sql] if insert_sql else [],
                scenario_id=scenario.id,
                scenario_title=scenario.title,
                scenario_objective=scenario.objective,
                field_strategies=generated_table.field_strategies,
                field_generation_strategies=generated_table.field_generation_strategies,
                generation_source=generated_table.generation_source,
            ),
            record_checks,
        )

    def generate_table_rows(
        self,
        table_plan: TableDataPlan,
        schema: TableSchema,
        generation_tag: str | None = None,
        fixed_value_map: dict[str, str] | None = None,
        ai_advice: AiTableGenerationAdvice | None = None,
        field_generation_strategies: dict[str, FieldGenerationStrategy] | None = None,
        scenario_context: dict[str, list[str | None]] | None = None,
        requirement_overrides: dict[str, list[str]] | None = None,
    ) -> list[GeneratedRow]:
        normalized_generation_tag = _normalize_generation_tag(generation_tag)
        ai_advice = ai_advice or AiTableGenerationAdvice(table_name=table_plan.table_name)
        scenario_context = scenario_context or {}
        requirement_overrides = requirement_overrides or {}
        field_generation_strategies = field_generation_strategies or _resolve_table_generation_strategies(
            schema=schema,
            table_plan=table_plan,
            fixed_value_map=fixed_value_map or {},
            ai_advice=ai_advice,
            local_field_rule_service=self._local_field_rule_service,
        )
        row_count = max(1, len(ai_advice.rows) or table_plan.row_hint)
        column_plans = {plan.column_name: plan for plan in table_plan.column_plans}
        rows: list[GeneratedRow] = []

        for row_index in range(row_count):
            ai_row = ai_advice.rows[row_index] if row_index < len(ai_advice.rows) else {}
            values: dict[str, str | None] = {}
            deferred_columns: list[tuple[TableColumn, object]] = []
            for column in schema.columns:
                column_plan = column_plans.get(column.name)
                generation_strategy = field_generation_strategies.get(column.name)
                if (
                    generation_strategy is not None
                    and self._local_field_rule_service.is_contextual_generator(generation_strategy.generator)
                ):
                    deferred_columns.append((column, column_plan))
                    continue
                values[column.name] = self._materialize_value(
                    table_name=table_plan.table_name,
                    column=column,
                    column_plan=column_plan,
                    row_index=row_index,
                    generation_tag=normalized_generation_tag,
                    fixed_value_map=fixed_value_map or {},
                    ai_value=ai_row.get(column.name),
                    ai_strategy=ai_advice.field_strategies.get(column.name),
                    generation_strategy=generation_strategy,
                    row_values=values,
                    scenario_context=scenario_context,
                    requirement_override_values=requirement_overrides.get(column.name),
                )
            for allow_fallback_generators in (False, True):
                if not deferred_columns:
                    break
                unresolved_columns: list[tuple[TableColumn, object]] = []
                for column, column_plan in deferred_columns:
                    resolved_value = self._materialize_value(
                        table_name=table_plan.table_name,
                        column=column,
                        column_plan=column_plan,
                        row_index=row_index,
                        generation_tag=normalized_generation_tag,
                        fixed_value_map=fixed_value_map or {},
                        ai_value=ai_row.get(column.name),
                        ai_strategy=ai_advice.field_strategies.get(column.name),
                        generation_strategy=field_generation_strategies.get(column.name),
                        row_values=values,
                        scenario_context=scenario_context,
                        allow_fallback_generators=allow_fallback_generators,
                        requirement_override_values=requirement_overrides.get(column.name),
                    )
                    if resolved_value is _UNRESOLVED:
                        unresolved_columns.append((column, column_plan))
                        continue
                    values[column.name] = resolved_value
                deferred_columns = unresolved_columns
            for column, column_plan in deferred_columns:
                resolved_value = self._materialize_value(
                    table_name=table_plan.table_name,
                    column=column,
                    column_plan=column_plan,
                    row_index=row_index,
                    generation_tag=normalized_generation_tag,
                    fixed_value_map=fixed_value_map or {},
                    ai_value=ai_row.get(column.name),
                    ai_strategy=ai_advice.field_strategies.get(column.name),
                    generation_strategy=field_generation_strategies.get(column.name),
                    row_values=values,
                    scenario_context=scenario_context,
                    allow_fallback_generators=True,
                    requirement_override_values=requirement_overrides.get(column.name),
                )
                values[column.name] = None if resolved_value is _UNRESOLVED else resolved_value
            rows.append(GeneratedRow(values=values))

        return rows

    def _materialize_value(
        self,
        table_name: str,
        column: TableColumn,
        column_plan,
        row_index: int,
        generation_tag: str | None = None,
        fixed_value_map: dict[str, str] | None = None,
        ai_value: str | None = None,
        ai_strategy: str | None = None,
        generation_strategy: FieldGenerationStrategy | None = None,
        row_values: dict[str, str | None] | None = None,
        scenario_context: dict[str, list[str | None]] | None = None,
        allow_fallback_generators: bool = True,
        requirement_override_values: list[str] | None = None,
    ) -> str | None | object:
        if column_plan is None:
            return _fallback_value(column, row_index)

        source = column_plan.source
        values = list(column_plan.suggested_values)
        fixed_value_map = fixed_value_map or {}
        row_values = row_values or {}
        scenario_context = scenario_context or {}
        normalized_ai_value = _normalize_ai_value(ai_value)
        normalized_ai_strategy = _normalize_ai_strategy(ai_strategy)
        is_contextual_strategy = (
            generation_strategy is not None
            and self._local_field_rule_service.is_contextual_generator(generation_strategy.generator)
        )

        if column.name in fixed_value_map:
            return fixed_value_map[column.name]

        normalized_requirement_values = _normalize_requirement_override_values(requirement_override_values, column)
        if normalized_requirement_values and not column.is_primary_key:
            return _pick_cycle(normalized_requirement_values, row_index)

        if column.is_primary_key and source != "condition":
            return _generated_value(table_name, column, row_index, generation_tag)
        if source == "condition":
            return _pick_cycle(values, row_index) if values else _fallback_value(column, row_index)

        if generation_strategy is not None:
            strategy_value = self._materialize_strategy_value(
                table_name=table_name,
                column=column,
                row_index=row_index,
                generation_tag=generation_tag,
                fixed_value_map=fixed_value_map,
                suggested_values=values,
                generation_strategy=generation_strategy,
                ai_value=normalized_ai_value,
                row_values=row_values,
                scenario_context=scenario_context,
                allow_fallback_generators=allow_fallback_generators,
            )
            if strategy_value is _UNRESOLVED:
                return _UNRESOLVED
            if strategy_value is not None:
                return strategy_value
            if generation_strategy.executor == "local" and generation_strategy.generator == "null":
                return strategy_value
            if is_contextual_strategy and not allow_fallback_generators:
                return _UNRESOLVED

        if normalized_ai_strategy == "ai" and normalized_ai_value is not None:
            return normalized_ai_value

        local_value = self._local_field_rule_service.generate_value(
            column=column,
            row_index=row_index,
            generation_tag=generation_tag,
            fixed_values=fixed_value_map,
        )

        if normalized_ai_strategy == "local" and local_value is not None:
            return local_value

        if normalized_ai_strategy is None and normalized_ai_value is not None:
            return normalized_ai_value

        if local_value is not None:
            return local_value

        if normalized_ai_value is not None:
            return normalized_ai_value

        if source in {"dictionary", "sample"}:
            return _pick_cycle(values, row_index) if values else _fallback_value(column, row_index)
        if source == "generated":
            return _generated_value(table_name, column, row_index, generation_tag)
        if source == "default":
            return _runtime_default_value(column, row_index, values)
        if source == "optional":
            return None
        return _fallback_value(column, row_index)

    def _materialize_strategy_value(
        self,
        table_name: str,
        column: TableColumn,
        row_index: int,
        generation_tag: str | None,
        fixed_value_map: dict[str, str],
        suggested_values: list[str],
        generation_strategy: FieldGenerationStrategy,
        ai_value: str | None,
        row_values: dict[str, str | None],
        scenario_context: dict[str, list[str | None]],
        allow_fallback_generators: bool,
    ) -> str | None | object:
        generators = [generation_strategy.generator, *generation_strategy.fallback_generators]
        if generation_strategy.executor == "ai" and generation_strategy.generator == "ai_value":
            if ai_value is not None:
                return ai_value
            if not allow_fallback_generators:
                return _UNRESOLVED
        for generator_name in generators:
            if not allow_fallback_generators and generator_name != generation_strategy.generator:
                break
            value = self._local_field_rule_service.generate_with_generator(
                column=column,
                generator=generator_name,
                params=generation_strategy.params,
                row_index=row_index,
                generation_tag=generation_tag,
                fixed_values=fixed_value_map,
                row_values=row_values,
                scenario_context=scenario_context,
            )
            if generator_name == "fixed_value" and isinstance(value, str):
                normalized_value = _normalize_placeholder_fixed_value(value, row_index)
                if normalized_value is None and _looks_like_placeholder_value(value):
                    continue
                if normalized_value is not None:
                    return normalized_value
            if value is not None or generator_name == "null":
                return value
            if (
                not allow_fallback_generators
                and self._local_field_rule_service.is_contextual_generator(generator_name)
            ):
                return _UNRESOLVED
            generic_value = _materialize_generic_generator(
                generator_name=generator_name,
                table_name=table_name,
                column=column,
                row_index=row_index,
                generation_tag=generation_tag,
                suggested_values=suggested_values,
            )
            if generic_value is not None:
                return generic_value
        if generation_strategy.executor == "ai":
            return ai_value
        return None


def _select_table_plans(table_plans: list[TableDataPlan], scenario: ScenarioDraft) -> list[TableDataPlan]:
    selected_tables = set(scenario.tables or scenario.table_requirements)
    if not selected_tables:
        return list(table_plans)
    return [table_plan for table_plan in table_plans if table_plan.table_name in selected_tables]


def _namespace_checks(scenario_id: str, checks: list[ValidationCheck]) -> list[ValidationCheck]:
    if scenario_id == "default":
        return checks
    return [
        ValidationCheck(
            name=f"{scenario_id}:{check.name}",
            passed=check.passed,
            detail=check.detail,
        )
        for check in checks
    ]


def _update_scenario_context(
    scenario_context: dict[str, list[str | None]],
    generated_table: GeneratedTable,
) -> None:
    for field_name in {
        field_name
        for row in generated_table.rows
        for field_name in row.values
    }:
        scenario_context[field_name] = [row.values.get(field_name) for row in generated_table.rows]


def _merge_ai_advice(
    base_advice: AiTableGenerationAdvice,
    override_advice: AiTableGenerationAdvice,
) -> AiTableGenerationAdvice:
    if (
        not base_advice.rows
        and not base_advice.field_strategies
        and not base_advice.field_generation_strategies
    ):
        return override_advice
    if (
        not override_advice.rows
        and not override_advice.field_strategies
        and not override_advice.field_generation_strategies
    ):
        return base_advice
    return AiTableGenerationAdvice(
        table_name=override_advice.table_name or base_advice.table_name,
        rows=override_advice.rows or base_advice.rows,
        field_strategies={**base_advice.field_strategies, **override_advice.field_strategies},
        field_generation_strategies={
            **base_advice.field_generation_strategies,
            **override_advice.field_generation_strategies,
        },
    )


def _has_explicit_field_decisions(advice: AiTableGenerationAdvice | None) -> bool:
    if advice is None:
        return False
    return bool(advice.field_strategies or advice.field_generation_strategies)


def _normalize_prior_advice(advice: AiTableGenerationAdvice) -> AiTableGenerationAdvice | None:
    if advice.rows or _has_explicit_field_decisions(advice):
        return advice
    return None


def _scenario_generation_tag(
    base_tag: str | None,
    scenario: ScenarioDraft,
    scenario_index: int,
    scenario_count: int,
) -> str | None:
    if base_tag is None and scenario_count <= 1:
        return None
    scenario_token = _normalize_generation_tag(f"{scenario.id}_{scenario_index}")
    if base_tag:
        return _normalize_generation_tag(f"{base_tag}_{scenario_token}")
    return scenario_token


def _normalize_ai_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized in {"", "[DEFAULT]"}:
        return None
    if normalized.upper() in {"NULL", "[NULL]"}:
        return None
    return normalized


def _normalize_ai_strategy(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"ai", "local"}:
        return normalized
    return None


def _resolve_table_field_strategies(
    field_generation_strategies: dict[str, FieldGenerationStrategy],
) -> dict[str, str]:
    return {
        field_name: ("ai" if strategy.executor == "ai" else "local")
        for field_name, strategy in field_generation_strategies.items()
    }


def _apply_requirement_overrides_to_generation_strategies(
    schema: TableSchema,
    field_generation_strategies: dict[str, FieldGenerationStrategy],
    requirement_overrides: dict[str, list[str]],
) -> dict[str, FieldGenerationStrategy]:
    if not requirement_overrides:
        return field_generation_strategies
    column_by_name = {column.name: column for column in schema.columns}
    updated = dict(field_generation_strategies)
    for field_name, raw_values in requirement_overrides.items():
        column = column_by_name.get(field_name)
        if column is None or column.is_primary_key:
            continue
        values = _normalize_requirement_override_values(raw_values, column)
        if not values:
            continue
        if len(values) == 1:
            updated[field_name] = FieldGenerationStrategy(
                executor="local",
                generator="fixed_value",
                params={"value": values[0]},
                fallback_generators=[],
                rationale="scenario table requirement override",
            )
            continue
        updated[field_name] = FieldGenerationStrategy(
            executor="local",
            generator="condition_value",
            params={"values": values},
            fallback_generators=[],
            rationale="scenario table requirement override",
        )
    return updated


def _parse_requirement_overrides(requirement_text: str, schema: TableSchema) -> dict[str, list[str]]:
    if not requirement_text:
        return {}
    column_by_lower_name = {column.name.lower(): column for column in schema.columns}
    parsed: dict[str, list[str]] = {}

    for match in _REQUIREMENT_IN_RE.finditer(requirement_text):
        column_name = str(match.group(1) or "").strip()
        column = column_by_lower_name.get(column_name.lower())
        if column is None:
            continue
        values = [_clean_requirement_value(item) for item in _split_requirement_values(match.group(2) or "")]
        values = [value for value in values if value]
        normalized = _normalize_requirement_override_values(values, column)
        if not normalized:
            continue
        parsed[column.name] = _merge_requirement_values(parsed.get(column.name, []), normalized)

    for match in _REQUIREMENT_EQ_RE.finditer(requirement_text):
        column_name = str(match.group(1) or "").strip()
        column = column_by_lower_name.get(column_name.lower())
        if column is None:
            continue
        value = _clean_requirement_value(match.group(2) or "")
        normalized = _normalize_requirement_override_values([value], column)
        if not normalized:
            continue
        parsed[column.name] = _merge_requirement_values(parsed.get(column.name, []), normalized)

    return parsed


def _split_requirement_values(raw_value_list: str) -> list[str]:
    if not raw_value_list:
        return []
    return [part.strip() for part in re.split(r"[,\uFF0C]", raw_value_list) if part.strip()]


def _clean_requirement_value(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        value = value[1:-1].strip()
    value = value.strip().strip("`").strip()
    value = value.replace("\\'", "'").replace('\\"', '"')
    value = re.sub(r"\s*[（(][^()（）]*[)）]\s*$", "", value).strip()
    return value


def _normalize_requirement_override_values(values: list[str] | None, column: TableColumn) -> list[str]:
    normalized: list[str] = []
    for raw_value in values or []:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if not _is_requirement_value_compatible_with_column(value, column):
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized


def _is_requirement_value_compatible_with_column(value: str, column: TableColumn) -> bool:
    lowered = column.type.lower()
    if "datetime" in lowered or "timestamp" in lowered:
        return _parse_datetime_value(value) is not None
    if "date" in lowered:
        return _parse_datetime_value(value) is not None
    if lowered.startswith("time"):
        return bool(re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value))
    if any(token in lowered for token in ("int", "decimal", "float", "double", "numeric")):
        try:
            float(value)
        except ValueError:
            return False
    return True


def _merge_requirement_values(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for value in incoming:
        if value not in merged:
            merged.append(value)
    return merged


def _resolve_table_generation_strategies(
    schema: TableSchema,
    table_plan: TableDataPlan,
    fixed_value_map: dict[str, str],
    ai_advice: AiTableGenerationAdvice,
    local_field_rule_service: LocalFieldRuleService,
) -> dict[str, FieldGenerationStrategy]:
    plan_by_column = {plan.column_name: plan for plan in table_plan.column_plans}
    strategies: dict[str, FieldGenerationStrategy] = {}
    for column in schema.columns:
        column_plan = plan_by_column.get(column.name)
        default_strategy = _build_default_generation_strategy(
            column=column,
            column_plan=column_plan,
            fixed_value_map=fixed_value_map,
            local_field_rule_service=local_field_rule_service,
        )
        ai_strategy = ai_advice.field_generation_strategies.get(column.name)
        resolved = _merge_generation_strategy(
            default_strategy=default_strategy,
            ai_strategy=ai_strategy,
            ai_label=ai_advice.field_strategies.get(column.name),
            ai_value_present=any(_normalize_ai_value(row.get(column.name)) is not None for row in ai_advice.rows),
        )
        strategies[column.name] = resolved
    return strategies


def _build_default_generation_strategy(
    column: TableColumn,
    column_plan,
    fixed_value_map: dict[str, str],
    local_field_rule_service: LocalFieldRuleService,
) -> FieldGenerationStrategy:
    suggested_values = list(column_plan.suggested_values) if column_plan is not None else []
    source = column_plan.source if column_plan is not None else ""

    if column.name in fixed_value_map:
        return FieldGenerationStrategy(
            executor="local",
            generator="fixed_value",
            params={"value": fixed_value_map[column.name]},
            rationale="fixed value override",
        )
    if column.is_primary_key and source != "condition":
        return FieldGenerationStrategy(
            executor="local",
            generator="generated_value",
            rationale="generate primary key locally",
        )
    if source == "condition":
        return FieldGenerationStrategy(
            executor="local",
            generator="condition_value",
            params={"values": suggested_values},
            rationale="SQL condition value",
        )
    if local_field_rule_service.has_local_rule(column):
        if column.name.lower() == "transactionkey" or "transaction" in column.comment.lower():
            return FieldGenerationStrategy(
                executor="local",
                generator="transaction_key",
                fallback_generators=["sample_cycle", "default_value"],
                rationale="local transaction key generator",
            )
        if column.name.lower() == "model_seq" or "model" in column.comment.lower():
            return FieldGenerationStrategy(
                executor="local",
                generator="model_seq_blank",
                fallback_generators=["default_value"],
                rationale="local model sequence generator",
            )
        if source == "dictionary":
            return FieldGenerationStrategy(
                executor="local",
                generator="dictionary_cycle",
                params={"values": suggested_values},
                fallback_generators=["sample_cycle"],
                rationale="dictionary value cycle",
            )
        return FieldGenerationStrategy(
            executor="local",
            generator="customer_id",
            fallback_generators=["sample_cycle", "default_value"],
            rationale="local customer id generator",
        )
    if source == "dictionary":
        return FieldGenerationStrategy(
            executor="local",
            generator="dictionary_cycle",
            params={"values": suggested_values},
            fallback_generators=["default_value"],
            rationale="dictionary value cycle",
        )
    if source == "sample":
        if _looks_like_sequence_column(column) and suggested_values:
            return FieldGenerationStrategy(
                executor="local",
                generator="sequence_cycle",
                params={"values": suggested_values},
                fallback_generators=["default_value"],
                rationale="sequence sample cycle",
            )
        if _looks_like_datetime_values(suggested_values):
            return FieldGenerationStrategy(
                executor="local",
                generator="datetime_range_cycle",
                params={"values": suggested_values},
                fallback_generators=["default_value"],
                rationale="datetime sample cycle",
            )
        if _looks_like_decimal_values(suggested_values):
            return FieldGenerationStrategy(
                executor="local",
                generator="amount_pattern_cycle",
                params={"values": suggested_values},
                fallback_generators=["default_value"],
                rationale="amount sample cycle",
            )
        return FieldGenerationStrategy(
            executor="local",
            generator="sample_cycle",
            params={"values": suggested_values},
            fallback_generators=["default_value"],
            rationale="sample value cycle",
        )
    if source == "generated":
        return FieldGenerationStrategy(
            executor="local",
            generator="generated_value",
            rationale="local generated value",
        )
    if source == "default":
        return FieldGenerationStrategy(
            executor="local",
            generator="default_value",
            params={"values": suggested_values},
            fallback_generators=["fallback_value"],
            rationale="default value generation",
        )
    if source == "optional":
        return FieldGenerationStrategy(
            executor="local",
            generator="null",
            rationale="optional field defaults to null",
        )
    return FieldGenerationStrategy(
        executor="local",
        generator="fallback_value",
        rationale="local fallback generation",
    )


def _merge_generation_strategy(
    default_strategy: FieldGenerationStrategy,
    ai_strategy: FieldGenerationStrategy | None,
    ai_label: str | None,
    ai_value_present: bool,
) -> FieldGenerationStrategy:
    if ai_strategy is None:
        if ai_value_present or _normalize_ai_strategy(ai_label) == "ai":
            return FieldGenerationStrategy(
                executor="ai",
                generator="ai_value",
                fallback_generators=[default_strategy.generator, *default_strategy.fallback_generators],
                rationale="AI generated field value",
            )
        return default_strategy

    if default_strategy.generator in {"fixed_value", "condition_value", "generated_value"}:
        return default_strategy

    executor = ai_strategy.executor or default_strategy.executor
    generator = ai_strategy.generator or default_strategy.generator
    fallback_generators = list(ai_strategy.fallback_generators or [])
    if not fallback_generators and default_strategy.generator and default_strategy.generator != generator:
        fallback_generators.append(default_strategy.generator)
    for fallback in default_strategy.fallback_generators:
        if fallback and fallback not in fallback_generators and fallback != generator:
            fallback_generators.append(fallback)
    params = ai_strategy.params or default_strategy.params
    return FieldGenerationStrategy(
        executor=executor,
        generator=generator,
        params=params,
        fallback_generators=fallback_generators,
        rationale=ai_strategy.rationale or default_strategy.rationale,
        implementation_hint=ai_strategy.implementation_hint,
        implementation_code=ai_strategy.implementation_code,
    )


def _materialize_generic_generator(
    generator_name: str,
    table_name: str,
    column: TableColumn,
    row_index: int,
    generation_tag: str | None,
    suggested_values: list[str],
) -> str | None:
    normalized = (generator_name or "").strip().lower()
    if normalized == "generated_value":
        return _generated_value(table_name, column, row_index, generation_tag)
    if normalized == "default_value":
        return _runtime_default_value(column, row_index, suggested_values)
    if normalized == "fallback_value":
        return _fallback_value(column, row_index)
    return None


def _looks_like_sequence_column(column: TableColumn) -> bool:
    name = column.name.lower()
    comment = column.comment.lower()
    return name in {"seq_no", "sequence_no"} or "sequence" in comment


def _looks_like_datetime_values(values: list[str]) -> bool:
    if not values:
        return False
    parsed = [
        _parse_datetime_value(value)
        for value in values
        if value not in {"", DEFAULT_MARKER, "[NULL]"}
    ]
    return bool(parsed) and all(item is not None for item in parsed)


def _looks_like_decimal_values(values: list[str]) -> bool:
    numeric_values: list[str] = [
        value
        for value in values
        if value not in {"", DEFAULT_MARKER, "[NULL]"}
    ]
    if not numeric_values:
        return False
    try:
        [float(value) for value in numeric_values]
    except ValueError:
        return False
    return any("." in value or value.startswith("-") for value in numeric_values)


def _parse_datetime_value(value: str) -> datetime | None:
    text = str(value).strip()
    if not text:
        return None
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _looks_like_placeholder_value(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False
    lowered = text.lower()
    keywords = (
        "random",
        "sequence",
        "different time",
        "unique",
        "generate",
        "relation",
        "mapping",
        "placeholder",
        "generate different timestamp",
        "time placeholder",
        "amount placeholder",
    )
    return any(keyword in lowered for keyword in keywords)

def _normalize_placeholder_fixed_value(value: str, row_index: int) -> str | None:
    text = str(value).strip()
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if match is None:
        return None

    placeholder_keywords = (
        "different time",
        "generate different timestamp",
        "time placeholder",
        "amount placeholder",
    )
    if not any(keyword in text.lower() for keyword in placeholder_keywords):
        return None

    base = datetime.strptime(match.group(1), "%Y-%m-%d")
    return (base + timedelta(minutes=row_index * 7 + 9 * 60)).strftime("%Y-%m-%d %H:%M:%S")

def _pick_cycle(values: list[str], row_index: int) -> str | None:
    if not values:
        return None
    return values[row_index % len(values)]


def _fallback_value(column: TableColumn, row_index: int) -> str | None:
    if column.nullable:
        return None
    return _runtime_default_value(column, row_index, [])


def _generated_value(
    table_name: str,
    column: TableColumn,
    row_index: int,
    generation_tag: str | None = None,
) -> str:
    if column.is_auto_primary_key:
        return DEFAULT_MARKER

    lowered = column.type.lower()
    sequence = row_index + 1
    if any(token in lowered for token in ("int", "decimal", "float", "double", "numeric")):
        if generation_tag:
            return _generated_numeric_value(generation_tag, sequence)
        return str(sequence)

    prefix = table_name.upper().replace("_", "")[:8] or "ROW"
    token = _generation_token(generation_tag)
    return _fit_generated_text(prefix, token, sequence, column.max_length)


def _generated_numeric_value(generation_tag: str, sequence: int) -> str:
    hashed = int(hashlib.sha1(generation_tag.encode("utf-8")).hexdigest()[:8], 16)
    base = 100_000_000 + (hashed % 800_000_000)
    return str(base + sequence - 1)


def _runtime_default_value(column: TableColumn, row_index: int, suggested_values: list[str]) -> str:
    explicit = next(
        (
            value
            for value in suggested_values
            if value not in {"", DEFAULT_MARKER, "[NULL]"}
        ),
        None,
    )
    if explicit is not None:
        return explicit

    if column.default_value:
        default_value = column.default_value.strip()
        if default_value.lower().startswith("current_timestamp"):
            return DEFAULT_MARKER
        return default_value

    lowered = column.type.lower()
    if any(token in lowered for token in ("int", "decimal", "float", "double", "numeric")):
        return "0"
    if "datetime" in lowered or "timestamp" in lowered:
        return "1970-01-01 00:00:00"
    if "date" in lowered:
        return "1970-01-01"
    if lowered.startswith("time"):
        return "00:00:00"

    value = f"{column.name}_{row_index + 1}"
    return _fit_prefix(value, column.max_length)


def _normalize_generation_tag(generation_tag: str | None) -> str | None:
    if generation_tag is None:
        return None
    normalized = "".join(character for character in generation_tag.upper() if character.isalnum())
    return normalized or None


def _generation_token(generation_tag: str | None) -> str:
    if not generation_tag:
        return ""
    return hashlib.sha1(generation_tag.encode("utf-8")).hexdigest()[:6].upper()


def _fit_generated_text(prefix: str, token: str, sequence: int, max_length: int) -> str:
    sequence_part = f"{sequence:03d}"
    if token:
        compact = f"{token}_{sequence_part}"
        available_prefix = max_length - len(compact) - 1
        if max_length > 0 and available_prefix > 0:
            return f"{prefix[:available_prefix]}_{compact}"
        return _fit_suffix(f"{prefix}_{compact}", max_length)
    return _fit_suffix(f"{prefix}_{sequence_part}", max_length)


def _fit_prefix(value: str, max_length: int) -> str:
    if max_length <= 0 or len(value) <= max_length:
        return value
    return value[:max_length]


def _fit_suffix(value: str, max_length: int) -> str:
    if max_length <= 0 or len(value) <= max_length:
        return value
    return value[-max_length:]
