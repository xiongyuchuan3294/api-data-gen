from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.infra.db.field_match_repository import FieldMatchRepository


class _FakeFieldMatchClient:
    def __init__(self):
        self.query = ""
        self.params = ()
        self.executed_schema = ""
        self.executed_statements: list[str] = []

    def fetch_all(self, query: str, params=()):
        self.query = query
        self.params = params
        return [
            {
                "target_table": "target_table",
                "target_field": "target_no",
                "source_table": "source_table",
                "source_field": "source_no",
                "match_reason": "explicit relation",
            }
        ]

    def execute_statements(self, schema: str, statements: list[str]) -> None:
        self.executed_schema = schema
        self.executed_statements = list(statements)


class FieldMatchRepositoryTest(unittest.TestCase):
    def test_list_relations_queries_trace_schema_and_maps_rows(self) -> None:
        client = _FakeFieldMatchClient()
        repository = FieldMatchRepository(client, Settings())

        relations = repository.list_relations(["target_table", "source_table"])

        self.assertIn("field_match_relations", client.query)
        self.assertEqual(("target_table", "source_table", "target_table", "source_table"), client.params)
        self.assertEqual(1, len(relations))
        self.assertEqual("target_no", relations[0].target_field)
        self.assertEqual("source_no", relations[0].source_field)

    def test_replace_target_relations_rewrites_target_rows(self) -> None:
        client = _FakeFieldMatchClient()
        repository = FieldMatchRepository(client, Settings())
        relations = [
            relation
            for relation in repository.list_relations(["target_table"])
            if relation.target_table == "target_table"
        ]

        repository.replace_target_relations(
            "target_table",
            relations=relations,
        )

        self.assertEqual("rrs_test_dev", client.executed_schema)
        self.assertEqual(2, len(client.executed_statements))
        self.assertIn("DELETE FROM `rrs_test_dev`.field_match_relations", client.executed_statements[0])
        self.assertIn("'target_table'", client.executed_statements[0])
        self.assertIn("INSERT INTO `rrs_test_dev`.field_match_relations", client.executed_statements[1])
        self.assertIn(f"'{relations[0].source_table}'", client.executed_statements[1])


if __name__ == "__main__":
    unittest.main()
