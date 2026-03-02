from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import InterfaceInfo, ScenarioDraft, SqlInfo, TableColumn, TableSchema
from api_data_gen.services.ai_data_generation_service import AiDataGenerationService
from api_data_gen.services.ai_scenario_service import AiScenarioService


class _FakeAiChatClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._responses.pop(0)


class AiServicesTest(unittest.TestCase):
    def test_ai_scenario_service_parses_json_and_includes_fixed_values(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                ```json
                [
                  {
                    "name": "核心交易链路",
                    "description": "覆盖核心命中数据。",
                    "tableRequirements": {
                      "aml_f_tidb_model_result": "生成 2 条模型结果",
                      "aml_f_wst_alert_cust_trans_info": "确保金额和收付标志可用"
                    }
                  }
                ]
                ```
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="覆盖核心交易链路",
            interface_infos=[
                InterfaceInfo(
                    name="custTransInfo",
                    path="/wst/custTransInfo",
                    sql_infos=[SqlInfo("aml_f_tidb_model_result", ["cust_id = '1'"])],
                )
            ],
            schemas={
                "aml_f_tidb_model_result": TableSchema(
                    table_name="aml_f_tidb_model_result",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
            fixed_values=["cust_id=962020122711000002"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual("ai", scenarios[0].generation_source)
        self.assertEqual(
            "生成 2 条模型结果",
            scenarios[0].table_requirements["aml_f_tidb_model_result"],
        )
        self.assertIn("cust_id=962020122711000002", client.calls[0]["user_prompt"])
        self.assertIn("transactionkey depends on alert_date", client.calls[0]["user_prompt"])

    def test_ai_data_generation_service_normalizes_single_and_batch_rows(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {"table": "table_a", "data": {"amount": 12.5, "memo": "ok"}},
                  {"table": "table_b", "data": [{"name": "alice"}, {"name": "bob"}]}
                ]
                """
            ]
        )
        service = AiDataGenerationService(client)

        rows = service.generate(
            scenario=ScenarioDraft(
                id="ai:test:1",
                title="AI test",
                api_name="multi_api",
                api_path="",
                objective="生成补充字段",
                tables=["table_a", "table_b"],
                table_requirements={"table_a": "1 row", "table_b": "2 rows"},
                generation_source="ai",
            ),
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("amount", "decimal(20,4)", False, None, "", False, False, 20)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("name", "varchar(20)", False, None, "", False, False, 20)],
                    primary_keys=[],
                ),
            },
            sample_rows_by_table={"table_a": [{"amount": "10.00"}], "table_b": [{"name": "legacy"}]},
            local_generated_columns={"table_a": {"cust_id"}, "table_b": set()},
            analysis_by_table={"table_a": '{"amount":"numeric"}', "table_b": '{"name":"person"}'},
            fixed_values=["cust_id=962020122711000002"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
        )

        self.assertEqual([{"amount": "12.5", "memo": "ok"}], rows["table_a"])
        self.assertEqual([{"name": "alice"}, {"name": "bob"}], rows["table_b"])
        self.assertIn("以下字段由本地规则生成", client.calls[0]["user_prompt"])
        self.assertIn("cust_id=962020122711000002", client.calls[0]["user_prompt"])


if __name__ == "__main__":
    unittest.main()
