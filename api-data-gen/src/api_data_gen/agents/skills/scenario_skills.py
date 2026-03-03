"""Scenario generation agent skills."""
from __future__ import annotations

from typing import Any

from api_data_gen.domain.models import InterfaceInfo, SqlInfo, TableColumn, TableSchema

from .decorator import skill

_skill_container: dict[str, Any] = {}


def init_skills(
    ai_scenario_service=None,
    ai_data_generation_service=None,
    ai_data_analysis_service=None,
    local_field_rule_service=None,
):
    global _skill_container
    _skill_container = {
        "ai_scenario_service": ai_scenario_service,
        "ai_data_analysis_service": ai_data_analysis_service,
        "local_field_rule_service": local_field_rule_service,
    }


def _build_table_schema(table_name: str, table_schema: dict) -> TableSchema:
    columns = [
        TableColumn(
            name=str(column["name"]),
            type=str(column.get("type", "varchar")),
            nullable=bool(column.get("nullable", True)),
            default_value=column.get("default_value"),
            comment=str(column.get("comment", "")),
            is_primary_key=bool(column.get("is_primary_key", False)),
            is_auto_primary_key=bool(column.get("is_auto_primary_key", False)),
            max_length=int(column.get("max_length", 0) or 0),
        )
        for column in table_schema.get("columns", [])
    ]
    return TableSchema(
        table_name=table_name,
        table_type=str(table_schema.get("table_type", "")),
        columns=columns,
        primary_keys=[str(value) for value in table_schema.get("primary_keys", [])],
    )


@skill(
    name="generate_scenarios_ai",
    description="Generate test scenarios with the configured AI model.",
    category="scenario",
)
def generate_scenarios_ai(
    requirement: str,
    interface_sql_info: list[dict],
    table_schemas: dict[str, dict],
    fixed_values: list[str] | None = None,
    dependent_fixed_values: list[str] | None = None,
) -> list[dict]:
    ai_scenario_service = _skill_container.get("ai_scenario_service")
    if ai_scenario_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    interface_infos = []
    for info in interface_sql_info:
        sql_infos = [
            SqlInfo(
                table_name=str(sql.get("table_name", "")),
                operation=str(sql.get("operation", "SELECT")),
                conditions=[str(value) for value in sql.get("conditions", [])],
            )
            for sql in info.get("sql_infos", [])
        ]
        interface_infos.append(
            InterfaceInfo(
                name=str(info.get("name", "")),
                path=str(info.get("path", "")),
                sql_infos=sql_infos,
            )
        )

    schemas = {
        table_name: _build_table_schema(table_name, schema_dict)
        for table_name, schema_dict in table_schemas.items()
    }

    scenarios = ai_scenario_service.generate(
        requirement_text=requirement,
        interface_infos=interface_infos,
        schemas=schemas,
        fixed_values=fixed_values,
        dependent_fixed_values=dependent_fixed_values,
    )

    return [
        {
            "id": scenario.id,
            "title": scenario.title,
            "api_name": scenario.api_name,
            "api_path": scenario.api_path,
            "objective": scenario.objective,
            "tables": scenario.tables,
            "table_requirements": scenario.table_requirements,
            "fixed_conditions": scenario.fixed_conditions,
            "request_inputs": scenario.request_inputs,
            "assertions": scenario.assertions,
            "generation_source": scenario.generation_source,
        }
        for scenario in scenarios
    ]


@skill(
    name="analyze_samples_ai",
    description="Analyze sample rows with the configured AI model.",
    category="analysis",
)
def analyze_samples_ai(
    table_name: str,
    sample_rows: list[dict],
    table_schema: dict | None = None,
) -> dict:
    ai_data_analysis_service = _skill_container.get("ai_data_analysis_service")
    if ai_data_analysis_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    schema = _build_table_schema(table_name, table_schema or {}) if table_schema else None
    analysis = ai_data_analysis_service.analyze(
        table_name=table_name,
        sample_rows=sample_rows,
        schema=schema,
    )
    return analysis if isinstance(analysis, dict) else {}


@skill(
    name="resolve_local_generators",
    description="Identify fields that should stay on local deterministic generators.",
    category="analysis",
)
def resolve_local_generators(table_schema: dict) -> list[str]:
    local_field_rule_service = _skill_container.get("local_field_rule_service")
    if local_field_rule_service is None:
        raise RuntimeError("Skills not initialized. Call init_skills() first.")

    schema = _build_table_schema(str(table_schema.get("table_name", "")), table_schema)
    return sorted(local_field_rule_service.identify_local_fields(schema))
