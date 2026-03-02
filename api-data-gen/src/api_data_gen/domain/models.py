from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TraceRequest:
    trace_id: str
    url: str
    method: str
    request_body: str | None = None
    query_params: str | None = None
    status_code: int | None = None
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseOperation:
    trace_id: str
    sequence: int
    sql_text: str
    operation_type: str
    parameters: str | None = None
    result_rows: int | None = None
    query_result_data: str | None = None


@dataclass(frozen=True, slots=True)
class FieldMatchRelation:
    target_table: str
    target_field: str
    source_table: str
    source_field: str
    match_reason: str = ""


@dataclass(frozen=True, slots=True)
class SqlInfo:
    table_name: str
    conditions: list[str] = field(default_factory=list)
    operation: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    name: str
    path: str
    sql_infos: list[SqlInfo] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TableColumn:
    name: str
    type: str
    nullable: bool
    default_value: str | None
    comment: str
    is_primary_key: bool
    is_auto_primary_key: bool
    max_length: int


@dataclass(frozen=True, slots=True)
class TableSchema:
    table_name: str
    table_type: str
    columns: list[TableColumn] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InterfaceTarget:
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class RequirementSummary:
    summary: str
    constraints: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScenarioDraft:
    id: str
    title: str
    api_name: str
    api_path: str
    objective: str
    request_inputs: dict[str, str] = field(default_factory=dict)
    fixed_conditions: list[str] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    table_requirements: dict[str, str] = field(default_factory=dict)
    generation_source: str = "local"


@dataclass(frozen=True, slots=True)
class ColumnPlan:
    column_name: str
    source: str
    required: bool
    suggested_values: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class TableDataPlan:
    table_name: str
    primary_keys: list[str] = field(default_factory=list)
    fixed_conditions: list[str] = field(default_factory=list)
    row_hint: int = 1
    column_plans: list[ColumnPlan] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentRoutingDecision:
    mode: str = "local"
    operation: str = ""
    scenario_strategy: str = "local"
    data_strategy: str = "local_only"
    selected_skills: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentSkillExecution:
    skill_name: str
    status: str = "completed"
    summary: str = ""


@dataclass(frozen=True, slots=True)
class AgentToolSpec:
    name: str
    description: str
    input_hint: str = ""
    output_hint: str = ""


@dataclass(frozen=True, slots=True)
class AgentPromptSpec:
    name: str
    purpose: str
    system_prompt: str
    user_prompt: str
    expected_output: str = ""


@dataclass(frozen=True, slots=True)
class AgentTaskBundle:
    operation: str
    tool_specs: list[AgentToolSpec] = field(default_factory=list)
    prompt_specs: list[AgentPromptSpec] = field(default_factory=list)
    interfaces: list[InterfaceTarget] = field(default_factory=list)
    interface_infos: list[InterfaceInfo] = field(default_factory=list)
    schemas: dict[str, TableSchema] = field(default_factory=dict)
    table_plans: list["TableDataPlan"] = field(default_factory=list)
    sample_rows_by_table: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    local_fields_by_table: dict[str, list[str]] = field(default_factory=dict)
    fixed_values: list[str] = field(default_factory=list)
    dependent_fixed_values: list[str] = field(default_factory=list)
    local_reference_scenarios: list["ScenarioDraft"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentRunSummary:
    decision: AgentRoutingDecision | None = None
    executed_skills: list[AgentSkillExecution] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlanningDraft:
    requirement: RequirementSummary
    scenarios: list[ScenarioDraft] = field(default_factory=list)
    table_plans: list[TableDataPlan] = field(default_factory=list)
    agent_run: AgentRunSummary | None = None
    agent_bundle: AgentTaskBundle | None = None


@dataclass(frozen=True, slots=True)
class GeneratedRow:
    values: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeneratedTable:
    table_name: str
    row_count: int = 0
    rows: list[GeneratedRow] = field(default_factory=list)
    insert_sql: list[str] = field(default_factory=list)
    scenario_id: str = ""
    scenario_title: str = ""


@dataclass(frozen=True, slots=True)
class ScenarioGeneration:
    scenario_id: str
    scenario_title: str
    generated_tables: list[GeneratedTable] = field(default_factory=list)
    validation_checks: list["ValidationCheck"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GenerationReport:
    requirement: RequirementSummary
    scenarios: list[ScenarioDraft] = field(default_factory=list)
    table_plans: list[TableDataPlan] = field(default_factory=list)
    generated_tables: list[GeneratedTable] = field(default_factory=list)
    scenario_generations: list[ScenarioGeneration] = field(default_factory=list)
    validation_checks: list["ValidationCheck"] = field(default_factory=list)
    generation_tag: str = ""
    apply_result: "ApplyResult | None" = None
    agent_run: AgentRunSummary | None = None
    agent_bundle: AgentTaskBundle | None = None


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ApplyResult:
    applied: bool
    forced: bool = False
    statement_count: int = 0
    schemas: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
