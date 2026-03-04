from __future__ import annotations

import tempfile
import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.domain.models import (
    InterfaceInfo,
    InterfaceTarget,
    SqlInfo,
    TableColumn,
    TableSchema,
    TraceRequest,
)
from api_data_gen.services.planning_service import PlanningService
from api_data_gen.services.ai_cache_service import AiCacheService
from api_data_gen.services.requirement_parser import RequirementParser


class _FakeTraceRepository:
    def find_latest_request(self, url_prefix: str) -> TraceRequest | None:
        return TraceRequest(
            trace_id="trace-1",
            url=url_prefix,
            method="POST",
            query_params='{"pageSize":"10","pageNum":"1"}',
            request_body='{"custId":"962020122711000002","caseDate":"2020-12-27","modelNo":"WSTY001"}',
        )


class _FakeInterfaceTraceService:
    def get_table_info(self, api_name: str, api_path: str) -> InterfaceInfo:
        if api_path == "/wst/custTransInfo":
            return InterfaceInfo(
                name=api_name,
                path=api_path,
                sql_infos=[
                    SqlInfo("aml_f_tidb_model_result", ["cust_id = '962020122711000002'", "model_key = 'WSTY001'"]),
                    SqlInfo(
                        "aml_f_wst_alert_cust_trans_info",
                        ["cust_id = '962020122711000002'", "alert_date = '2020-12-20'"],
                    ),
                ],
            )
        return InterfaceInfo(
            name=api_name,
            path=api_path,
            sql_infos=[
                SqlInfo("aml_f_tidb_model_result", ["cust_id = '962020122711000002'", "model_key = 'WSTY001'"]),
                SqlInfo(
                    "aml_f_wst_alert_cust_drft_record",
                    ["cust_id = '962020122711000002'", "alert_date = '2020-12-20'"],
                ),
            ],
        )


class _FakeSchemaService:
    def __init__(self):
        self._schemas = {
            "aml_f_tidb_model_result": TableSchema(
                table_name="aml_f_tidb_model_result",
                table_type="innodb",
                columns=[
                    TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                    TableColumn("cust_id", "varchar(64)", True, None, "", False, False, 64),
                    TableColumn("model_key", "varchar(64)", True, None, "", False, False, 64),
                ],
                primary_keys=["uuid"],
            ),
            "aml_f_wst_alert_cust_trans_info": TableSchema(
                table_name="aml_f_wst_alert_cust_trans_info",
                table_type="innodb",
                columns=[
                    TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                    TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                    TableColumn("receive_pay_cd", "varchar(2)", True, None, "资金收付表示", False, False, 2),
                    TableColumn("trans_amount", "decimal(20,4)", True, None, "", False, False, 20),
                ],
                primary_keys=["uuid"],
            ),
            "aml_f_wst_alert_cust_drft_record": TableSchema(
                table_name="aml_f_wst_alert_cust_drft_record",
                table_type="innodb",
                columns=[
                    TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                    TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                    TableColumn("drft_no", "varchar(64)", True, None, "", False, False, 64),
                ],
                primary_keys=["uuid"],
            ),
        }

    def get_all_table_schemas(self, interface_infos: list[InterfaceInfo]) -> dict[str, TableSchema]:
        return dict(self._schemas)


class _FakeSampleRepository:
    def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
        samples = {
            "aml_f_tidb_model_result": [
                {"uuid": "01A", "cust_id": "962020122711000002", "model_key": "WSTY001"},
            ],
            "aml_f_wst_alert_cust_trans_info": [
                {
                    "uuid": "11K",
                    "cust_id": "962020122711000002",
                    "receive_pay_cd": "01",
                    "trans_amount": "129876.4000",
                }
            ],
            "aml_f_wst_alert_cust_drft_record": [
                {"uuid": "026B", "cust_id": "962020122711000002", "drft_no": "510355...3478"},
            ],
        }
        return samples.get(table_name, [])[:limit]


class _FakeDictRuleResolver:
    def resolve_code_values(self, column_name: str, column_comment: str) -> list[str]:
        if column_name == "receive_pay_cd":
            return ["01", "02"]
        return []


class _FakeAiScenarioService:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        requirement_text: str,
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ):
        self.calls.append(
            {
                "requirement_text": requirement_text,
                "interface_infos": interface_infos,
                "schemas": schemas,
                "fixed_values": fixed_values,
                "dependent_fixed_values": dependent_fixed_values,
            }
        )
        from api_data_gen.domain.models import ScenarioDraft

        return [
            ScenarioDraft(
                id="ai:core_chain:1",
                title="AI core chain",
                api_name="multi_api",
                api_path="",
                objective="覆盖核心交易链路和跨表一致性。",
                tables=["aml_f_tidb_model_result", "aml_f_wst_alert_cust_trans_info"],
                table_requirements={
                    "aml_f_tidb_model_result": "生成 2 条模型命中记录。",
                    "aml_f_wst_alert_cust_trans_info": "保证收付标志和金额字段可用。",
                },
                generation_source="ai",
            )
        ]


class _FailingAiScenarioService:
    def generate(self, *args, **kwargs):
        raise RuntimeError("ssl verify failed")


class _EmptyTablesAiScenarioService:
    def generate(
        self,
        requirement_text: str,
        interface_infos: list[InterfaceInfo],
        schemas: dict[str, TableSchema],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ):
        from api_data_gen.domain.models import ScenarioDraft

        return [
            ScenarioDraft(
                id="ai:empty_tables:1",
                title="AI empty tables",
                api_name="multi_api",
                api_path="",
                objective="AI scenario relies on derived relation rules.",
                tables=[],
                table_requirements={},
                generation_source="ai",
            )
        ]


class PlanningServiceTest(unittest.TestCase):
    def test_build_draft_outputs_scenarios_and_table_plans(self) -> None:
        service = PlanningService(
            settings=Settings(),
            trace_repository=_FakeTraceRepository(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            dict_rule_resolver=_FakeDictRuleResolver(),
            requirement_parser=RequirementParser(),
        )

        report = service.build_draft(
            requirement_text=(
                "需求描述：希望基于需求描述、接口和SQL查询行为生成测试场景和造数，"
                "建议在本地MySQL生成新的表，并按 agent skill 方式模块化实现。"
            ),
            interfaces=[
                InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
            ],
            sample_limit=2,
        )

        self.assertIn("测试场景", report.requirement.keywords)
        self.assertEqual(5, len(report.scenarios))
        self.assertEqual(3, len(report.table_plans))
        trans_info_plan = next(plan for plan in report.table_plans if plan.table_name == "aml_f_wst_alert_cust_trans_info")
        receive_pay_plan = next(plan for plan in trans_info_plan.column_plans if plan.column_name == "receive_pay_cd")
        trans_uuid_plan = next(plan for plan in trans_info_plan.column_plans if plan.column_name == "uuid")
        trans_cust_id_plan = next(plan for plan in trans_info_plan.column_plans if plan.column_name == "cust_id")
        self.assertEqual("dictionary", receive_pay_plan.source)
        self.assertEqual(["01", "02"], receive_pay_plan.suggested_values)
        self.assertEqual("generated", trans_uuid_plan.source)
        self.assertEqual("condition", trans_cust_id_plan.source)
        self.assertEqual(["962020122711000002"], trans_cust_id_plan.suggested_values)

        baseline = next(scenario for scenario in report.scenarios if scenario.id == "custTransInfo:baseline")
        self.assertEqual("10", baseline.request_inputs["pageSize"])
        self.assertIn("cust_id = '962020122711000002'", baseline.fixed_conditions)
        self.assertTrue(any(rule.target_table == "aml_f_wst_alert_cust_trans_info" and rule.target_field == "cust_id" and rule.source_table == "aml_f_tidb_model_result" and rule.source_field == "cust_id" for rule in baseline.relation_rules))

    def test_build_draft_uses_ai_scenarios_when_enabled(self) -> None:
        ai_scenario_service = _FakeAiScenarioService()
        service = PlanningService(
            settings=Settings(),
            trace_repository=_FakeTraceRepository(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            dict_rule_resolver=_FakeDictRuleResolver(),
            requirement_parser=RequirementParser(),
            ai_scenario_service=ai_scenario_service,
        )

        report = service.build_draft(
            requirement_text="生成覆盖核心链路的测试场景",
            interfaces=[
                InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
            ],
            sample_limit=2,
            fixed_values=["cust_id=962020122711000002"],
            dependent_fixed_values=["transactionkey 依赖 alert_date"],
            use_ai_scenarios=True,
        )

        self.assertEqual(1, len(report.scenarios))
        self.assertEqual("ai", report.scenarios[0].generation_source)
        self.assertEqual(
            "生成 2 条模型命中记录。",
            report.scenarios[0].table_requirements["aml_f_tidb_model_result"],
        )
        self.assertEqual(["cust_id=962020122711000002"], ai_scenario_service.calls[0]["fixed_values"])
        self.assertEqual(
            ["transactionkey 依赖 alert_date"],
            ai_scenario_service.calls[0]["dependent_fixed_values"],
        )
        self.assertEqual(3, len(report.table_plans))

    def test_build_draft_populates_tables_from_derived_relation_rules(self) -> None:
        service = PlanningService(
            settings=Settings(),
            trace_repository=_FakeTraceRepository(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            dict_rule_resolver=_FakeDictRuleResolver(),
            requirement_parser=RequirementParser(),
            ai_scenario_service=_EmptyTablesAiScenarioService(),
        )

        report = service.build_draft(
            requirement_text="AI scenario derives table coverage from relation rules.",
            interfaces=[
                InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
            ],
            sample_limit=2,
            use_ai_scenarios=True,
        )

        self.assertEqual(1, len(report.scenarios))
        self.assertCountEqual(
            [
                "aml_f_tidb_model_result",
                "aml_f_wst_alert_cust_trans_info",
                "aml_f_wst_alert_cust_drft_record",
            ],
            report.scenarios[0].tables,
        )
        self.assertTrue(report.scenarios[0].relation_rules)

    def test_build_draft_raises_when_ai_scenarios_fail(self) -> None:
        service = PlanningService(
            settings=Settings(),
            trace_repository=_FakeTraceRepository(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            dict_rule_resolver=_FakeDictRuleResolver(),
            requirement_parser=RequirementParser(),
            ai_scenario_service=_FailingAiScenarioService(),
        )

        with self.assertRaisesRegex(RuntimeError, "ssl verify failed"):
            service.build_draft(
                requirement_text="生成覆盖核心链路的测试场景",
                interfaces=[
                    InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                ],
                sample_limit=2,
                use_ai_scenarios=True,
            )

    def test_build_draft_does_not_fallback_to_local_when_ai_scenarios_requested_without_service(self) -> None:
        service = PlanningService(
            settings=Settings(),
            trace_repository=_FakeTraceRepository(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            dict_rule_resolver=_FakeDictRuleResolver(),
            requirement_parser=RequirementParser(),
            ai_scenario_service=None,
        )

        with self.assertRaisesRegex(ValueError, "AI scenario generation requested"):
            service.build_draft(
                requirement_text="生成覆盖核心链路的测试场景",
                interfaces=[
                    InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                    InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
                ],
                sample_limit=2,
                use_ai_scenarios=True,
            )

    def test_build_draft_reuses_cached_ai_scenarios_without_ai_service(self) -> None:
        ai_scenario_service = _FakeAiScenarioService()
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_service = AiCacheService(temp_dir)
            service = PlanningService(
                settings=Settings(),
                trace_repository=_FakeTraceRepository(),
                interface_trace_service=_FakeInterfaceTraceService(),
                schema_service=_FakeSchemaService(),
                sample_repository=_FakeSampleRepository(),
                dict_rule_resolver=_FakeDictRuleResolver(),
                requirement_parser=RequirementParser(),
                ai_scenario_service=ai_scenario_service,
                ai_cache_service=cache_service,
            )

            first_report = service.build_draft(
                requirement_text="生成覆盖核心链路的测试场景",
                interfaces=[
                    InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                    InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
                ],
                sample_limit=2,
                use_ai_scenarios=True,
            )

            cached_service = PlanningService(
                settings=Settings(),
                trace_repository=_FakeTraceRepository(),
                interface_trace_service=_FakeInterfaceTraceService(),
                schema_service=_FakeSchemaService(),
                sample_repository=_FakeSampleRepository(),
                dict_rule_resolver=_FakeDictRuleResolver(),
                requirement_parser=RequirementParser(),
                ai_scenario_service=None,
                ai_cache_service=cache_service,
            )

            second_report = cached_service.build_draft(
                requirement_text="生成覆盖核心链路的测试场景",
                interfaces=[
                    InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo"),
                    InterfaceTarget(name="custDrftRecord", path="/wst/custDrftRecord"),
                ],
                sample_limit=2,
                use_ai_scenarios=True,
            )

        self.assertEqual(1, len(ai_scenario_service.calls))
        self.assertEqual(
            [scenario.title for scenario in first_report.scenarios],
            [scenario.title for scenario in second_report.scenarios],
        )


if __name__ == "__main__":
    unittest.main()
