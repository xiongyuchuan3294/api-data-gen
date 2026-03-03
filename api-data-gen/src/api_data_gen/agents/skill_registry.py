from __future__ import annotations

from api_data_gen.domain.models import AgentToolSpec


_SKILLS = {
    "extract_interface_sql": AgentToolSpec(
        "extract_interface_sql",
        "Load interface trace, SQL chain, tables, and filter conditions.",
        input_hint="api_name, api_path",
        output_hint="InterfaceInfo",
    ),
    "load_table_schema": AgentToolSpec(
        "load_table_schema",
        "Load and normalize a target table schema.",
        input_hint="table_name",
        output_hint="TableSchema",
    ),
    "resolve_local_generators": AgentToolSpec(
        "resolve_local_generators",
        "Identify fields that should remain on local deterministic generators.",
        input_hint="TableSchema",
        output_hint="field_names",
    ),
    "build_table_plans_local": AgentToolSpec(
        "build_table_plans_local",
        "Build table-level data plans from SQL conditions, schema, and samples.",
        input_hint="requirement, InterfaceInfo, TableSchema, sample_rows",
        output_hint="TableDataPlan[]",
    ),
    "generate_scenarios_ai": AgentToolSpec(
        "generate_scenarios_ai",
        "Generate test scenarios with the configured AI model.",
        input_hint="requirement + interface/sql context + schemas",
        output_hint="ScenarioDraft[] JSON",
    ),
    "sample_table_data": AgentToolSpec(
        "sample_table_data",
        "Sample business rows for downstream reasoning and completion.",
        input_hint="table_name, limit",
        output_hint="rows[]",
    ),
    "analyze_samples_ai": AgentToolSpec(
        "analyze_samples_ai",
        "Analyze sample patterns with the configured AI model.",
        input_hint="table_name, sample_rows, table_schema",
        output_hint="analysis JSON",
    ),
    "generate_table_rows_local": AgentToolSpec(
        "generate_table_rows_local",
        "Generate rows with local deterministic rules.",
        input_hint="TableDataPlan, TableSchema",
        output_hint="GeneratedRow[]",
    ),
    "generate_table_rows_ai": AgentToolSpec(
        "generate_table_rows_ai",
        "Generate non-local fields with the configured AI model.",
        input_hint="prompt_spec + selected_scenario + local_context",
        output_hint="row JSON",
    ),
    "merge_and_validate_rows": AgentToolSpec(
        "merge_and_validate_rows",
        "Merge local/AI rows and run record-level checks.",
        input_hint="local_rows, ai_rows, TableSchema",
        output_hint="validated_rows, checks",
    ),
    "render_insert_sql": AgentToolSpec(
        "render_insert_sql",
        "Render rows into INSERT SQL.",
        input_hint="validated_rows, TableSchema",
        output_hint="INSERT SQL",
    ),
}


def skill_catalog(operation: str) -> list[AgentToolSpec]:
    base = [
        _SKILLS["extract_interface_sql"],
        _SKILLS["load_table_schema"],
        _SKILLS["resolve_local_generators"],
        _SKILLS["build_table_plans_local"],
    ]
    if operation == "draft":
        return base + [_SKILLS["generate_scenarios_ai"]]
    return base + [
        _SKILLS["generate_scenarios_ai"],
        _SKILLS["sample_table_data"],
        _SKILLS["analyze_samples_ai"],
        _SKILLS["generate_table_rows_local"],
        _SKILLS["generate_table_rows_ai"],
        _SKILLS["merge_and_validate_rows"],
        _SKILLS["render_insert_sql"],
    ]


def default_skill_order(operation: str, scenario_strategy: str, data_strategy: str) -> list[str]:
    selected = [
        "extract_interface_sql",
        "load_table_schema",
        "resolve_local_generators",
        "generate_scenarios_ai",
    ]
    if operation == "generate":
        selected.extend(
            [
                "sample_table_data",
                "generate_table_rows_local",
            ]
        )
        if data_strategy == "local_then_ai":
            selected.extend(
                [
                    "analyze_samples_ai",
                    "generate_table_rows_ai",
                ]
            )
        selected.extend(
            [
                "merge_and_validate_rows",
                "render_insert_sql",
            ]
        )
    return selected
