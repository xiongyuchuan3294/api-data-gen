from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import GeneratedRow, GeneratedTable, ValidationCheck
from api_data_gen.services.sql_apply_service import SqlApplyService


class _FakeApplyClient:
    def __init__(self):
        self.executed: list[tuple[str, list[str]]] = []

    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        mapping = {
            "table_a": ("schema_a", "table_a"),
            "table_b": ("schema_b", "table_b"),
        }
        return mapping[table_name]

    def execute_statements(self, database: str, statements: list[str]) -> None:
        self.executed.append((database, list(statements)))


class SqlApplyServiceTest(unittest.TestCase):
    def test_apply_executes_grouped_statements_when_validation_passes(self) -> None:
        client = _FakeApplyClient()
        service = SqlApplyService(client)

        result = service.apply(
            generated_tables=[
                GeneratedTable(
                    table_name="table_a",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "1"})],
                    insert_sql=["INSERT INTO `table_a` (`id`) VALUES ('1');"],
                ),
                GeneratedTable(
                    table_name="table_b",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "2"})],
                    insert_sql=["INSERT INTO `table_b` (`id`) VALUES ('2');"],
                ),
            ],
            validation_checks=[ValidationCheck(name="cross_table:cust_id", passed=True)],
        )

        self.assertTrue(result.applied)
        self.assertEqual(2, result.statement_count)
        self.assertEqual(["schema_a", "schema_b"], result.schemas)
        self.assertEqual(2, len(client.executed))

    def test_apply_rejects_failed_validation_without_force(self) -> None:
        client = _FakeApplyClient()
        service = SqlApplyService(client)

        with self.assertRaisesRegex(ValueError, "validation failed"):
            service.apply(
                generated_tables=[
                    GeneratedTable(
                        table_name="table_a",
                        row_count=1,
                        rows=[GeneratedRow(values={"id": "1"})],
                        insert_sql=["INSERT INTO `table_a` (`id`) VALUES ('1');"],
                    )
                ],
                validation_checks=[ValidationCheck(name="field_match:broken", passed=False)],
            )

        self.assertEqual([], client.executed)

    def test_apply_force_executes_even_when_validation_fails(self) -> None:
        client = _FakeApplyClient()
        service = SqlApplyService(client)

        result = service.apply(
            generated_tables=[
                GeneratedTable(
                    table_name="table_a",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "1"})],
                    insert_sql=["INSERT INTO `table_a` (`id`) VALUES ('1');"],
                )
            ],
            validation_checks=[ValidationCheck(name="field_match:broken", passed=False)],
            force=True,
        )

        self.assertTrue(result.applied)
        self.assertTrue(result.forced)
        self.assertEqual(1, len(client.executed))


if __name__ == "__main__":
    unittest.main()
