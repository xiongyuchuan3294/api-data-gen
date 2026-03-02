from __future__ import annotations

import hashlib

from api_data_gen.domain.models import (
    GeneratedRow,
    GeneratedTable,
    GenerationReport,
    InterfaceTarget,
    ScenarioDraft,
    ScenarioGeneration,
    TableColumn,
    TableDataPlan,
    TableSchema,
    ValidationCheck,
)
from api_data_gen.services.cross_table_alignment_service import CrossTableAlignmentService
from api_data_gen.services.cross_table_validation_service import CrossTableValidationService
from api_data_gen.services.fixed_value_service import parse_fixed_values
from api_data_gen.services.field_match_alignment_service import FieldMatchAlignmentService
from api_data_gen.services.field_match_validation_service import FieldMatchValidationService
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService
from api_data_gen.services.record_validation_service import RecordValidationService

DEFAULT_MARKER = "[DEFAULT]"


class DataGenerationService:
    def __init__(
        self,
        planning_service,
        schema_repository,
        insert_render_service,
        sample_repository=None,
        cross_table_alignment_service: CrossTableAlignmentService | None = None,
        cross_table_validation_service: CrossTableValidationService | None = None,
        field_match_alignment_service: FieldMatchAlignmentService | None = None,
        field_match_validation_service: FieldMatchValidationService | None = None,
        local_field_rule_service: LocalFieldRuleService | None = None,
        record_validation_service: RecordValidationService | None = None,
        ai_data_analysis_service=None,
        ai_data_generation_service=None,
    ):
        self._planning_service = planning_service
        self._schema_repository = schema_repository
        self._insert_render_service = insert_render_service
        self._sample_repository = sample_repository
        self._cross_table_alignment_service = cross_table_alignment_service or CrossTableAlignmentService()
        self._cross_table_validation_service = cross_table_validation_service or CrossTableValidationService()
        self._field_match_alignment_service = field_match_alignment_service
        self._field_match_validation_service = field_match_validation_service
        self._local_field_rule_service = local_field_rule_service or LocalFieldRuleService()
        self._record_validation_service = record_validation_service or RecordValidationService()
        self._ai_data_analysis_service = ai_data_analysis_service
        self._ai_data_generation_service = ai_data_generation_service

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
    ) -> GenerationReport:
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
                title="default",
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

        for scenario_index, scenario in enumerate(scenarios, start=1):
            scenario_tag = _scenario_generation_tag(
                normalized_generation_tag,
                scenario,
                scenario_index,
                len(scenarios),
            )
            relevant_plans = _select_table_plans(draft.table_plans, scenario)
            ai_rows_by_table = self._generate_ai_rows(
                scenario=scenario,
                relevant_plans=relevant_plans,
                sample_limit=sample_limit,
                fixed_values=fixed_values,
                dependent_fixed_values=dependent_fixed_values,
                use_ai_data=use_ai_data,
            )
            scenario_tables: list[GeneratedTable] = []
            scenario_checks: list[ValidationCheck] = []

            for table_plan in relevant_plans:
                table_result, record_checks = self._generate_table(
                    table_plan=table_plan,
                    scenario=scenario,
                    generation_tag=scenario_tag,
                    fixed_value_map=fixed_value_map,
                    ai_rows=ai_rows_by_table.get(table_plan.table_name, []),
                )
                scenario_tables.append(table_result)
                scenario_checks.extend(record_checks)

            scenario_tables = self._cross_table_alignment_service.align(relevant_plans, scenario_tables)
            if self._field_match_alignment_service is not None:
                scenario_tables = self._field_match_alignment_service.align(relevant_plans, scenario_tables)

            rendered_tables: list[GeneratedTable] = []
            for generated_table in scenario_tables:
                rendered_table, record_checks = self._render_validated_table(
                    scenario=scenario,
                    generated_table=generated_table,
                )
                rendered_tables.append(rendered_table)
                scenario_checks.extend(record_checks)

            scenario_checks.extend(self._cross_table_validation_service.validate(relevant_plans, rendered_tables))
            if self._field_match_validation_service is not None:
                scenario_checks.extend(self._field_match_validation_service.validate(relevant_plans, rendered_tables))

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

    def _generate_ai_rows(
        self,
        scenario: ScenarioDraft,
        relevant_plans: list[TableDataPlan],
        sample_limit: int,
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        use_ai_data: bool,
    ) -> dict[str, list[dict[str, str]]]:
        if not use_ai_data or self._ai_data_generation_service is None or self._sample_repository is None:
            return {}

        schemas = {
            table_plan.table_name: self._schema_repository.get_table_schema(table_plan.table_name)
            for table_plan in relevant_plans
        }
        local_generated_columns = {
            table_name: self._local_field_rule_service.identify_local_fields(schema)
            for table_name, schema in schemas.items()
        }
        masked_samples = {
            table_name: self._local_field_rule_service.mask_rows(
                self._sample_repository.sample_rows(table_name, sample_limit),
                local_generated_columns[table_name],
            )
            for table_name in schemas
        }
        analysis_by_table: dict[str, str] = {}
        if self._ai_data_analysis_service is not None:
            for table_name, schema in schemas.items():
                try:
                    analysis_by_table[table_name] = self._ai_data_analysis_service.analyze(
                        table_name=table_name,
                        schema=schema,
                        sample_rows=masked_samples[table_name],
                        fixed_values=fixed_values,
                        dependent_fixed_values=dependent_fixed_values,
                    )
                except Exception:
                    analysis_by_table[table_name] = "{}"
        return self._ai_data_generation_service.generate(
            scenario=scenario,
            schemas=schemas,
            sample_rows_by_table=masked_samples,
            local_generated_columns=local_generated_columns,
            analysis_by_table=analysis_by_table,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
        )

    def _generate_table(
        self,
        table_plan: TableDataPlan,
        scenario: ScenarioDraft,
        generation_tag: str | None,
        fixed_value_map: dict[str, str],
        ai_rows: list[dict[str, str]],
    ) -> tuple[GeneratedTable, list[ValidationCheck]]:
        schema = self._schema_repository.get_table_schema(table_plan.table_name)
        rows = self.generate_table_rows(
            table_plan=table_plan,
            schema=schema,
            generation_tag=generation_tag,
            fixed_value_map=fixed_value_map,
            ai_rows=ai_rows,
        )
        return (
            GeneratedTable(
                table_name=table_plan.table_name,
                row_count=len(rows),
                rows=rows,
                insert_sql=[],
                scenario_id=scenario.id,
                scenario_title=scenario.title,
            ),
            [],
        )

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
            ),
            record_checks,
        )

    def generate_table_rows(
        self,
        table_plan: TableDataPlan,
        schema: TableSchema,
        generation_tag: str | None = None,
        fixed_value_map: dict[str, str] | None = None,
        ai_rows: list[dict[str, str]] | None = None,
    ) -> list[GeneratedRow]:
        normalized_generation_tag = _normalize_generation_tag(generation_tag)
        row_count = max(1, len(ai_rows or []) or table_plan.row_hint)
        column_plans = {plan.column_name: plan for plan in table_plan.column_plans}
        rows: list[GeneratedRow] = []

        for row_index in range(row_count):
            ai_row = (ai_rows or [])[row_index] if ai_rows and row_index < len(ai_rows) else {}
            values: dict[str, str | None] = {}
            for column in schema.columns:
                column_plan = column_plans.get(column.name)
                values[column.name] = self._materialize_value(
                    table_name=table_plan.table_name,
                    column=column,
                    column_plan=column_plan,
                    row_index=row_index,
                    generation_tag=normalized_generation_tag,
                    fixed_value_map=fixed_value_map or {},
                    ai_value=ai_row.get(column.name),
                )
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
    ) -> str | None:
        if column_plan is None:
            return _fallback_value(column, row_index)

        source = column_plan.source
        values = list(column_plan.suggested_values)
        fixed_value_map = fixed_value_map or {}

        if column.is_primary_key and source != "condition":
            return _generated_value(table_name, column, row_index, generation_tag)
        if source == "condition":
            return values[0] if values else _fallback_value(column, row_index)

        local_value = self._local_field_rule_service.generate_value(
            column=column,
            row_index=row_index,
            generation_tag=generation_tag,
            fixed_values=fixed_value_map,
        )
        if local_value is not None:
            return local_value

        normalized_ai_value = _normalize_ai_value(ai_value)
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
