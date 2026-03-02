from __future__ import annotations

from api_data_gen.agents.skill_registry import default_skill_order, skill_catalog
from api_data_gen.domain.models import AgentPromptSpec, AgentRoutingDecision, InterfaceInfo, InterfaceTarget, RequirementSummary, TableSchema


class AgentRouterService:
    def build_prompt(
        self,
        operation: str,
        requirement: RequirementSummary,
        interfaces: list[InterfaceTarget],
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        local_fields_by_table: dict[str, list[str]],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> AgentPromptSpec:
        interface_lines = [
            f"- {target.name} {target.path}: {', '.join(sql.table_name for sql in info.sql_infos) or '[no tables]'}"
            for target, info in zip(interfaces, interface_infos)
        ]
        schema_lines = [
            f"- {table_name}: {len(schema.columns)} columns, pk={','.join(schema.primary_keys) or '[none]'}, local_fields={','.join(local_fields_by_table.get(table_name, [])) or '[none]'}"
            for table_name, schema in schemas.items()
        ]
        skill_lines = [
            f"- {skill.name}: {skill.description}"
            for skill in skill_catalog(operation)
        ]
        user_prompt = (
            f"任务类型: {operation}\n"
            f"需求摘要: {requirement.summary}\n"
            f"需求约束: {requirement.constraints or ['[none]']}\n"
            f"关键词: {requirement.keywords or ['[none]']}\n"
            f"固定值: {fixed_values or ['[none]']}\n"
            f"依赖固定值: {dependent_fixed_values or ['[none]']}\n"
            f"接口上下文:\n" + "\n".join(interface_lines) + "\n"
            f"表结构与本地规则:\n" + "\n".join(schema_lines) + "\n"
            f"可用技能:\n" + "\n".join(skill_lines) + "\n\n"
            "请选择场景策略和造数策略，并给出建议技能顺序。\n"
            "可选 scenario_strategy: local, ai, agent_decides\n"
            "可选 data_strategy: local_only, local_then_ai, agent_decides\n"
            "严格输出 JSON 对象，字段如下:\n"
            "{\n"
            '  "scenario_strategy": "local|ai|agent_decides",\n'
            '  "data_strategy": "local_only|local_then_ai|agent_decides",\n'
            '  "selected_skills": ["skill_a", "skill_b"],\n'
            '  "reasoning": ["reason 1", "reason 2"]\n'
            "}\n"
        )
        return AgentPromptSpec(
            name="route_generation_strategy",
            purpose="让外部模型基于当前上下文选择场景策略、数据策略和 skill 顺序。",
            system_prompt="你是一名测试数据编排 agent。你只能基于给定的本地技能和上下文做策略决策，不能假设额外工具。",
            user_prompt=user_prompt,
            expected_output='{"scenario_strategy":"ai","data_strategy":"local_then_ai","selected_skills":["..."],"reasoning":["..."]}',
        )

    @staticmethod
    def default_decision(operation: str, reason: str) -> AgentRoutingDecision:
        return AgentRoutingDecision(
            mode="agent_prompt",
            operation=operation,
            scenario_strategy="agent_decides",
            data_strategy="agent_decides" if operation == "generate" else "local_only",
            selected_skills=default_skill_order(operation, "local", "local_only"),
            reasoning=[reason],
        )
