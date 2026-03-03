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
    """鎵ц妯″紡"""

    LOCAL = "local"  # 绾湰鍦拌鍒欐墽琛?
    DIRECT = "direct"  # 鐩存帴璋冪敤 AI锛屼笉缁忚繃 Agent
    AGENT_PROMPT = "agent_prompt"  # 鍑嗗鎻愮ず璇嶏紝澶栭儴妯″瀷鎵ц
    AGENT_AUTO = "agent_auto"  # Agent 鑷富鎵ц锛堟柊澧烇級


@dataclass
class ExecutionConfig:
    """鎵ц閰嶇疆"""

    mode: ExecutionMode = ExecutionMode.AGENT_PROMPT
    max_agent_turns: int = 10
    enable_mcp: bool = False
    mcp_port: int = 8000
    fallback_to_local: bool = True  # Agent 澶辫触鏃跺洖閫€鍒版湰鍦?


class HybridAgentOrchestrator:
    """
    娣峰悎妯″紡 Agent 缂栨帓鍣?

    鏀寔澶氱鎵ц妯″紡:
    - LOCAL: 淇濇寔鍘熸湁鍥哄畾娴佺▼
    - DIRECT: 鍦ㄧ壒瀹氳妭鐐圭洿鎺ヨ皟鐢?AI
    - AGENT_PROMPT: 杩斿洖鎻愮ず璇嶄緵澶栭儴鎵ц锛堝綋鍓嶅疄鐜帮級
    - AGENT_AUTO: Agent 鑷富缂栨帓鎵ц锛堟柊澧烇級
    """

    def __init__(
        self,
        planning_service,
        interface_trace_service,
        schema_service,
        sample_repository,
        local_field_rule_service,
        ai_chat_client,
        # 鍘熸湁鏈嶅姟
        agent_router_service=None,
        agent_prompt_service=None,
        # Agent 鎵ц鍣紙鏂板锛?
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
        """鏋勫缓鍦烘櫙鍜屾暟鎹崏绋?""
        config = config or ExecutionConfig()

        if config.mode == ExecutionMode.AGENT_AUTO:
            return self._build_draft_agent(
                requirement_text, interfaces, config, **kwargs
            )
        else:
            # 淇濇寔鍘熸湁閫昏緫
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
        """鐢熸垚娴嬭瘯鏁版嵁"""
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

    # ========== Agent Auto 妯″紡瀹炵幇 ==========

    def _build_draft_agent(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig,
        **kwargs,
    ) -> PlanningDraft:
        """Agent 鑷富妯″紡鏋勫缓鑽夌"""

        if self._react_executor is None:
            raise RuntimeError(
                "ReAct executor not initialized. Cannot use AGENT_AUTO mode."
            )

        # 1. 鍑嗗涓婁笅鏂?
        context = self._prepare_context(requirement_text, interfaces, **kwargs)

        # 2. 鏋勫缓 Agent 浠诲姟
        task = """璇峰垎鏋愪笟鍔￠渶姹傚拰鎺ュ彛淇℃伅锛岃璁″悎閫傜殑娴嬭瘯鍦烘櫙銆?

浣犻渶瑕?
1. 鐞嗚В鎺ュ彛鐨?SQL 閾捐矾鍜屾暟鎹緷璧?
2. 璁捐瑕嗙洊鏍稿績鍦烘櫙鐨勬祴璇曠敤渚?
3. 鑰冭檻杈圭晫鎯呭喌鍜屽紓甯稿満鏅?

璇风洿鎺ヨ皟鐢ㄥ伐鍏峰畬鎴愬垎鏋愬拰寤鸿銆?""

        # 3. 鎵ц Agent
        result = self._react_executor.execute(
            task=task,
            context=context,
            max_turns=config.max_agent_turns,
        )

        if not result.success and config.fallback_to_local:
            # 鍥為€€鍒版湰鍦版ā寮?
            return self._build_draft_traditional(
                requirement_text, interfaces, **kwargs
            )

        # 4. 瑙ｆ瀽缁撴灉
        return self._parse_agent_result_draft(result, context)

    def _generate_agent(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        config: ExecutionConfig,
        **kwargs,
    ) -> GenerationReport:
        """Agent 鑷富妯″紡鐢熸垚鏁版嵁"""

        if self._react_executor is None:
            raise RuntimeError(
                "ReAct executor not initialized. Cannot use AGENT_AUTO mode."
            )

        # 1. 鍑嗗涓婁笅鏂?
        context = self._prepare_context(requirement_text, interfaces, **kwargs)

        # 2. 娣诲姞鏁版嵁鐢熸垚鐩稿叧涓婁笅鏂?
        context["data_requirements"] = self._prepare_data_requirements(interfaces)

        # 鑾峰彇琛ㄥ悕鍒楄〃渚涗换鍔′娇鐢?
        table_names = [info["name"] for info in context.get("data_requirements", [])]

        # 3. 鏋勫缓鍒嗛樁娈?Agent 浠诲姟
        # 鍙傝€?Java 椤圭洰 TestMultiAPIDataGen.java 鐨勬彁绀鸿瘝璁捐
        task = f"""浣犳槸涓€浣嶈祫娣遍噾铻嶅弽娲楅挶娴嬭瘯鏋舵瀯甯堬紝绮鹃€氭暟鎹簱璁捐鍜孉PI娴嬭瘯鐨勪笟鍔°€?

## 涓氬姟闇€姹?
{requirement_text}

## 涓氬姟绾︽潫:
1. 鍚屼竴涓鎴锋湁棰勮蹇呴』鏈変氦鏄擄紙1:N锛?
2. 鍚屼竴涓鎴锋湁妗堜緥蹇呴』鏈夐璀︼紙1:N锛?

## 浠诲姟锛氬垎闃舵瀹屾垚娴嬭瘯鏁版嵁鐢熸垚

### 闃舵1锛氱敓鎴愭祴璇曞満鏅紙蹇呴』鎵ц锛?
璇蜂娇鐢?build_table_plans_local 宸ュ叿璁捐娴嬭瘯鍦烘櫙锛岀敓鎴?-5涓狿0绾у埆鐨勬祴璇曞満鏅€?
姣忎釜鍦烘櫙闇€瑕佸寘鍚細
- name: 鍦烘櫙鍚嶇О
- description: 鍦烘櫙鎻忚堪
- tableRequirements: 鏁版嵁闇€姹傛弿杩帮紝濡?"aml_f_tidb_model_result": "鐢熸垚2020-12-27鐨勯璀﹁褰?

### 闃舵2锛氶噰鏍峰拰鍒嗘瀽鏁版嵁鐗瑰緛锛堝繀椤绘墽琛岋級
璇蜂娇鐢?sample_table_data 宸ュ叿閲囨牱涓氬姟鏁版嵁锛岀劧鍚庡垎鏋愭瘡涓〃鐨勬暟鎹壒寰併€?
璇蜂娇鐢ㄤ互涓嬫牸寮忚緭鍑哄垎鏋愮粨鏋滐細
{{
  "data_analysis": [
    {{"table": "琛ㄥ悕", "analysis": "鍒嗘瀽缁撴灉鎻忚堪"}}
  ]
}}

### 闃舵3锛氱敓鎴愭祴璇曟暟鎹紙蹇呴』鎵ц锛?
鍩轰簬闃舵1鐨勫満鏅拰闃舵2鐨勬暟鎹垎鏋愶紝浣跨敤 generate_table_rows_local 宸ュ叿鐢熸垚娴嬭瘯鏁版嵁銆?

### 闃舵4锛氭覆鏌揝QL锛堝繀椤绘墽琛岋級
浣跨敤 render_insert_sql 宸ュ叿灏嗙敓鎴愮殑鏁版嵁娓叉煋涓?INSERT SQL 璇彞銆?
璋冪敤鏂瑰紡: render_insert_sql(table_name="琛ㄥ悕", rows=[{{"瀛楁鍚?: "鍊?}}])

## 杈撳嚭鏍煎紡瑕佹眰
鏈€缁堝繀椤昏繑鍥炰互涓嬫牸寮忕殑缁撴灉锛?
```json
{{
  "scenarios": [
    {{"name": "鍦烘櫙鍚?, "description": "鎻忚堪", "tableRequirements": {{"琛ㄥ悕": "闇€姹傛弿杩?}}}}
  ],
  "data_analysis": [
    {{"table": "琛ㄥ悕", "analysis": "鍒嗘瀽缁撴灉"}}
  ],
  "generated_tables": [
    {{"table_name": "琛ㄥ悕", "rows": [{{"瀛楁鍚?: "鍊?}}], "sqls": ["INSERT INTO ..."]}}
  ]
}}
```

## 閲嶈鎻愰啋
1. 蹇呴』鎸夐『搴忔墽琛?涓樁娈碉紝涓嶈兘璺宠繃浠讳綍闃舵
2. 闃舵1鐢熸垚鍦烘櫙鍚庯紝涓嶈鐩存帴杩涘叆闃舵3锛屽繀椤诲厛瀹屾垚闃舵2鐨勬暟鎹垎鏋?
3. 姣忎釜闃舵閮藉繀椤昏皟鐢ㄧ浉搴旂殑宸ュ叿
4. 濡傛灉涓嶈皟鐢?render_insert_sql锛屾暟鎹皢鏃犳硶淇濆瓨"""

        # 4. 鎵ц Agent
        print(f"       [Agent] 寮€濮嬫墽琛屼换鍔?(鏈€澶?{config.max_agent_turns} 杞?...")
        try:
            result = self._react_executor.execute(
                task=task,
                context=context,
                max_turns=config.max_agent_turns,
            )
        except Exception as e:
            print(f"       [Agent] 鎵ц寮傚父: {e}")
            if config.fallback_to_local:
                print(f"       [Agent] 寮傚父鍥為€€鍒版湰鍦版ā寮?)
                return self._generate_traditional(
                    requirement_text, interfaces, **kwargs
                )
            raise

        print(f"       [Agent] 鎵ц瀹屾垚: success={result.success}, tool_calls={len(result.tool_calls)}, final_output_len={len(result.final_output or '')}, error={result.error}")

        if not result.success and config.fallback_to_local:
            print(f"       [Agent] 鎵ц澶辫触锛屽洖閫€鍒版湰鍦版ā寮?(fallback_to_local=True)")
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
        """鍑嗗 Agent 涓婁笅鏂?""

        # 鏀堕泦鎺ュ彛淇℃伅
        interface_infos = [
            self._interface_trace_service.get_table_info(item.name, item.path)
            for item in interfaces
        ]

        # 鏀堕泦琛ㄧ粨鏋?
        schemas = self._schema_service.get_all_table_schemas(interface_infos)

        # 鏀堕泦鏈湴瀛楁瑙勫垯
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
        """鍑嗗鏁版嵁鐢熸垚闇€姹?""
        # 鍙互浠?PlanningService 鑾峰彇宸叉湁鐨勬暟鎹鍒掍綔涓哄弬鑰?
        return {}

    def _parse_agent_result_draft(
        self, result, context: dict
    ) -> PlanningDraft:
        """瑙ｆ瀽 Agent 鎵ц缁撴灉锛堣崏绋匡級"""
        import json
        from api_data_gen.domain.models import RequirementSummary, ScenarioDraft

        # 浠庝笂涓嬫枃涓彁鍙栧熀鏈俊鎭?
        requirement = RequirementSummary(
            summary=context.get("requirement", ""),
            constraints=[],
            keywords=[],
        )

        # 浠?Agent 缁撴灉涓彁鍙栧満鏅?
        scenarios = []
        table_plans = []

        # 1. 灏濊瘯浠?final_output 瑙ｆ瀽
        if result.final_output:
            scenarios, table_plans = self._extract_scenarios_from_output(
                result.final_output, context
            )

        # 2. 濡傛灉 final_output 娌℃湁鍦烘櫙锛屽皾璇曚粠 tool_calls 瑙ｆ瀽
        if not scenarios:
            scenarios, table_plans = self._extract_scenarios_from_tool_calls(
                result.tool_calls, context
            )

        # 鏋勫缓鎵ц鎽樿
        executed_skills = [
            AgentSkillExecution(
                skill_name=tc.tool_name,
                summary=f"status={tc.status.value}, result={str(tc.result)[:50] if tc.result else tc.error}"
            )
            for tc in result.tool_calls
        ]

        # 杩斿洖 PlanningDraft
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
        """瑙ｆ瀽 Agent 鎵ц缁撴灉锛堢敓鎴愶級"""
        import json
        from api_data_gen.domain.models import RequirementSummary, GeneratedTable, ScenarioGeneration

        requirement = RequirementSummary(
            summary=context.get("requirement", ""),
            constraints=[],
            keywords=[],
        )

        # 浠?Agent 缁撴灉涓彁鍙栫敓鎴愮殑鏁版嵁
        generated_tables = []
        scenario_generations = []

        # 灏濊瘯浠?final_output 瑙ｆ瀽
        if result.final_output:
            generated_tables, scenario_generations = self._extract_generated_data(
                result.final_output, context
            )

        # 濡傛灉 final_output 娌℃湁鏁版嵁锛屽皾璇曚粠 tool_calls 瑙ｆ瀽
        if not generated_tables:
            generated_tables, scenario_generations = self._extract_generated_data_from_tools(
                result.tool_calls, context
            )

        # 鏋勫缓鎵ц鎽樿
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
        """浠庤緭鍑轰腑鎻愬彇鍦烘櫙"""
        import json
        scenarios = []

        # 灏濊瘯瑙ｆ瀽 JSON
        try:
            # 鏌ユ壘 JSON 鏁扮粍
            import re
            json_match = re.search(r'\[[\s\S]*\]', output)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    for i, item in enumerate(data):
                        if isinstance(item, dict):
                            scenarios.append(ScenarioDraft(
                                id=item.get("id", f"agent鍦烘櫙_{i}"),
                                title=item.get("title", item.get("name", f"鍦烘櫙 {i}")),
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
        """浠庡伐鍏疯皟鐢ㄤ腑鎻愬彇鍦烘櫙"""
        scenarios = []

        for tc in tool_calls:
            if tc.tool_name == "generate_scenarios_ai" and tc.result:
                try:
                    if isinstance(tc.result, list):
                        for i, item in enumerate(tc.result):
                            if isinstance(item, dict):
                                scenarios.append(ScenarioDraft(
                                    id=item.get("id", f"agent鍦烘櫙_{i}"),
                                    title=item.get("title", f"鍦烘櫙 {i}"),
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
        """浠庤緭鍑轰腑鎻愬彇鐢熸垚鐨勬暟鎹?""
        import json
        from api_data_gen.domain.models import GeneratedTable, ScenarioGeneration

        generated_tables = []

        try:
            import re
            # 灏濊瘯鏌ユ壘 JSON 瀵硅薄
            json_match = re.search(r'\{[\s\S]*\}', output)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    # 瑙ｆ瀽 generated_tables
                    tables_data = data.get("generated_tables", data.get("tables", []))
                    if isinstance(tables_data, list):
                        for table_data in tables_data:
                            if isinstance(table_data, dict):
                                generated_tables.append(GeneratedTable(
                                    table_name=table_data.get("table_name", "unknown"),
                                    rows=table_data.get("rows", []),
                                    sqls=table_data.get("sqls", []),
                                    generation_source="ai",  # 鏍囪涓?AI 鐢熸垚
                                ))
        except (json.JSONDecodeError, Exception):
            pass

        return generated_tables, []

    def _extract_generated_data_from_tools(
        self, tool_calls: list, context: dict
    ) -> tuple[list, list]:
        """浠庡伐鍏疯皟鐢ㄤ腑鎻愬彇鐢熸垚鐨勬暟鎹?""
        import json
        from api_data_gen.domain.models import GeneratedTable, ScenarioGeneration

        generated_tables = []

        for tc in tool_calls:
            if tc.tool_name in ("generate_table_rows_ai", "render_insert_sql") and tc.result:
                try:
                    if isinstance(tc.result, list):
                        # 灏濊瘯纭畾琛ㄥ悕
                        table_name = "unknown"
                        sqls = []

                        if tc.tool_name == "render_insert_sql":
                            sqls = tc.result

                        generated_tables.append(GeneratedTable(
                            table_name=table_name,
                            rows=tc.result if tc.tool_name == "generate_table_rows_ai" else [],
                            sqls=sqls,
                            generation_source="ai",  # 鏍囪涓?AI 鐢熸垚
                        ))
                except Exception:
                    pass

        return generated_tables, []

    # ========== 浼犵粺妯″紡锛堜繚鎸佸師鏈夐€昏緫锛?=========

    def _build_draft_traditional(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> PlanningDraft:
        """浼犵粺妯″紡鏋勫缓鑽夌"""
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
        """浼犵粺妯″紡鐢熸垚鏁版嵁"""
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

