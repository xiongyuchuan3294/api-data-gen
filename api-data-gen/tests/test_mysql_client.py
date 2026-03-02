from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.infra.db.mysql_client import MysqlClient


class _FakeMysqlClient(MysqlClient):
    def __init__(self, row):
        super().__init__(Settings())
        self._row = row

    def fetch_one(self, query: str, params=()):
        return self._row

    def fetch_all(self, query: str, params=()):
        return []


class MysqlClientTest(unittest.TestCase):
    def test_resolve_table_location_accepts_uppercase_information_schema_keys(self) -> None:
        client = _FakeMysqlClient({"TABLE_SCHEMA": "aml_new3", "TABLE_NAME": "aml_f_tidb_model_result"})

        schema_name, table_name = client.resolve_table_location("aml_f_tidb_model_result")

        self.assertEqual("aml_new3", schema_name)
        self.assertEqual("aml_f_tidb_model_result", table_name)


if __name__ == "__main__":
    unittest.main()
