from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    StoredFieldStrategy,
    StoredRelationStrategy,
)
from api_data_gen.services.reusable_strategy_service import ReusableStrategyService


class _FakeReusableStrategyRepository:
    def __init__(self):
        self.field_records: list[StoredFieldStrategy] = []
        self.relation_records: list[StoredRelationStrategy] = []

    def list_field_strategies(self, table_names: list[str]) -> list[StoredFieldStrategy]:
        return [record for record in self.field_records if record.table_name in table_names]

    def save_field_strategies(self, strategies: list[StoredFieldStrategy]) -> None:
        self.field_records.extend(strategies)

    def list_relation_strategies(self, table_names: list[str]) -> list[StoredRelationStrategy]:
        return [
            record
            for record in self.relation_records
            if record.target_table in table_names or record.source_table in table_names
        ]

    def save_relation_strategies(self, strategies: list[StoredRelationStrategy]) -> None:
        self.relation_records.extend(strategies)


class ReusableStrategyServiceTest(unittest.TestCase):
    def test_save_generic_field_strategies_filters_out_scenario_specific_strategies(self) -> None:
        repository = _FakeReusableStrategyRepository()
        service = ReusableStrategyService(repository)
        advice = AiTableGenerationAdvice(
            table_name="demo_table",
            field_generation_strategies={
                "result_key": FieldGenerationStrategy(
                    executor="local",
                    generator="concat_template",
                    params={"template": "{uuid}-R"},
                ),
                "trans_time": FieldGenerationStrategy(
                    executor="local",
                    generator="datetime_range_cycle",
                    params={"start": "2020-12-20 09:00:00"},
                ),
                "status_cd": FieldGenerationStrategy(
                    executor="local",
                    generator="dictionary_cycle",
                    params={"values": ["01", "02"]},
                ),
            },
        )

        service.save_generic_field_strategies("demo_table", advice)

        self.assertEqual(2, len(repository.field_records))
        persisted_fields = {record.field_name for record in repository.field_records}
        self.assertEqual({"result_key", "status_cd"}, persisted_fields)

    def test_load_table_advice_returns_field_strategies_only(self) -> None:
        repository = _FakeReusableStrategyRepository()
        repository.field_records = [
            StoredFieldStrategy(
                table_name="target_table",
                field_name="result_key",
                strategy=FieldGenerationStrategy(
                    executor="local",
                    generator="concat_template",
                    params={"template": "{uuid}-R"},
                ),
                strategy_source="ai_generic",
            )
        ]
        repository.relation_records = [
            StoredRelationStrategy(
                target_table="target_table",
                target_field="drft_no",
                source_table="source_table",
                source_field="drft_no",
                strategy=FieldGenerationStrategy(
                    executor="local",
                    generator="copy_from_context",
                    params={"source_table": "source_table", "source_field": "drft_no"},
                ),
                relation_reason="same value relation",
                strategy_source="manual",
            )
        ]
        service = ReusableStrategyService(repository)

        advice = service.load_table_advice("target_table", ["target_table", "source_table"])

        self.assertEqual("local", advice.field_strategies["result_key"])
        self.assertEqual("concat_template", advice.field_generation_strategies["result_key"].generator)
        self.assertNotIn("drft_no", advice.field_strategies)
        self.assertNotIn("drft_no", advice.field_generation_strategies)

    def test_list_relation_strategies_returns_repository_records(self) -> None:
        repository = _FakeReusableStrategyRepository()
        repository.relation_records = [
            StoredRelationStrategy(
                target_table="target_table",
                target_field="drft_no",
                source_table="source_table",
                source_field="drft_no",
                strategy=FieldGenerationStrategy(
                    executor="local",
                    generator="copy_from_context",
                    params={"source_table": "source_table", "source_field": "drft_no"},
                ),
                relation_reason="same value relation",
                strategy_source="manual",
            )
        ]
        service = ReusableStrategyService(repository)

        records = service.list_relation_strategies(["target_table", "source_table"])

        self.assertEqual(1, len(records))
        self.assertEqual("drft_no", records[0].target_field)
        self.assertEqual("copy_from_context", records[0].strategy.generator)

    def test_save_relation_strategies_persists_relation_records(self) -> None:
        repository = _FakeReusableStrategyRepository()
        service = ReusableStrategyService(repository)

        service.save_relation_strategies(
            [
                StoredRelationStrategy(
                    target_table="target_table",
                    target_field="ds",
                    source_table="source_table",
                    source_field="ds",
                    strategy=FieldGenerationStrategy(
                        executor="local",
                        generator="copy_from_context",
                        params={"source_table": "source_table", "source_field": "ds"},
                    ),
                    relation_reason="shared date relation",
                    strategy_source="manual",
                )
            ]
        )

        self.assertEqual(1, len(repository.relation_records))
        record = repository.relation_records[0]
        self.assertEqual("copy_from_context", record.strategy.generator)
        self.assertEqual("source_table", record.strategy.params["source_table"])
        self.assertEqual("ds", record.strategy.params["source_field"])


if __name__ == "__main__":
    unittest.main()
