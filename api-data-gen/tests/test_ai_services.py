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

    def test_ai_scenario_service_accepts_compact_line_format(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                SCENARIO|联合主链路|覆盖两个接口的联合验证
                TABLE|table_a|生成 1 条主记录
                TABLE|table_b|生成 1 条关联记录

                SCENARIO|边界场景|覆盖边界输入
                TABLE|table_a|生成 1 条边界记录
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="覆盖核心交易链路",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("drft_no", "varchar(32)", False, None, "票号", False, False, 32)],
                    primary_keys=[],
                ),
            },
        )

        self.assertEqual(2, len(scenarios))
        self.assertEqual("联合主链路", scenarios[0].title)
        self.assertEqual("生成 1 条关联记录", scenarios[0].table_requirements["table_b"])
        self.assertIn("优先输出紧凑行格式", client.calls[0]["user_prompt"])
        self.assertEqual(900, client.calls[0]["max_output_tokens"])

    def test_ai_scenario_service_retries_when_multi_interface_output_is_not_joint(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "单接口场景",
                    "description": "只覆盖 table_a。",
                    "tableRequirements": {
                      "table_a": "生成 1 条"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "联合主链路场景",
                    "description": "同时覆盖两个接口。",
                    "tableRequirements": {
                      "table_a": "生成 1 条主记录",
                      "table_b": "生成 1 条关联记录"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="生成多接口联合场景",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                ),
                "table_b": TableSchema(
                    table_name="table_b",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                ),
            },
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual(["table_a", "table_b"], scenarios[0].tables)
        self.assertEqual(2, len(client.calls))
        self.assertIn("多接口联合测试要求", client.calls[0]["user_prompt"])
        self.assertIn("没有任何场景同时覆盖两个及以上接口", client.calls[1]["user_prompt"])
        self.assertIn("请重新输出完整紧凑行格式", client.calls[1]["user_prompt"])

    def test_ai_scenario_service_repairs_invalid_json_once(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "坏场景",
                    "description": "缺右括号",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                """,
                """
                [
                  {
                    "name": "修复后的场景",
                    "description": "已修复",
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
            requirement_text="修复场景 JSON",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual("修复后的场景", scenarios[0].title)
        self.assertEqual(2, len(client.calls))

    def test_ai_scenario_service_repairs_invalid_json_twice_when_needed(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "坏场景",
                    "description": "缺右括号",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                """,
                """
                [
                  {
                    "name": "仍然坏掉的场景",
                    "description": "字符串没收口,
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "第二次修复成功",
                    "description": "已修复",
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
            requirement_text="修复场景 JSON 两次",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual("第二次修复成功", scenarios[0].title)
        self.assertEqual(3, len(client.calls))

    def test_ai_scenario_service_salvages_complete_objects_from_truncated_json(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "完整场景",
                    "description": "可恢复",
                    "tableRequirements": {
                      "table_a": "1 row"
                    }
                  },
                  {
                    "name": "截断场景",
                    "description": "没收尾
                """
            ]
        )
        service = AiScenarioService(client)

        scenarios = service.generate(
            requirement_text="截断场景恢复",
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
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
        )

        self.assertEqual(1, len(scenarios))
        self.assertEqual("完整场景", scenarios[0].title)
        self.assertEqual(1, len(client.calls))

    def test_ai_scenario_service_raises_when_multi_interface_output_still_invalid_after_retry(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                [
                  {
                    "name": "单接口场景A",
                    "description": "只覆盖 table_a。",
                    "tableRequirements": {
                      "table_a": "生成 1 条"
                    }
                  }
                ]
                """,
                """
                [
                  {
                    "name": "单接口场景A-重试",
                    "description": "还是只覆盖 table_a。",
                    "tableRequirements": {
                      "table_a": "生成 1 条"
                    }
                  }
                ]
                """,
            ]
        )
        service = AiScenarioService(client)

        with self.assertRaisesRegex(ValueError, "multi-interface coverage"):
            service.generate(
                requirement_text="生成多接口联合场景",
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
                        columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                        primary_keys=[],
                    ),
                    "table_b": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
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

        self.assertIsInstance(plans["table_a"], AiTableGenerationAdvice)
        self.assertEqual([{"amount": "12.5", "memo": "ok"}], plans["table_a"].rows)
        self.assertEqual([{"name": "alice"}, {"name": "bob"}], plans["table_b"].rows)
        self.assertEqual({"cust_id": "local", "amount": "ai", "memo": "ai"}, plans["table_a"].field_strategies)
        self.assertIn("以下字段具备本地规则能力，仅供参考", client.calls[0]["user_prompt"])
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
                objective="修复 JSON",
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
                      "implementation_hint": "后续可沉淀一个短文本摘要生成器"
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
            requirement_text="字段策略决策",
            table_name="table_a",
            schema=TableSchema(
                table_name="table_a",
                table_type="innodb",
                columns=[
                    TableColumn("memo", "varchar(20)", True, None, "摘要", False, False, 20),
                    TableColumn("transactionkey", "varchar(64)", False, None, "交易流水", False, False, 64),
                ],
                primary_keys=[],
            ),
            scenario_summaries=["场景A: 命中核心链路; 表要求: 生成1条"],
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
                implementation_hint="后续可沉淀一个短文本摘要生成器",
            ),
            advice.field_generation_strategies["memo"],
        )
        self.assertEqual("transaction_key", advice.field_generation_strategies["transactionkey"].generator)
        self.assertIn("只做字段策略判断", client.calls[0]["user_prompt"])
        self.assertIn("transactionkey", client.calls[0]["user_prompt"])
        self.assertEqual(700, client.calls[0]["max_output_tokens"])

    def test_ai_data_generation_service_accepts_compact_field_strategy_format(self) -> None:
        client = _FakeAiChatClient(
            [
                """
                TABLE|table_a
                FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d||组合键|
                FIELD|ds|local|date_format_from_field|source_field=alert_date;output_format=%Y%m%d||日期派生|
                """
            ]
        )
        service = AiDataGenerationService(client)

        advice = service.decide_table_field_strategies(
            requirement_text="字段策略决策",
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
            scenario_summaries=["场景A: 命中核心链路; 表要求: 生成1条"],
            local_generated_columns={"result_key", "ds"},
        )

        self.assertEqual("concat_template", advice.field_generation_strategies["result_key"].generator)
        self.assertEqual(
            {"result_date": "date:%Y%m%d"},
            advice.field_generation_strategies["result_key"].params["transforms"],
        )
        self.assertEqual("date_format_from_field", advice.field_generation_strategies["ds"].generator)
        self.assertIn("FIELD|字段名|local或ai|generator编码", client.calls[0]["user_prompt"])
        self.assertEqual(700, client.calls[0]["max_output_tokens"])

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
            requirement_text="批量字段策略",
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
                    "scenario_summaries": ["场景A: 生成组合字段"],
                    "local_generated_columns": {"cust_id"},
                },
                {
                    "table_name": "table_b",
                    "schema": TableSchema(
                        table_name="table_b",
                        table_type="innodb",
                        columns=[
                            TableColumn("seq_no", "varchar(8)", False, None, "历史序号", False, False, 8),
                        ],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["场景B: 生成序号"],
                    "local_generated_columns": set(),
                },
            ],
            fixed_values=["cust_id=1"],
        )

        self.assertEqual({"table_a", "table_b"}, set(advice_by_table))
        self.assertEqual("concat_template", advice_by_table["table_a"].field_generation_strategies["result_key"].generator)
        self.assertEqual("sequence_cycle", advice_by_table["table_b"].field_generation_strategies["seq_no"].generator)
        self.assertIn("批量判断多张表的字段生成策略", client.calls[0]["user_prompt"])
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
            requirement_text="批量字段策略",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("result_key", "varchar(64)", False, None, "", False, False, 64)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["场景A"],
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
                    "scenario_summaries": ["场景B"],
                    "local_generated_columns": set(),
                },
            ],
        )

        self.assertEqual({"table_a", "table_b"}, set(advice_by_table))
        self.assertEqual("concat_template", advice_by_table["table_a"].field_generation_strategies["result_key"].generator)
        self.assertEqual(["8", "7", "10"], advice_by_table["table_b"].field_generation_strategies["seq_no"].params["values"])
        self.assertGreaterEqual(client.calls[0]["max_output_tokens"], 700)

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
            requirement_text="批量截断恢复",
            table_requests=[
                {
                    "table_name": "table_a",
                    "schema": TableSchema(
                        table_name="table_a",
                        table_type="innodb",
                        columns=[TableColumn("memo", "varchar(20)", True, None, "", False, False, 20)],
                        primary_keys=[],
                    ),
                    "scenario_summaries": ["场景A"],
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
                    "scenario_summaries": ["场景B"],
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
                objective="批量失败后拆表生成",
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
        self.assertIn("表: table_a", client.calls[3]["user_prompt"])
        self.assertNotIn("表: table_b", client.calls[3]["user_prompt"])


if __name__ == "__main__":
    unittest.main()
