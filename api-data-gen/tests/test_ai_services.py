from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    InterfaceInfo,
    ScenarioDraft,
    SqlInfo,
    TableColumn,
    TableSchema,
)
from api_data_gen.services.ai_data_generation_service import AiDataGenerationService
from api_data_gen.services.ai_scenario_service import AiScenarioService
from api_data_gen.services.ai_utils import parse_json_payload


class _FakeAiChatClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        call = {"system_prompt": system_prompt, "user_prompt": user_prompt}
        call.update(kwargs)
        self.calls.append(call)
        return self._responses.pop(0)


class AiServicesTest(unittest.TestCase):
    def test_parse_json_payload_accepts_relaxed_json(self) -> None:
        payload = parse_json_payload(
            """
            [
              {table: 'demo_table', field_strategies: {memo: 'ai', cust_id: 'local'}, data: [{memo: 'ok', amount: 12.5,},],},
            ]
            """
        )

        self.assertEqual("demo_table", payload[0]["table"])
        self.assertEqual("ai", payload[0]["field_strategies"]["memo"])
        self.assertEqual("ok", payload[0]["data"][0]["memo"])

    def test_ai_scenario_service_parses_json_and_includes_fixed_values(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                ```json
                [
                  {
                    "name": "core transaction path",
                    "description": "cover the core hit data.",
                    "tableRequirements": {
                      "aml_f_tidb_model_result": "generate 2 model-result rows",
                      "aml_f_wst_alert_cust_trans_info": "ensure amount and receive-pay flags are available"
                    }
                  }
                ]
                ```
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="cover the core transaction path",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                )
            },
            fixed_values=["cust_id=962020122711000002"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual("ai", scenarios[0].generation_source)
        self.assertEqual(
            "generate 2 model-result rows",
            scenarios[0].table_requirements["aml_f_tidb_model_result"],
        )
        self.assertIn("cust_id=962020122711000002", client.calls[0]["user_prompt"])
        self.assertIn("transactionkey depends on alert_date", client.calls[0]["user_prompt"])

    def test_ai_scenario_service_accepts_compact_line_format(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                SCENARIO|joint main path|cover the joint validation for both interfaces
                TABLE|table_a|generate 1 primary row
                TABLE|table_b|generate 1 related row

                SCENARIO|boundary scenario|cover boundary input
                TABLE|table_a|generate 1 boundary row
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="cover the core transaction path",
            interface_infos=[
                InterfaceInfo(
                    name="demo",
                    path="/demo",
                    sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                )
            ],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("drft_no", "varchar(32)", False, None, "draft number", False, False, 32)],
                    primary_keys=[],
                ),
            },
        )

        self.assertEqual(2, len(scenarios))
        self.assertTrue(scenarios[0].title)
        self.assertIn("table_b", scenarios[0].table_requirements)
        self.assertIn("Prefer compact line format", client.calls[0]["user_prompt"])
        self.assertEqual(900, client.calls[0]["max_output_tokens"])

    def test_ai_scenario_service_retries_when_multi_interface_output_is_not_joint(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "single-interface scenario",
                    "description": "cover only table_a.",
                    "tableRequirements": {
                      "table_a": "generate 1 row"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "joint main-path scenario",
                    "description": "cover both interfaces together.",
                    "tableRequirements": {
                      "table_a": "generate 1 primary row",
                      "table_b": "generate 1 related row"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="generate a multi-interface joint scenario",
            interface_infos=[
                InterfaceInfo(
                    name="apiA",
                    path="/api/a",
                    sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                ),
                InterfaceInfo(
                    name="apiB",
                    path="/api/b",
                    sql_infos=[SqlInfo("table_b", ["cust_id = '1'"])],
                ),
            ],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                ),
            },
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual(["table_a", "table_b"], scenarios[0].tables)
        self.assertEqual(2, len(client.calls))
        self.assertIn("Multi-Interface Requirements:", client.calls[0]["user_prompt"])
        self.assertIn("No scenario covers two or more interfaces together.", client.calls[1]["user_prompt"])
        self.assertIn("Do not include markdown fences or any explanation.", client.calls[1]["user_prompt"])

    def test_ai_scenario_service_retries_when_shared_table_hides_missing_interface(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "shared only",
                    "description": "covers only the shared table",
                    "tableRequirements": {
                      "shared_table": "1 row"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "joint scenario",
                    "description": "covers both interface-specific tables",
                    "tableRequirements": {
                      "shared_table": "1 row",
                      "table_a": "1 row",
                      "table_b": "1 row"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="cover both interfaces",
            interface_infos=[
                InterfaceInfo(
                    name="apiA",
                    path="/api/a",
                    sql_infos=[SqlInfo("shared_table", ["cust_id = '1'"]), SqlInfo("table_a", ["cust_id = '1'"])],
                ),
                InterfaceInfo(
                    name="apiB",
                    path="/api/b",
                    sql_infos=[SqlInfo("shared_table", ["cust_id = '1'"]), SqlInfo("table_b", ["cust_id = '1'"])],
                ),
            ],
            schemas={
                "shared_table": TableSchema(
                    table_name="shared_table",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "", False, False, 18)],
                    primary_keys=[],
                ),
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "", False, False, 18)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "", False, False, 18)],
                    primary_keys=[],
                ),
            },
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual(["shared_table", "table_a", "table_b"], scenarios[0].tables)
        self.assertEqual(2, len(client.calls))
        self.assertIn("Missing interface coverage", client.calls[1]["user_prompt"])

    def test_ai_scenario_service_repairs_invalid_json_once(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "broken scenario",
                    "description": "missing closing brace",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                """,
                """
                [
                  {
                    "name": "repaired scenario",
                    "description": "repaired",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="repair scenario JSON",
            interface_infos=[
                InterfaceInfo(
                    name="demo",
                    path="/demo",
                    sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                )
            ],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual("repaired scenario", scenarios[0].title)
        self.assertEqual(2, len(client.calls))

    def test_ai_scenario_service_repairs_invalid_json_twice_when_needed(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "broken scenario",
                    "description": "missing closing brace",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                """,
                """
                [
                  {
                    "name": "still broken scenario",
                    "description": "unterminated string,
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "second repair succeeded",
                    "description": "repaired",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="repair scenario JSON twice",
            interface_infos=[
                InterfaceInfo(
                    name="demo",
                    path="/demo",
                    sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                )
            ],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual("second repair succeeded", scenarios[0].title)
        self.assertEqual(3, len(client.calls))

    def test_ai_scenario_service_salvages_complete_objects_from_truncated_json(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "complete scenario",
                    "description": "recoverable",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  },
                  {
                    "name": "truncated scenario",
                    "description": "missing ending
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="recover truncated scenario",
            interface_infos=[
                InterfaceInfo(
                    name="demo",
                    path="/demo",
                    sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                )
            ],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual("complete scenario", scenarios[0].title)
        self.assertEqual(1, len(client.calls))

    def test_ai_scenario_service_raises_when_multi_interface_output_still_invalid_after_retry(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "single-interface scenario A",
                    "description": "cover only table_a.",
                    "tableRequirements": {
                      "table_a": "generate 1 row"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "single-interface scenario A retry",
                    "description": "still covers only table_a.",
                    "tableRequirements": {
                      "table_a": "generate 1 row"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        with self.assertRaisesRegex(ValueError, "multi-interface coverage"):
            service.generate(
                requirement_text="generate a multi-interface joint scenario",
                interface_infos=[
                    InterfaceInfo(
                        name="apiA",
                        path="/api/a",
                        sql_infos=[SqlInfo("table_a", ["cust_id = '1'"])],
                    ),
                    InterfaceInfo(
                        name="apiB",
                        path="/api/b",
                        sql_infos=[SqlInfo("table_b", ["cust_id = '1'"])],
                    ),
                ],
                schemas={
                    "table_a": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                        primary_keys=[],
                    ),
                    "table_b": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18)],
                        primary_keys=[],
                    ),
                },
            )

    def test_ai_data_generation_service_normalizes_single_and_batch_rows(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {"table": "table_a", "field_strategies": {"cust_id": "local", "amount": "ai", "memo": "ai"}, "data": {"amount": 12.5, "memo": "ok"}},
                  {"table": "table_b", "field_strategies": {"name": "ai"}, "data": [{"name": "alice"}, {"name": "bob"}]}
                ]
                """
            ]
        )
        service = AiDataGenerationService(client)

        plans = service.generate(
            scenario=ScenarioDraft(
                id="ai:test:1",
                title="AI test",
                api_name="multi_api",
                api_path="",
                objective="generate supplemental fields",
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

        self.assertIsInstance(plans["table_a"], AiTableGenerationAdvice)
        self.assertEqual([{"amount": "12.5", "memo": "ok"}], plans["table_a"].rows)
        self.assertEqual([{"name": "alice"}, {"name": "bob"}], plans["table_b"].rows)
        self.assertEqual({"cust_id": "local", "amount": "ai", "memo": "ai"}, plans["table_a"].field_strategies)
        self.assertIn("These fields already have local generator support. Use this as guidance, not as a hard restriction:", client.calls[0]["user_prompt"])
        self.assertIn("cust_id=962020122711000002", client.calls[0]["user_prompt"])

    def test_ai_data_generation_service_repairs_invalid_json_once(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "bad}}
                """,
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "fixed"}}
                ]
                """,
            ]
        )
        service = AiDataGenerationService(client)

        plans = service.generate(
            scenario=ScenarioDraft(
                id="ai:test:2",
                title="AI repair",
                api_name="multi_api",
                api_path="",
                objective="repair JSON",
                tables=["table_a"],
                table_requirements={"table_a": "1 row"},
                generation_source="ai",
            ),
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("memo", "varchar(20)", False, None, "", False, False, 20)],
                    primary_keys=[],
                )
            },
            sample_rows_by_table={"table_a": [{"memo": "legacy"}]},
            local_generated_columns={"table_a": set()},
            analysis_by_table={"table_a": '{"memo":"text"}'},
        )

        self.assertEqual([{"memo": "fixed"}], plans["table_a"].rows)
        self.assertEqual(2, len(client.calls))

    def test_ai_data_generation_service_decides_table_field_strategies(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                {
                  "table": "table_a",
                  "field_strategies": {
                    "memo": "ai",
                    "transactionkey": "local"
                  },
                  "field_generation_strategies": {
                    "memo": {
                      "executor": "ai",
                      "generator": "ai_value",
                      "fallback_generators": ["sample_cycle"],
                      "implementation_hint": "add a short text summary generator later"
                    },
                    "transactionkey": {
                      "executor": "local",
                      "generator": "transaction_key"
                    }
                  }
                }
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice = service.decide_table_field_strategies(
            requirement_text="field strategy decision",
            table_name="table_a",
            schema=TableSchema(
                table_name="table_a",
                table_type="innodb",
                columns=[
                    TableColumn("memo", "varchar(20)", True, None, "summary", False, False, 20),
                    TableColumn("transactionkey", "varchar(64)", False, None, "transaction key", False, False, 64),
                ],
                primary_keys=[],
            ),
            scenario_summaries=["scenario A: hit the main path; table requirement: generate 1 row"],
            local_generated_columns={"transactionkey"},
            fixed_values=["cust_id=1"],
        )

        self.assertEqual("table_a", advice.table_name)
        self.assertEqual([], advice.rows)
        self.assertEqual({"memo": "ai", "transactionkey": "local"}, advice.field_strategies)
        self.assertEqual(
            FieldGenerationStrategy(
                executor="ai",
                generator="ai_value",
                fallback_generators=["sample_cycle"],
                implementation_hint="add a short text summary generator later",
            ),
            advice.field_generation_strategies["memo"],
        )
        self.assertEqual("transaction_key", advice.field_generation_strategies["transactionkey"].generator)
        self.assertIn("Decide field strategies only.", client.calls[0]["user_prompt"])
        self.assertIn("transactionkey", client.calls[0]["user_prompt"])
        self.assertEqual(700, client.calls[0]["max_output_tokens"])

    def test_ai_data_generation_service_accepts_compact_field_strategy_format(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                TABLE|table_a
                FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d||composite key|
                FIELD|ds|local|date_format_from_field|source_field=alert_date;output_format=%Y%m%d||derived date|
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice = service.decide_table_field_strategies(
            requirement_text="field strategy decision",
            table_name="table_a",
            schema=TableSchema(
                table_name="table_a",
                table_type="innodb",
                columns=[
                    TableColumn("result_key", "varchar(64)", True, None, "", False, False, 64),
                    TableColumn("ds", "varchar(8)", True, None, "", False, False, 8),
                ],
                primary_keys=[],
            ),
            scenario_summaries=["scenario A: hit the main path; table requirement: generate 1 row"],
            local_generated_columns={"result_key", "ds"},
        )

        self.assertEqual("concat_template", advice.field_generation_strategies["result_key"].generator)
        self.assertEqual(
            {"result_date": "date:%Y%m%d"},
            advice.field_generation_strategies["result_key"].params["transforms"],
        )
        self.assertEqual("date_format_from_field", advice.field_generation_strategies["ds"].generator)
        self.assertIn("FIELD|field_name|local_or_ai|generator_code", client.calls[0]["user_prompt"])
        self.assertEqual(700, client.calls[0]["max_output_tokens"])

    def test_ai_data_generation_service_accepts_compact_field_strategy_format_after_repair(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                {
                  "table": "table_a",
                  "field_strategies": {
                    "result_key": "local"
                """,
                """
                FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d||| 
                FIELD|trans_time|local|datetime_range_cycle|start_date=2020-12-20;end_date=2020-12-20;start_time=09:00:00;end_time=17:00:00|||
                """,
            ]
        )
        service = AiDataGenerationService(client)

        advice = service.decide_table_field_strategies(
            requirement_text="field strategy repair fallback",
            table_name="table_a",
            schema=TableSchema(
                table_name="table_a",
                table_type="innodb",
                columns=[
                    TableColumn("result_key", "varchar(64)", True, None, "", False, False, 64),
                    TableColumn("trans_time", "varchar(32)", True, None, "", False, False, 32),
                ],
                primary_keys=[],
            ),
            scenario_summaries=["scenario A"],
            local_generated_columns={"result_key", "trans_time"},
        )

        self.assertEqual("concat_template", advice.field_generation_strategies["result_key"].generator)
        self.assertEqual("datetime_range_cycle", advice.field_generation_strategies["trans_time"].generator)
        self.assertEqual("09:00:00", advice.field_generation_strategies["trans_time"].params["start_time"])
        self.assertEqual(2, len(client.calls))

    def test_ai_data_generation_service_decides_table_field_strategies_in_batch(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "table": "table_a",
                    "field_strategies": {
                      "result_key": "local"
                    },
                    "field_generation_strategies": {
                      "result_key": {
                        "executor": "local",
                        "generator": "concat_template",
                        "params": {
                          "template": "{model_key}{result_date}{cust_id}",
                          "transforms": {
                            "result_date": "date:%Y%m%d"
                          }
                        }
                      }
                    }
                  },
                  {
                    "table": "table_b",
                    "field_strategies": {
                      "seq_no": "local"
                    },
                    "field_generation_strategies": {
                      "seq_no": {
                        "executor": "local",
                        "generator": "sequence_cycle",
                        "params": {
                          "values": ["8", "7", "10"]
                        }
                      }
                    }
                  }
                ]
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice_by_table = service.decide_tables_field_strategies(
            requirement_text="batch field strategies",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[
                            TableColumn("result_key", "varchar(64)", False, None, "", False, False, 64),
                            TableColumn("model_key", "varchar(16)", False, None, "", False, False, 16),
                            TableColumn("result_date", "varchar(16)", False, None, "", False, False, 16),
                            TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                        ],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario A: generate composed fields"],
                    "local_generated_columns": {"cust_id"},
                },
                {
                    "table_name": "table_b",
                    "schema": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[
                            TableColumn("seq_no", "varchar(8)", False, None, "historical sequence", False, False, 8),
                        ],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario B: generate sequence values"],
                    "local_generated_columns": set(),
                },
            ],
            fixed_values=["cust_id=1"],
        )

        self.assertEqual({"table_a", "table_b"}, set(advice_by_table))
        self.assertEqual("concat_template", advice_by_table["table_a"].field_generation_strategies["result_key"].generator)
        self.assertEqual("sequence_cycle", advice_by_table["table_b"].field_generation_strategies["seq_no"].generator)
        self.assertIn("Decide field-generation strategies for multiple tables.", client.calls[0]["user_prompt"])
        self.assertIn("copy_from_context", client.calls[0]["user_prompt"])
        self.assertGreaterEqual(client.calls[0]["max_output_tokens"], 700)

    def test_ai_data_generation_service_accepts_compact_batch_strategy_format(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                TABLE|table_a
                FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d|||
                TABLE|table_b
                FIELD|seq_no|local|sequence_cycle|values=8,7,10|||
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice_by_table = service.decide_tables_field_strategies(
            requirement_text="batch field strategies",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("result_key", "varchar(64)", False, None, "", False, False, 64)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario A"],
                    "local_generated_columns": set(),
                },
                {
                    "table_name": "table_b",
                    "schema": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[TableColumn("seq_no", "varchar(8)", False, None, "", False, False, 8)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario B"],
                    "local_generated_columns": set(),
                },
            ],
        )

        self.assertEqual({"table_a", "table_b"}, set(advice_by_table))
        self.assertEqual("concat_template", advice_by_table["table_a"].field_generation_strategies["result_key"].generator)
        self.assertEqual(["8", "7", "10"], advice_by_table["table_b"].field_generation_strategies["seq_no"].params["values"])
        self.assertGreaterEqual(client.calls[0]["max_output_tokens"], 700)

    def test_ai_data_generation_service_accepts_compact_batch_strategy_format_after_repair(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "table": "table_a",
                    "field_strategies": {
                      "result_key": "local"
                """,
                """
                TABLE|table_a
                FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d|||
                TABLE|table_b
                FIELD|seq_no|local|sequence_cycle|values=8,7,10|||
                """,
            ]
        )
        service = AiDataGenerationService(client)

        advice_by_table = service.decide_tables_field_strategies(
            requirement_text="field strategy repair fallback",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("result_key", "varchar(64)", False, None, "", False, False, 64)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario A"],
                    "local_generated_columns": set(),
                },
                {
                    "table_name": "table_b",
                    "schema": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[TableColumn("seq_no", "varchar(8)", False, None, "", False, False, 8)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario B"],
                    "local_generated_columns": set(),
                },
            ],
        )

        self.assertEqual({"table_a", "table_b"}, set(advice_by_table))
        self.assertEqual("concat_template", advice_by_table["table_a"].field_generation_strategies["result_key"].generator)
        self.assertEqual(["8", "7", "10"], advice_by_table["table_b"].field_generation_strategies["seq_no"].params["values"])
        self.assertEqual(2, len(client.calls))

    def test_ai_data_generation_service_batch_salvages_complete_objects_from_truncated_json(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "table": "table_a",
                    "field_strategies": {
                      "memo": "local"
                    },
                    "field_generation_strategies": {
                      "memo": {
                        "executor": "local",
                        "generator": "fixed_value",
                        "params": {
                          "value": "ok"
                        }
                      }
                    }
                  },
                  {
                    "table": "table_b",
                    "field_strategies": {
                      "memo": "local"
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice_by_table = service.decide_tables_field_strategies(
            requirement_text="recover truncated batch output",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("memo", "varchar(20)", True, None, "", False, False, 20)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario A"],
                    "local_generated_columns": set(),
                },
                {
                    "table_name": "table_b",
                    "schema": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[TableColumn("memo", "varchar(20)", True, None, "", False, False, 20)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["scenario B"],
                    "local_generated_columns": set(),
                },
            ],
        )

        self.assertEqual({"table_a"}, set(advice_by_table))
        self.assertEqual("fixed_value", advice_by_table["table_a"].field_generation_strategies["memo"].generator)
        self.assertEqual(1, len(client.calls))

    def test_ai_data_generation_service_falls_back_to_single_table_generation(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "broken"}}
                """,
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "still broken"}}
                """,
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "broken again"}}
                """,
                """
                [
                  {"table": "table_a", "field_strategies": {"memo": "ai"}, "data": {"memo": "ok-a"}}
                ]
                """,
                """
                [
                  {"table": "table_b", "field_strategies": {"name": "ai"}, "data": {"name": "ok-b"}}
                ]
                """,
            ]
        )
        service = AiDataGenerationService(client)

        plans = service.generate(
            scenario=ScenarioDraft(
                id="ai:test:3",
                title="AI split repair",
                api_name="multi_api",
                api_path="",
                objective="fallback to per-table generation after batch failure",
                tables=["table_a", "table_b"],
                table_requirements={"table_a": "1 row", "table_b": "1 row"},
                generation_source="ai",
            ),
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("memo", "varchar(20)", False, None, "", False, False, 20)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("name", "varchar(20)", False, None, "", False, False, 20)],
                    primary_keys=[],
                ),
            },
            sample_rows_by_table={"table_a": [{"memo": "legacy"}], "table_b": [{"name": "legacy"}]},
            local_generated_columns={"table_a": set(), "table_b": set()},
            analysis_by_table={"table_a": '{"memo":"text"}', "table_b": '{"name":"person"}'},
        )

        self.assertEqual([{"memo": "ok-a"}], plans["table_a"].rows)
        self.assertEqual([{"name": "ok-b"}], plans["table_b"].rows)
        self.assertEqual(5, len(client.calls))
        self.assertIn("Table: table_a", client.calls[3]["user_prompt"])
        self.assertNotIn("Table: table_b", client.calls[3]["user_prompt"])


if __name__ == "__main__":
    unittest.main()
