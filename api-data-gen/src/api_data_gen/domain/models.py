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
class SqlInfo:
    table_name: str
    conditions: list[str] = field(default_factory=list)


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
class PlanningDraft:
    requirement: RequirementSummary
    scenarios: list[ScenarioDraft] = field(default_factory=list)
    table_plans: list[TableDataPlan] = field(default_factory=list)
