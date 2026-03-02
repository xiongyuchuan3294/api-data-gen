from __future__ import annotations

from api_data_gen.domain.models import AgentToolSpec


_SKILLS = {
    "extract_interface_sql": AgentToolSpec(
        "extract_interface_sql",
        "提取接口 trace、SQL、表和过滤条件。",
        input_hint="api_name, api_path",
        output_hint="InterfaceInfo",
    ),
    "load_table_schema": AgentToolSpec(
        "load_table_schema",
        "加载并标准化目标表 schema。",
        input_hint="table_name",
        output_hint="TableSchema",
    ),
    "resolve_local_generators": AgentToolSpec(
        "resolve_local_generators",
        "识别适合本地规则生成的字段。",
        input_hint="TableSchema",
        output_hint="field_names",
    ),
    "build_table_plans_local": AgentToolSpec(
        "build_table_plans_local",
        "根据 SQL 条件、schema 和样本构建表级造数计划。",
        input_hint="requirement, InterfaceInfo, TableSchema, sample_rows",
        output_hint="TableDataPlan[]",
    ),
    "generate_scenarios_local": AgentToolSpec(
        "generate_scenarios_local",
        "基于接口行为和规则生成本地参考场景。",
        input_hint="requirement, InterfaceInfo, TableSchema",
        output_hint="ScenarioDraft[]",
    ),
    "generate_scenarios_ai": AgentToolSpec(
        "generate_scenarios_ai",
        "由外部模型直接生成测试场景。",
        input_hint="prompt_spec + local_context",
        output_hint="ScenarioDraft[] JSON",
    ),
    "sample_table_data": AgentToolSpec(
        "sample_table_data",
        "采样业务表数据供后续推理和补数使用。",
        input_hint="table_name, limit",
        output_hint="rows[]",
    ),
    "analyze_samples_ai": AgentToolSpec(
        "analyze_samples_ai",
        "由外部模型分析样本特征与字段模式。",
        input_hint="prompt_spec + sample_rows",
        output_hint="analysis JSON",
    ),
    "generate_table_rows_local": AgentToolSpec(
        "generate_table_rows_local",
        "优先使用本地规则和样本生成记录。",
        input_hint="TableDataPlan, TableSchema",
        output_hint="GeneratedRow[]",
    ),
    "generate_table_rows_ai": AgentToolSpec(
        "generate_table_rows_ai",
        "由外部模型补齐非本地字段。",
        input_hint="prompt_spec + selected_scenario + local_context",
        output_hint="row JSON",
    ),
    "merge_and_validate_rows": AgentToolSpec(
        "merge_and_validate_rows",
        "合并本地/AI结果并执行记录级校验。",
        input_hint="local_rows, ai_rows, TableSchema",
        output_hint="validated_rows, checks",
    ),
    "render_insert_sql": AgentToolSpec(
        "render_insert_sql",
        "把记录渲染为 INSERT SQL。",
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
        return base + [
            _SKILLS["generate_scenarios_local"],
            _SKILLS["generate_scenarios_ai"],
        ]
    return base + [
        _SKILLS["generate_scenarios_local"],
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
        "generate_scenarios_ai" if scenario_strategy == "ai" else "generate_scenarios_local",
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
