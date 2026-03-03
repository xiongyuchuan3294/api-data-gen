from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    GenerationReport,
    GeneratedRow,
    GeneratedTable,
    RequirementSummary,
)
from api_data_gen.services.strategy_export_service import StrategyExportService


class StrategyExportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = StrategyExportService()

    def test_render_strategy_config_extracts_table_field_generation_strategies(self) -> None:
        report = GenerationReport(
            requirement=RequirementSummary(summary="字段策略导出", constraints=[], keywords=[]),
            generated_tables=[
                GeneratedTable(
                    table_name="aml_f_wst_alert_cust_trans_info",
                    row_count=1,
                    rows=[GeneratedRow(values={"cust_name": "测试客户A"})],
                    scenario_id="scenario-a",
                    scenario_title="baseline",
                    generation_source="hybrid",
                    field_generation_strategies={
                        "cust_name": FieldGenerationStrategy(
                            executor="ai",
                            generator="sample_cycle",
                            params={"values": ["测试客户A", "测试客户B"]},
                            fallback_generators=["default_value"],
                            rationale="采样值轮询",
                            implementation_hint="后续补一个客户名称生成器",
                        )
                    },
                )
            ],
            generation_tag="RUN20260303",
        )

        payload = self.service.render_strategy_config(
            report=report,
            strategy_mode="agent_auto",
            generated_at="2026-03-03T22:30:00",
            source_result_file="result_20260303_223000_agent_auto.json",
        )

        self.assertEqual(1, payload["version"])
        self.assertEqual("agent_auto", payload["strategy_mode"])
        self.assertEqual("RUN20260303", payload["generation_tag"])
        self.assertEqual(1, payload["table_strategy_count"])
        self.assertEqual(
            "result_20260303_223000_agent_auto.json",
            payload["source_result_file"],
        )
        table_strategy = payload["table_strategies"][0]
        self.assertEqual("scenario-a", table_strategy["scenario_id"])
        self.assertEqual("aml_f_wst_alert_cust_trans_info", table_strategy["table_name"])
        self.assertEqual("ai", table_strategy["field_generation_strategies"]["cust_name"]["executor"])
        self.assertEqual(
            "后续补一个客户名称生成器",
            table_strategy["field_generation_strategies"]["cust_name"]["implementation_hint"],
        )

    def test_render_generator_candidates_aggregates_same_proposal_across_scenarios(self) -> None:
        strategy = FieldGenerationStrategy(
            executor="ai",
            generator="sample_cycle",
            params={"values": ["2020-12-15 09:30:00", "2020-12-16 10:15:00"]},
            fallback_generators=["default_value"],
            rationale="采样值轮询",
            implementation_hint="后续补一个交易时间生成器",
            implementation_code="def generate_trans_time():\n    return '2020-12-15 09:30:00'",
        )
        report = GenerationReport(
            requirement=RequirementSummary(summary="候选清单", constraints=[], keywords=[]),
            generated_tables=[
                GeneratedTable(
                    table_name="aml_f_wst_alert_cust_trans_info",
                    row_count=1,
                    rows=[GeneratedRow(values={"trans_time": "2020-12-15 09:30:00"})],
                    scenario_id="scenario-a",
                    scenario_title="baseline",
                    field_generation_strategies={"trans_time": strategy},
                ),
                GeneratedTable(
                    table_name="aml_f_wst_alert_cust_trans_info",
                    row_count=1,
                    rows=[GeneratedRow(values={"trans_time": "2020-12-16 10:15:00"})],
                    scenario_id="scenario-b",
                    scenario_title="variant",
                    field_generation_strategies={"trans_time": strategy},
                ),
                GeneratedTable(
                    table_name="aml_f_wst_alert_cust_trans_info",
                    row_count=1,
                    rows=[GeneratedRow(values={"transactionkey": "6008C20260303..."})],
                    scenario_id="scenario-c",
                    scenario_title="local-only",
                    field_generation_strategies={
                        "transactionkey": FieldGenerationStrategy(
                            executor="local",
                            generator="transaction_key",
                            rationale="本地交易流水生成器",
                        )
                    },
                ),
            ],
            generation_tag="RUN20260303",
        )

        payload = self.service.render_generator_candidates(
            report=report,
            strategy_mode="agent_auto",
            generated_at="2026-03-03T22:35:00",
            source_result_file="result_20260303_223500_agent_auto.json",
            source_strategy_file="strategy_20260303_223500_agent_auto.json",
        )

        self.assertEqual(1, payload["version"])
        self.assertEqual(1, payload["candidate_count"])
        self.assertEqual(
            "strategy_20260303_223500_agent_auto.json",
            payload["source_strategy_file"],
        )
        candidate = payload["candidates"][0]
        self.assertEqual("aml_f_wst_alert_cust_trans_info", candidate["table_name"])
        self.assertEqual("trans_time", candidate["field_name"])
        self.assertEqual("trans_time", candidate["suggested_generator_code"])
        self.assertFalse(candidate["local_generator_exists"])
        self.assertEqual("pending_review", candidate["review_status"])
        self.assertEqual(2, len(candidate["scenario_refs"]))
        self.assertEqual("scenario-a", candidate["scenario_refs"][0]["scenario_id"])
        self.assertEqual("scenario-b", candidate["scenario_refs"][1]["scenario_id"])

    def test_load_field_decisions_merges_strategy_file_entries_by_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "strategy.json"
            path.write_text(
                json.dumps(
                    {
                        "table_strategies": [
                            {
                                "scenario_id": "scenario-a",
                                "table_name": "demo_table",
                                "field_generation_strategies": {
                                    "trans_time": {
                                        "executor": "ai",
                                        "generator": "random_datetime",
                                        "params": {"start_date": "2020-12-15", "end_date": "2020-12-20"},
                                        "fallback_generators": ["sample_cycle"],
                                        "implementation_hint": "补一个交易时间生成器",
                                    }
                                },
                            },
                            {
                                "scenario_id": "scenario-b",
                                "table_name": "demo_table",
                                "field_generation_strategies": {
                                    "cust_name": {
                                        "executor": "ai",
                                        "generator": "random_choice",
                                        "params": {"values": ["测试客户A", "测试客户B"]},
                                        "fallback_generators": ["sample_cycle", "default_value"],
                                        "implementation_code": "def generate_cust_name(): pass",
                                    }
                                },
                            },
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            decisions = self.service.load_field_decisions(path)

        self.assertEqual({"demo_table"}, set(decisions))
        self.assertEqual(
            AiTableGenerationAdvice(
                table_name="demo_table",
                field_strategies={"trans_time": "ai", "cust_name": "ai"},
                field_generation_strategies={
                    "trans_time": FieldGenerationStrategy(
                        executor="ai",
                        generator="random_datetime",
                        params={"start_date": "2020-12-15", "end_date": "2020-12-20"},
                        fallback_generators=["sample_cycle"],
                        implementation_hint="补一个交易时间生成器",
                    ),
                    "cust_name": FieldGenerationStrategy(
                        executor="ai",
                        generator="random_choice",
                        params={"values": ["测试客户A", "测试客户B"]},
                        fallback_generators=["sample_cycle", "default_value"],
                        implementation_code="def generate_cust_name(): pass",
                    ),
                },
            ),
            decisions["demo_table"],
        )


if __name__ == "__main__":
    unittest.main()
