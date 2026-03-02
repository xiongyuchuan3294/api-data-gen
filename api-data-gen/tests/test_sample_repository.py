from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import TableColumn, TableSchema
from api_data_gen.infra.db.sample_repository import SampleRepository


class _FakeSchemaRepository:
    def get_table_schema(self, table_name: str) -> TableSchema:
        return TableSchema(
            table_name=table_name,
            table_type="mysql",
            columns=[
                TableColumn("receive_pay_cd", "varchar(2)", True, None, "", False, False, 2),
                TableColumn("cust_id", "varchar(32)", True, None, "", False, False, 32),
            ],
            primary_keys=[],
        )


class _FakeSampleClient:
    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        if table_name == "aml_f_sys_dict":
            return ("aml_new3", "aml_f_sys_dict")
        return ("aml_new3", table_name)

    def fetch_all(self, query: str, params=()):
        if "field_match_relations" in query:
            return [
                {
                    "target_field": "receive_pay_cd",
                    "source_table": "aml_f_sys_dict",
                    "source_field": "code_value",
                }
            ]
        if "SELECT DISTINCT `code_value`" in query:
            return [{"code_value": "01"}, {"code_value": "02"}]
        if "SELECT * FROM" in query:
            return []
        raise AssertionError(f"Unexpected fetch_all query: {query}")


class _FakeDiscoveryService:
    def __init__(self):
        self.requested_table = ""

    def discover(self, table_name: str):
        from api_data_gen.domain.models import FieldMatchRelation

        self.requested_table = table_name
        return [
            FieldMatchRelation(
                target_table=table_name,
                target_field="receive_pay_cd",
                source_table="aml_f_sys_dict",
                source_field="code_value",
                match_reason="same_column_name",
            )
        ]


class SampleRepositoryTest(unittest.TestCase):
    def test_fallback_sampling_uses_field_match_relations(self) -> None:
        repository = SampleRepository(_FakeSampleClient(), "rrs_test_dev", _FakeSchemaRepository())
        rows = repository.sample_rows("missing_target_table", 2)

        self.assertEqual(
            [
                {"receive_pay_cd": "01", "cust_id": "[DEFAULT]"},
                {"receive_pay_cd": "02", "cust_id": "[DEFAULT]"},
            ],
            rows,
        )

    def test_fallback_sampling_triggers_discovery_when_relations_missing(self) -> None:
        class _NoRelationClient(_FakeSampleClient):
            def fetch_all(self, query: str, params=()):
                if "field_match_relations" in query:
                    return []
                return super().fetch_all(query, params)

        discovery_service = _FakeDiscoveryService()
        repository = SampleRepository(
            _NoRelationClient(),
            "rrs_test_dev",
            _FakeSchemaRepository(),
            field_match_discovery_service=discovery_service,
        )

        rows = repository.sample_rows("missing_target_table", 1)

        self.assertEqual("missing_target_table", discovery_service.requested_table)
        self.assertEqual([{"receive_pay_cd": "01", "cust_id": "[DEFAULT]"}], rows)


if __name__ == "__main__":
    unittest.main()
