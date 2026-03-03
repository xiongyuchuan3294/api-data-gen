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
            f"浠诲姟绫诲瀷: {operation}\n"
            f"闇€姹傛憳瑕? {requirement.summary}\n"
            f"闇€姹傜害鏉? {requirement.constraints or ['[none]']}\n"
            f"鍏抽敭璇? {requirement.keywords or ['[none]']}\n"
            f"鍥哄畾鍊? {fixed_values or ['[none]']}\n"
            f"渚濊禆鍥哄畾鍊? {dependent_fixed_values or ['[none]']}\n"
            f"鎺ュ彛涓婁笅鏂?\n" + "\n".join(interface_lines) + "\n"
            f"琛ㄧ粨鏋勪笌鏈湴瑙勫垯:\n" + "\n".join(schema_lines) + "\n"
            f"鍙敤鎶€鑳?\n" + "\n".join(skill_lines) + "\n\n"
            "璇烽€夋嫨鍦烘櫙绛栫暐鍜岄€犳暟绛栫暐锛屽苟缁欏嚭寤鸿鎶€鑳介『搴忋€俓n"
            "鍙€?scenario_strategy: local, ai, agent_decides\n"
            "鍙€?data_strategy: local_only, local_then_ai, agent_decides\n"
            "涓ユ牸杈撳嚭 JSON 瀵硅薄锛屽瓧娈靛涓?\n"
            "{\n"
            '  "scenario_strategy": "local|ai|agent_decides",\n'
            '  "data_strategy": "local_only|local_then_ai|agent_decides",\n'
            '  "selected_skills": ["skill_a", "skill_b"],\n'
            '  "reasoning": ["reason 1", "reason 2"]\n'
            "}\n"
        )
        return AgentPromptSpec(
            name="route_generation_strategy",
            purpose="璁╁閮ㄦā鍨嬪熀浜庡綋鍓嶄笂涓嬫枃閫夋嫨鍦烘櫙绛栫暐銆佹暟鎹瓥鐣ュ拰 skill 椤哄簭銆?,
            system_prompt="浣犳槸涓€鍚嶆祴璇曟暟鎹紪鎺?agent銆備綘鍙兘鍩轰簬缁欏畾鐨勬湰鍦版妧鑳藉拰涓婁笅鏂囧仛绛栫暐鍐崇瓥锛屼笉鑳藉亣璁鹃澶栧伐鍏枫€?,
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

