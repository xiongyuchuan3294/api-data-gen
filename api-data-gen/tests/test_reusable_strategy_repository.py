from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.domain.models import FieldGenerationStrategy, StoredFieldStrategy, StoredRelationStrategy
from api_data_gen.infra.db.reusable_strategy_repository import ReusableStrategyRepository


class _FakeReusableStrategyClient:
    def __init__(self):
        self.query = ""
        self.params = ()
        self.fetch_rows: list[dict[str, object]] = []
        self.executed_calls: list[tuple[str, list[str]]] = []

    def fetch_all(self, query: str, params=()):
        self.query = query
        self.params = params
        return list(self.fetch_rows)

    def execute_statements(self, schema: str, statements: list[str]) -> None:
        self.executed_calls.append((schema, list(statements)))


class ReusableStrategyRepositoryTest(unittest.TestCase):
    def test_list_field_strategies_queries_trace_schema_and_maps_rows(self) -> None:
        client = _FakeReusableStrategyClient()
        client.fetch_rows = [
            {
                "table_name": "demo_table",
                "field_name": "result_key",
                "executor": "local",
                "generator": "concat_template",
                "params_json": '{"template":"{uuid}-R"}',
                "fallback_generators_json": '["sample_cycle"]',
                "rationale": "拼接结果键",
                "implementation_hint": "后续可沉淀",
                "implementation_code": "def build(): pass",
                "strategy_source": "ai_generic",
            }
        ]
        repository = ReusableStrategyRepository(client, Settings())

        records = repository.list_field_strategies(["demo_table"])

        self.assertIn("reusable_field_strategies", client.query)
        self.assertEqual(("demo_table",), client.params)
        self.assertEqual(1, len(records))
        self.assertEqual("result_key", records[0].field_name)
        self.assertEqual("concat_template", records[0].strategy.generator)
        self.assertEqual("{uuid}-R", records[0].strategy.params["template"])

    def test_save_field_strategies_creates_and_upserts_trace_schema_tables(self) -> None:
        client = _FakeReusableStrategyClient()
        repository = ReusableStrategyRepository(client, Settings())

        repository.save_field_strategies(
            [
                StoredFieldStrategy(
                    table_name="demo_table",
                    field_name="result_key",
                    strategy=FieldGenerationStrategy(
                        executor="local",
                        generator="concat_template",
                        params={"template": "{uuid}-R"},
                        fallback_generators=["sample_cycle"],
                    ),
                    strategy_source="ai_generic",
                )
            ]
        )

        self.assertEqual(2, len(client.executed_calls))
        self.assertEqual("rrs_test_dev", client.executed_calls[0][0])
        self.assertIn("CREATE TABLE IF NOT EXISTS `rrs_test_dev`.reusable_field_strategies", client.executed_calls[0][1][0])
        self.assertIn("INSERT INTO `rrs_test_dev`.reusable_field_strategies", client.executed_calls[1][1][0])
        self.assertIn("'demo_table'", client.executed_calls[1][1][0])

    def test_list_relation_strategies_queries_trace_schema_and_maps_rows(self) -> None:
        client = _FakeReusableStrategyClient()
        client.fetch_rows = [
            {
                "target_table": "target_table",
                "target_field": "drft_no",
                "source_table": "source_table",
                "source_field": "drft_no",
                "executor": "local",
                "generator": "copy_from_context",
                "params_json": '{"source_field":"drft_no","source_table":"source_table"}',
                "fallback_generators_json": '["sample_cycle"]',
                "rationale": "keep consistent",
                "implementation_hint": "",
                "implementation_code": "",
                "relation_reason": "scenario relation",
                "strategy_source": "scenario_inferred",
                "relation_type": "same_value",
                "evidence_json": '{"scenario_id":"ai:chain:1"}',
                "confidence_score": 0.9,
            }
        ]
        repository = ReusableStrategyRepository(client, Settings())

        records = repository.list_relation_strategies(["target_table", "source_table"])

        self.assertIn("reusable_relation_strategies", client.query)
        self.assertEqual(("target_table", "source_table", "target_table", "source_table"), client.params)
        self.assertEqual(1, len(records))
        self.assertEqual("drft_no", records[0].target_field)
        self.assertEqual("same_value", records[0].relation_type)
        self.assertEqual("ai:chain:1", records[0].evidence["scenario_id"])
        self.assertEqual(0.9, records[0].confidence_score)

    def test_save_relation_strategies_creates_and_upserts_trace_schema_tables(self) -> None:
        client = _FakeReusableStrategyClient()
        repository = ReusableStrategyRepository(client, Settings())

        repository.save_relation_strategies(
            [
                StoredRelationStrategy(
                    target_table="target_table",
                    target_field="drft_no",
                    source_table="source_table",
                    source_field="drft_no",
                    strategy=FieldGenerationStrategy(
                        executor="local",
                        generator="copy_from_context",
                        params={"source_table": "source_table", "source_field": "drft_no"},
                        fallback_generators=["sample_cycle"],
                    ),
                    relation_reason="跨表票号一致",
                    strategy_source="scenario_inferred",
                    relation_type="same_value",
                    evidence={"scenario_id": "ai:chain:1"},
                    confidence_score=0.9,
                )
            ]
        )

        self.assertEqual(2, len(client.executed_calls))
        self.assertEqual("rrs_test_dev", client.executed_calls[0][0])
        self.assertIn("CREATE TABLE IF NOT EXISTS `rrs_test_dev`.reusable_relation_strategies", client.executed_calls[0][1][1])
        self.assertIn("INSERT INTO `rrs_test_dev`.reusable_relation_strategies", client.executed_calls[1][1][0])
        self.assertIn("'target_table'", client.executed_calls[1][1][0])
        self.assertIn("relation_type", client.executed_calls[1][1][0])
        self.assertIn("evidence_json", client.executed_calls[1][1][0])
        self.assertIn("0.9", client.executed_calls[1][1][0])


if __name__ == "__main__":
    unittest.main()
