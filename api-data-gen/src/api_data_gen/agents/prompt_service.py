from __future__ import annotations

from api_data_gen.domain.models import AgentPromptSpec, InterfaceInfo, RequirementSummary, ScenarioDraft, TableDataPlan, TableSchema


class AgentPromptService:
    def build_scenario_prompt(
        self,
        requirement: RequirementSummary,
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        table_plans: list[TableDataPlan],
        local_fields_by_table: dict[str, list[str]],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        local_reference_scenarios: list[ScenarioDraft] | None = None,
    ) -> AgentPromptSpec:
        sql_lines: list[str] = []
        for interface_info in interface_infos:
            sql_lines.append(f"- 接口 {interface_info.name} {interface_info.path}")
            for sql_info in interface_info.sql_infos:
                sql_lines.append(f"  - 表 {sql_info.table_name}; 条件 {sql_info.conditions or ['[none]']}")

        schema_lines = [
            f"- {table_name}: columns={', '.join(column.name for column in schema.columns)}; local_fields={local_fields_by_table.get(table_name, []) or ['[none]']}"
            for table_name, schema in schemas.items()
        ]
        plan_lines = [
            f"- {plan.table_name}: row_hint={plan.row_hint}; columns={[column.column_name + ':' + column.source for column in plan.column_plans]}"
            for plan in table_plans
        ]
        reference_lines = [
            f"- {scenario.id}: {scenario.title}; tables={scenario.tables or list(scenario.table_requirements)}"
            for scenario in (local_reference_scenarios or [])
        ]
        user_prompt = (
            f"需求摘要: {requirement.summary}\n"
            f"需求约束: {requirement.constraints or ['[none]']}\n"
            f"关键词: {requirement.keywords or ['[none]']}\n"
            f"固定值: {fixed_values or ['[none]']}\n"
            f"依赖固定值: {dependent_fixed_values or ['[none]']}\n"
            "接口和 SQL 链路:\n" + "\n".join(sql_lines) + "\n"
            "表结构与本地字段能力:\n" + "\n".join(schema_lines) + "\n"
            "表级造数计划:\n" + "\n".join(plan_lines) + "\n"
            "本地参考场景:\n" + ("\n".join(reference_lines) if reference_lines else "[none]") + "\n\n"
            "请直接生成测试场景。必须优先复用固定值和本地规则，不要要求额外工具。\n"
            "输出严格 JSON 数组。每个场景字段:\n"
            "{\n"
            '  "name": "场景名称",\n'
            '  "description": "场景目标",\n'
            '  "tableRequirements": {"table_name": "该表需要的数据要求"}\n'
            "}\n"
        )
        return AgentPromptSpec(
            name="generate_test_scenarios",
            purpose="让外部模型直接生成测试场景。",
            system_prompt="你是一名金融测试场景设计专家。你只能依据给定上下文和本地规则能力生成可执行场景。",
            user_prompt=user_prompt,
            expected_output='[{"name":"核心链路命中","description":"...","tableRequirements":{"table_a":"..."}}]',
        )

    def build_data_prompt(
        self,
        requirement: RequirementSummary,
        schemas: dict[str, TableSchema],
        table_plans: list[TableDataPlan],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_fields_by_table: dict[str, list[str]],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> AgentPromptSpec:
        schema_lines = [
            f"- {table_name}: columns={', '.join(column.name + ':' + column.type for column in schema.columns)}; local_fields={local_fields_by_table.get(table_name, []) or ['[none]']}"
            for table_name, schema in schemas.items()
        ]
        plan_lines = [
            f"- {plan.table_name}: row_hint={plan.row_hint}; column_sources={[column.column_name + ':' + column.source for column in plan.column_plans]}"
            for plan in table_plans
        ]
        sample_lines = [
            f"- {table_name}: {rows[:3]}"
            for table_name, rows in sample_rows_by_table.items()
        ]
        user_prompt = (
            f"需求摘要: {requirement.summary}\n"
            f"固定值: {fixed_values or ['[none]']}\n"
            f"依赖固定值: {dependent_fixed_values or ['[none]']}\n"
            "表结构:\n" + "\n".join(schema_lines) + "\n"
            "表级造数计划:\n" + "\n".join(plan_lines) + "\n"
            "样本数据:\n" + "\n".join(sample_lines) + "\n\n"
            "选中的测试场景 JSON 如下，请基于它直接生成测试数据:\n"
            "{{SELECTED_SCENARIO_JSON}}\n\n"
            "约束:\n"
            "1. 本地规则字段不要重新发明格式，只补齐非本地字段。\n"
            "2. 保持跨表字段一致性。\n"
            "3. 输出严格 JSON 数组，每个元素格式为 {\"table\": \"表名\", \"data\": [{...}] }。\n"
        )
        return AgentPromptSpec(
            name="generate_test_data",
            purpose="让外部模型直接生成测试数据。",
            system_prompt="你是一名数据库测试数据生成专家。你只能输出结构化 JSON，不要解释。",
            user_prompt=user_prompt,
            expected_output='[{"table":"table_a","data":[{"field":"value"}]}]',
        )
