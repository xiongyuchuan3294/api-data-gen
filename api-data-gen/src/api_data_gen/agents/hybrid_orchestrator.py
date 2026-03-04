from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from api_data_gen.agents.prompt_service import AgentPromptService
from api_data_gen.agents.router_service import AgentRouterService
from api_data_gen.agents.skill_registry import skill_catalog
from api_data_gen.domain.models import (
    AgentRunSummary,
    AgentSkillExecution,
    AgentTaskBundle,
    GenerationReport,
    InterfaceTarget,
    PlanningDraft,
)


class ExecutionMode(Enum):
    LOCAL = "local"
    AGENT_PROMPT = "agent_prompt"
    AGENT_AUTO = "agent_auto"


@dataclass
class ExecutionConfig:
    mode: ExecutionMode = ExecutionMode.AGENT_AUTO
    max_agent_turns: int = 10
    enable_mcp: bool = False
    mcp_port: int = 8000
    fallback_to_local: bool = True


class HybridAgentOrchestrator:
    def __init__(
        self,
        planning_service,
        interface_trace_service,
        schema_service,
        sample_repository,
        local_field_rule_service,
        ai_chat_client,
        agent_router_service=None,
        agent_prompt_service=None,
        react_executor=None,
    ):
        self._planning_service = planning_service
        self._interface_trace_service = interface_trace_service
        self._schema_service = schema_service
        self._sample_repository = sample_repository
        self._local_field_rule_service = local_field_rule_service
        self._ai_chat_client = ai_chat_client
        self._agent_router_service = agent_router_service or AgentRouterService()
        self._agent_prompt_service = agent_prompt_service or AgentPromptService()
        self._react_executor = react_executor

    def build_draft(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig | None = None,
        **kwargs,
    ) -> PlanningDraft:
        return self._build_draft_traditional(requirement_text, interfaces, **kwargs)

    def generate(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig | None = None,
        **kwargs,
    ) -> GenerationReport:
        return self._generate_traditional(requirement_text, interfaces, **kwargs)

    def _build_draft_traditional(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> PlanningDraft:
        local_draft = self._planning_service.build_draft(
            requirement_text,
            interfaces,
            sample_limit,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
            use_ai_scenarios=False,
        )
        interface_infos = [
            self._interface_trace_service.get_table_info(item.name, item.path)
            for item in interfaces
        ]
        schemas = self._schema_service.get_all_table_schemas(interface_infos)
        local_fields_by_table = {
            table_name: sorted(
                self._local_field_rule_service.identify_local_fields(schema)
            )
            for table_name, schema in schemas.items()
        }
        agent_bundle = AgentTaskBundle(
            operation="draft",
            tool_specs=skill_catalog("draft"),
            prompt_specs=[
                self._agent_router_service.build_prompt(
                    operation="draft",
                    requirement=local_draft.requirement,
                    interfaces=interfaces,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    local_fields_by_table=local_fields_by_table,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                ),
                self._agent_prompt_service.build_scenario_prompt(
                    requirement=local_draft.requirement,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    table_plans=local_draft.table_plans,
                    local_fields_by_table=local_fields_by_table,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                    local_reference_scenarios=local_draft.scenarios,
                ),
            ],
            interfaces=interfaces,
            interface_infos=interface_infos,
            schemas=schemas,
            table_plans=local_draft.table_plans,
            local_fields_by_table=local_fields_by_table,
            fixed_values=list(fixed_values or []),
            dependent_fixed_values=list(dependent_fixed_values or []),
            local_reference_scenarios=local_draft.scenarios,
        )
        return PlanningDraft(
            requirement=local_draft.requirement,
            scenarios=[],
            table_plans=local_draft.table_plans,
            agent_run=AgentRunSummary(
                decision=self._agent_router_service.default_decision(
                    operation="draft",
                    reason="Agent mode only prepares prompt specs and local context; scenario choice is delegated to the external model.",
                ),
                executed_skills=[
                    AgentSkillExecution(
                        "extract_interface_sql",
                        summary=f"{len(interface_infos)} interfaces",
                    ),
                    AgentSkillExecution(
                        "load_table_schema",
                        summary=f"{len(schemas)} tables",
                    ),
                    AgentSkillExecution(
                        "resolve_local_generators",
                        summary=", ".join(
                            f"{table}={len(fields)}"
                            for table, fields in local_fields_by_table.items()
                        ),
                    ),
                    AgentSkillExecution(
                        "build_table_plans_local",
                        summary=f"{len(local_draft.table_plans)} table plans",
                    ),
                ],
            ),
            agent_bundle=agent_bundle,
        )

    def _generate_traditional(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        generation_tag: str | None = None,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> GenerationReport:
        local_draft = self._planning_service.build_draft(
            requirement_text,
            interfaces,
            sample_limit,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
            use_ai_scenarios=False,
        )
        interface_infos = [
            self._interface_trace_service.get_table_info(item.name, item.path)
            for item in interfaces
        ]
        schemas = self._schema_service.get_all_table_schemas(interface_infos)
        local_fields_by_table = {
            table_name: sorted(
                self._local_field_rule_service.identify_local_fields(schema)
            )
            for table_name, schema in schemas.items()
        }
        sample_rows_by_table = {
            table_name: self._sample_repository.sample_rows(table_name, sample_limit)
            for table_name in schemas
        }
        agent_bundle = AgentTaskBundle(
            operation="generate",
            tool_specs=skill_catalog("generate"),
            prompt_specs=[
                self._agent_router_service.build_prompt(
                    operation="generate",
                    requirement=local_draft.requirement,
                    interfaces=interfaces,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    local_fields_by_table=local_fields_by_table,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                ),
                self._agent_prompt_service.build_scenario_prompt(
                    requirement=local_draft.requirement,
                    interface_infos=interface_infos,
                    schemas=schemas,
                    table_plans=local_draft.table_plans,
                    local_fields_by_table=local_fields_by_table,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                    local_reference_scenarios=local_draft.scenarios,
                ),
                self._agent_prompt_service.build_data_prompt(
                    requirement=local_draft.requirement,
                    schemas=schemas,
                    table_plans=local_draft.table_plans,
                    sample_rows_by_table=sample_rows_by_table,
                    local_fields_by_table=local_fields_by_table,
                    fixed_values=fixed_values,
                    dependent_fixed_values=dependent_fixed_values,
                ),
            ],
            interfaces=interfaces,
            interface_infos=interface_infos,
            schemas=schemas,
            table_plans=local_draft.table_plans,
            sample_rows_by_table=sample_rows_by_table,
            local_fields_by_table=local_fields_by_table,
            fixed_values=list(fixed_values or []),
            dependent_fixed_values=list(dependent_fixed_values or []),
            local_reference_scenarios=local_draft.scenarios,
        )
        return GenerationReport(
            requirement=local_draft.requirement,
            scenarios=[],
            table_plans=local_draft.table_plans,
            generated_tables=[],
            scenario_generations=[],
            validation_checks=[],
            generation_tag=generation_tag or "",
            agent_run=AgentRunSummary(
                decision=self._agent_router_service.default_decision(
                    operation="generate",
                    reason="Agent mode only prepares prompt specs and local methods; scenario and data generation are delegated to the external model.",
                ),
                executed_skills=[
                    AgentSkillExecution(
                        "extract_interface_sql",
                        summary=f"{len(interface_infos)} interfaces",
                    ),
                    AgentSkillExecution(
                        "load_table_schema",
                        summary=f"{len(schemas)} tables",
                    ),
                    AgentSkillExecution(
                        "resolve_local_generators",
                        summary=", ".join(
                            f"{table}={len(fields)}"
                            for table, fields in local_fields_by_table.items()
                        ),
                    ),
                    AgentSkillExecution(
                        "build_table_plans_local",
                        summary=f"{len(local_draft.table_plans)} table plans",
                    ),
                    AgentSkillExecution(
                        "sample_table_data",
                        summary=f"{len(sample_rows_by_table)} sampled tables",
                    ),
                ],
            ),
            agent_bundle=agent_bundle,
        )
