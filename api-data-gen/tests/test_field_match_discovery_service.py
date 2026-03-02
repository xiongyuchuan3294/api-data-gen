from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import FieldMatchRelation, TableColumn, TableSchema
from api_data_gen.services.field_match_discovery_service import FieldMatchDiscoveryService


class _FakeSchemaRepository:
    def list_tables(self, schema_names: list[str]) -> list[str]:
        self.schema_names = schema_names
        return ["target_table", "source_by_name", "source_by_comment"]

    def get_row_counts(self, table_names: list[str]) -> dict[str, int]:
        return {
            "source_by_name": 10,
            "source_by_comment": 5,
        }

    def get_table_schema(self, table_name: str) -> TableSchema:
        if table_name == "target_table":
            return TableSchema(
                table_name=table_name,
                table_type="innodb",
                columns=[
                    TableColumn("id", "varchar(32)", False, None, "", True, False, 32),
                    TableColumn("target_no", "varchar(32)", True, None, "", False, False, 32),
                    TableColumn("target_desc", "varchar(32)", True, None, "共享注释", False, False, 32),
                ],
                primary_keys=["id"],
            )
        if table_name == "source_by_name":
            return TableSchema(
                table_name=table_name,
                table_type="innodb",
                columns=[
                    TableColumn("target_no", "varchar(32)", True, None, "", False, False, 32),
                ],
                primary_keys=[],
            )
        return TableSchema(
            table_name=table_name,
            table_type="innodb",
            columns=[
                TableColumn("source_desc", "varchar(32)", True, None, "共享注释", False, False, 32),
            ],
            primary_keys=[],
        )


class _FakeFieldMatchRepository:
    def __init__(self):
        self.saved: list[FieldMatchRelation] = []

    def list_relations(self, table_names: list[str]) -> list[FieldMatchRelation]:
        return []

    def replace_target_relations(self, target_table: str, relations: list[FieldMatchRelation]) -> None:
        self.target_table = target_table
        self.saved = list(relations)


class FieldMatchDiscoveryServiceTest(unittest.TestCase):
    def test_discover_matches_same_name_then_same_comment_and_persists(self) -> None:
        schema_repository = _FakeSchemaRepository()
        field_match_repository = _FakeFieldMatchRepository()
        service = FieldMatchDiscoveryService(
            schema_repository=schema_repository,
            field_match_repository=field_match_repository,
            candidate_schema_names=["aml_new3"],
        )

        relations = service.discover("target_table")

        self.assertEqual("target_table", field_match_repository.target_table)
        self.assertEqual(2, len(relations))
        self.assertEqual("target_no", relations[0].target_field)
        self.assertEqual("source_by_name", relations[0].source_table)
        self.assertEqual("same_column_name", relations[0].match_reason)
        self.assertEqual("target_desc", relations[1].target_field)
        self.assertEqual("source_by_comment", relations[1].source_table)
        self.assertEqual("source_desc", relations[1].source_field)
        self.assertEqual("same_comment:共享注释", relations[1].match_reason)


if __name__ == "__main__":
    unittest.main()
