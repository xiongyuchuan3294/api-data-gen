from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from api_data_gen.agents.prompt_service import AgentPromptService
from api_data_gen.agents.router_service import AgentRouterService
from api_data_gen.agents.skill_registry import skill_catalog
from api_data_gen.agents.executor import ReActExecutor
from api_data_gen.domain.models import (
    AgentRunSummary,
    AgentSkillExecution,
    AgentTaskBundle,
    GenerationReport,
    InterfaceTarget,
    PlanningDraft,
)


class ExecutionMode(Enum):
    """执行模式"""

    LOCAL = "local"  # 纯本地规则执行
    DIRECT = "direct"  # 直接调用 AI，不经过 Agent
    AGENT_PROMPT = "agent_prompt"  # 准备提示词，外部模型执行
    AGENT_AUTO = "agent_auto"  # Agent 自主执行（新增）


@dataclass
class ExecutionConfig:
    """执行配置"""

    mode: ExecutionMode = ExecutionMode.AGENT_PROMPT
    max_agent_turns: int = 10
    enable_mcp: bool = False
    mcp_port: int = 8000
    fallback_to_local: bool = True  # Agent 失败时回退到本地


class HybridAgentOrchestrator:
    """
    混合模式 Agent 编排器

    支持多种执行模式:
    - LOCAL: 保持原有固定流程
    - DIRECT: 在特定节点直接调用 AI
    - AGENT_PROMPT: 返回提示词供外部执行（当前实现）
    - AGENT_AUTO: Agent 自主编排执行（新增）
    """

    def __init__(
        self,
        planning_service,
        interface_trace_service,
        schema_service,
        sample_repository,
        local_field_rule_service,
        ai_chat_client,
        # 原有服务
        agent_router_service=None,
        agent_prompt_service=None,
        # Agent 执行器（新增）
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
        """构建场景和数据草稿"""
        config = config or ExecutionConfig()

        if config.mode == ExecutionMode.AGENT_AUTO:
            return self._build_draft_agent(
                requirement_text, interfaces, config, **kwargs
            )
        else:
            # 保持原有逻辑
            return self._build_draft_traditional(
                requirement_text,
                interfaces,
                **kwargs,
            )

    def generate(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig | None = None,
        **kwargs,
    ) -> GenerationReport:
        """生成测试数据"""
        config = config or ExecutionConfig()

        if config.mode == ExecutionMode.AGENT_AUTO:
            return self._generate_agent(
                requirement_text, interfaces, config, **kwargs
            )
        else:
            return self._generate_traditional(
                requirement_text,
                interfaces,
                **kwargs,
            )

    # ========== Agent Auto 模式实现 ==========

    def _build_draft_agent(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig,
        **kwargs,
    ) -> PlanningDraft:
        """Agent 自主模式构建草稿"""

        if self._react_executor is None:
            raise RuntimeError(
                "ReAct executor not initialized. Cannot use AGENT_AUTO mode."
            )

        # 1. 准备上下文
        context = self._prepare_context(requirement_text, interfaces, **kwargs)

        # 2. 构建 Agent 任务
        task = """请分析业务需求和接口信息，设计合适的测试场景。

你需要:
1. 理解接口的 SQL 链路和数据依赖
2. 设计覆盖核心场景的测试用例
3. 考虑边界情况和异常场景

请直接调用工具完成分析和建议。"""

        # 3. 执行 Agent
        result = self._react_executor.execute(
            task=task,
            context=context,
            max_turns=config.max_agent_turns,
        )

        if not result.success and config.fallback_to_local:
            # 回退到本地模式
            return self._build_draft_traditional(
                requirement_text, interfaces, **kwargs
            )

        # 4. 解析结果
        return self._parse_agent_result_draft(result, context)

    def _generate_agent(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig,
        **kwargs,
    ) -> GenerationReport:
        """Agent 自主模式生成数据"""

        if self._react_executor is None:
            raise RuntimeError(
                "ReAct executor not initialized. Cannot use AGENT_AUTO mode."
            )

        # 1. 准备上下文
        context = self._prepare_context(requirement_text, interfaces, **kwargs)

        # 2. 添加数据生成相关上下文
        context["data_requirements"] = self._prepare_data_requirements(interfaces)

        # 3. 构建 Agent 任务
        task = """请基于以下业务需求和接口信息，完成测试数据生成。

你需要:
1. 分析表结构和数据依赖
2. 设计测试场景
3. 生成符合业务规则的测试数据
4. 验证数据质量

请直接调用工具完成数据生成。"""

        # 4. 执行 Agent
        result = self._react_executor.execute(
            task=task,
            context=context,
            max_turns=config.max_agent_turns,
        )

        if not result.success and config.fallback_to_local:
            return self._generate_traditional(
                requirement_text, interfaces, **kwargs
            )

        return self._parse_agent_result_generate(result, context)

    def _prepare_context(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        **kwargs,
    ) -> dict:
        """准备 Agent 上下文"""

        # 收集接口信息
        interface_infos = [
            self._interface_trace_service.get_table_info(item.name, item.path)
            for item in interfaces
        ]

        # 收集表结构
        schemas = self._schema_service.get_all_table_schemas(interface_infos)

        # 收集本地字段规则
        local_fields_by_table = {}
        for table_name, schema in schemas.items():
            local_fields_by_table[table_name] = sorted(
                self._local_field_rule_service.identify_local_fields(schema)
            )

        return {
            "requirement": requirement_text,
            "interfaces": [
                {"name": i.name, "path": i.path}
                for i in interfaces
            ],
            "interface_infos": [
                {
                    "name": info.name,
                    "path": info.path,
                    "sql_infos": [
                        {
                            "table_name": sql.table_name,
                            "operation": sql.operation,
                            "conditions": sql.conditions,
                        }
                        for sql in info.sql_infos
                    ],
                }
                for info in interface_infos
            ],
            "schemas": {
                name: {
                    "table_name": schema.table_name,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "nullable": c.nullable,
                            "is_primary_key": c.is_primary_key,
                            "comment": c.comment,
                        }
                        for c in schema.columns
                    ],
                    "primary_keys": schema.primary_keys,
                }
                for name, schema in schemas.items()
            },
            "local_fields": local_fields_by_table,
            "available_tools": [
                tool["name"]
                for tool in self._react_executor.get_available_tools()
            ]
            if self._react_executor
            else [],
        }

    def _prepare_data_requirements(self, interfaces: list[InterfaceTarget]) -> dict:
        """准备数据生成需求"""
        # 可以从 PlanningService 获取已有的数据计划作为参考
        return {}

    def _parse_agent_result_draft(
        self, result, context: dict
    ) -> PlanningDraft:
        """解析 Agent 执行结果（草稿）"""
        import json
        from api_data_gen.domain.models import RequirementSummary, ScenarioDraft

        # 从上下文中提取基本信息
        requirement = RequirementSummary(
            summary=context.get("requirement", ""),
            constraints=[],
            keywords=[],
        )

        # 从 Agent 结果中提取场景
        scenarios = []
        table_plans = []

        # 1. 尝试从 final_output 解析
        if result.final_output:
            scenarios, table_plans = self._extract_scenarios_from_output(
                result.final_output, context
            )

        # 2. 如果 final_output 没有场景，尝试从 tool_calls 解析
        if not scenarios:
            scenarios, table_plans = self._extract_scenarios_from_tool_calls(
                result.tool_calls, context
            )

        # 构建执行摘要
        executed_skills = [
            AgentSkillExecution(
                skill_name=tc.tool_name,
                summary=f"status={tc.status.value}, result={str(tc.result)[:50] if tc.result else tc.error}"
            )
            for tc in result.tool_calls
        ]

        # 返回 PlanningDraft
        return PlanningDraft(
            requirement=requirement,
            scenarios=scenarios,
            table_plans=table_plans,
            agent_run=AgentRunSummary(
                decision=None,
                executed_skills=executed_skills,
            ),
        )

    def _parse_agent_result_generate(
        self, result, context: dict
    ) -> GenerationReport:
        """解析 Agent 执行结果（生成）"""
        import json
        from api_data_gen.domain.models import RequirementSummary, GeneratedTable, ScenarioGeneration

        requirement = RequirementSummary(
            summary=context.get("requirement", ""),
            constraints=[],
            keywords=[],
        )

        # 从 Agent 结果中提取生成的数据
        generated_tables = []
        scenario_generations = []

        # 尝试从 final_output 解析
        if result.final_output:
            generated_tables, scenario_generations = self._extract_generated_data(
                result.final_output, context
            )

        # 如果 final_output 没有数据，尝试从 tool_calls 解析
        if not generated_tables:
            generated_tables, scenario_generations = self._extract_generated_data_from_tools(
                result.tool_calls, context
            )

        # 构建执行摘要
        executed_skills = [
            AgentSkillExecution(
                skill_name=tc.tool_name,
                summary=f"status={tc.status.value}, result={str(tc.result)[:50] if tc.result else tc.error}"
            )
            for tc in result.tool_calls
        ]

        return GenerationReport(
            requirement=requirement,
            scenarios=[],
            table_plans=[],
            generated_tables=generated_tables,
            scenario_generations=scenario_generations,
            validation_checks=[],
            generation_tag="agent_auto",
            agent_run=AgentRunSummary(
                decision=None,
                executed_skills=executed_skills,
            ),
        )

    def _extract_scenarios_from_output(
        self, output: str, context: dict
    ) -> tuple[list, list]:
        """从输出中提取场景"""
        import json
        scenarios = []

        # 尝试解析 JSON
        try:
            # 查找 JSON 数组
            import re
            json_match = re.search(r'\[[\s\S]*\]', output)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    for i, item in enumerate(data):
                        if isinstance(item, dict):
                            scenarios.append(ScenarioDraft(
                                id=item.get("id", f"agent_scenario_{i}"),
                                title=item.get("title", item.get("name", f"Scenario {i}")),
                                api_name=item.get("api_name", "unknown"),
                                api_path=item.get("api_path", ""),
                                objective=item.get("description", item.get("objective", "")),
                                request_inputs=item.get("request_inputs", {}),
                                fixed_conditions=item.get("fixed_conditions", []),
                                assertions=item.get("assertions", []),
                                tables=item.get("tables", []),
                                table_requirements=item.get("table_requirements", {}),
                            ))
        except (json.JSONDecodeError, Exception):
            pass

        return scenarios, []

    def _extract_scenarios_from_tool_calls(
        self, tool_calls: list, context: dict
    ) -> tuple[list, list]:
        """从工具调用中提取场景"""
        scenarios = []

        for tc in tool_calls:
            if tc.tool_name == "generate_scenarios_ai" and tc.result:
                try:
                    if isinstance(tc.result, list):
                        for i, item in enumerate(tc.result):
                            if isinstance(item, dict):
                                scenarios.append(ScenarioDraft(
                                    id=item.get("id", f"agent_scenario_{i}"),
                                    title=item.get("title", f"Scenario {i}"),
                                    api_name=item.get("api_name", "unknown"),
                                    api_path=item.get("api_path", ""),
                                    objective=item.get("objective", ""),
                                    request_inputs=item.get("request_inputs", {}),
                                    fixed_conditions=item.get("fixed_conditions", []),
                                    assertions=item.get("assertions", []),
                                    tables=item.get("tables", []),
                                    table_requirements=item.get("table_requirements", {}),
                                ))
                except Exception:
                    pass

        return scenarios, []

    def _extract_generated_data(
        self, output: str, context: dict
    ) -> tuple[list, list]:
        """从输出中提取生成的数据"""
        import json
        from api_data_gen.domain.models import GeneratedTable, ScenarioGeneration

        generated_tables = []

        try:
            import re
            # 尝试查找 JSON 对象
            json_match = re.search(r'\{[\s\S]*\}', output)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    # 解析 generated_tables
                    tables_data = data.get("generated_tables", data.get("tables", []))
                    if isinstance(tables_data, list):
                        for table_data in tables_data:
                            if isinstance(table_data, dict):
                                generated_tables.append(GeneratedTable(
                                    table_name=table_data.get("table_name", "unknown"),
                                    rows=table_data.get("rows", []),
                                    sqls=table_data.get("sqls", []),
                                ))
        except (json.JSONDecodeError, Exception):
            pass

        return generated_tables, []

    def _extract_generated_data_from_tools(
        self, tool_calls: list, context: dict
    ) -> tuple[list, list]:
        """从工具调用中提取生成的数据"""
        import json
        from api_data_gen.domain.models import GeneratedTable, ScenarioGeneration

        generated_tables = []

        for tc in tool_calls:
            if tc.tool_name in ("generate_table_rows_ai", "render_insert_sql") and tc.result:
                try:
                    if isinstance(tc.result, list):
                        # 尝试确定表名
                        table_name = "unknown"
                        sqls = []

                        if tc.tool_name == "render_insert_sql":
                            sqls = tc.result

                        generated_tables.append(GeneratedTable(
                            table_name=table_name,
                            rows=tc.result if tc.tool_name == "generate_table_rows_ai" else [],
                            sqls=sqls,
                        ))
                except Exception:
                    pass

        return generated_tables, []

    # ========== 传统模式（保持原有逻辑）==========

    def _build_draft_traditional(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> PlanningDraft:
        """传统模式构建草稿"""
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
                        "load_table_schema", summary=f"{len(schemas)} tables"
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
        """传统模式生成数据"""
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
                        "load_table_schema", summary=f"{len(schemas)} tables"
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
