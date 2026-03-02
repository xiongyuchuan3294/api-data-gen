from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.infra.db.schema_repository import SchemaRepository


class _FakeSchemaClient:
    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        return ("aml_new3", table_name)

    def fetch_one(self, query: str, params=()):
        if "SHOW TABLE STATUS" in query:
            return {"Engine": "InnoDB"}
        raise AssertionError(f"Unexpected fetch_one query: {query}")

    def fetch_all(self, query: str, params=()):
        if "SHOW KEYS" in query:
            return [{"Column_name": "uuid"}]
        if "SHOW FULL COLUMNS" in query:
            return [
                {
                    "Field": "uuid",
                    "Type": "varchar(64)",
                    "Null": "NO",
                    "Default": None,
                    "Comment": "主键",
                    "Extra": "",
                },
                {
                    "Field": "trans_amount",
                    "Type": "decimal(20,4)",
                    "Null": "YES",
                    "Default": None,
                    "Comment": "交易金额",
                    "Extra": "",
                },
            ]
        raise AssertionError(f"Unexpected fetch_all query: {query}")


class SchemaRepositoryTest(unittest.TestCase):
    def test_get_table_schema(self) -> None:
        repository = SchemaRepository(_FakeSchemaClient())
        schema = repository.get_table_schema("aml_f_wst_alert_cust_trans_info")

        self.assertEqual("aml_f_wst_alert_cust_trans_info", schema.table_name)
        self.assertEqual("innodb", schema.table_type)
        self.assertEqual(["uuid"], schema.primary_keys)
        self.assertEqual(2, len(schema.columns))
        self.assertTrue(schema.columns[0].is_primary_key)
        self.assertEqual(20, schema.columns[1].max_length)


if __name__ == "__main__":
    unittest.main()
