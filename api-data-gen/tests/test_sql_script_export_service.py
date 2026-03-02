from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import GeneratedRow, GeneratedTable, ValidationCheck
from api_data_gen.services.sql_script_export_service import SqlScriptExportService


class _FakeTableLocator:
    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        mapping = {
            "table_a": ("schema_a", "table_a"),
            "table_b": ("schema_a", "table_b"),
            "table_c": ("schema_b", "table_c"),
        }
        return mapping[table_name]


class SqlScriptExportServiceTest(unittest.TestCase):
    def test_render_groups_tables_by_schema_and_includes_validation_comments(self) -> None:
        service = SqlScriptExportService(_FakeTableLocator())
        script = service.render(
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
                GeneratedTable(
                    table_name="table_c",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "3"})],
                    insert_sql=["INSERT INTO `table_c` (`id`) VALUES ('3');"],
                ),
            ],
            validation_checks=[
                ValidationCheck(name="cross_table:cust_id", passed=True, detail="cust_id expected C1"),
                ValidationCheck(name="field_match:target<-source", passed=False, detail="target=['A']; source=['B']"),
            ],
            generation_tag="RUN20260302",
        )

        self.assertIn("-- Generation tag: RUN20260302", script)
        self.assertIn("-- [PASS] cross_table:cust_id cust_id expected C1", script)
        self.assertIn("-- [FAIL] field_match:target<-source target=['A']; source=['B']", script)
        self.assertIn("USE `schema_a`;", script)
        self.assertIn("USE `schema_b`;", script)
        self.assertEqual(1, script.count("USE `schema_a`;"))
        self.assertIn("START TRANSACTION;", script)
        self.assertTrue(script.endswith("COMMIT;\n"))

    def test_render_includes_scenario_headers_when_present(self) -> None:
        service = SqlScriptExportService(_FakeTableLocator())

        script = service.render(
            generated_tables=[
                GeneratedTable(
                    table_name="table_a",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "1"})],
                    insert_sql=["INSERT INTO `table_a` (`id`) VALUES ('1');"],
                    scenario_id="scenario-a",
                    scenario_title="baseline",
                ),
                GeneratedTable(
                    table_name="table_b",
                    row_count=1,
                    rows=[GeneratedRow(values={"id": "2"})],
                    insert_sql=["INSERT INTO `table_b` (`id`) VALUES ('2');"],
                    scenario_id="scenario-b",
                    scenario_title="dictionary",
                ),
            ],
            validation_checks=[],
        )

        self.assertIn("-- Scenario: scenario-a baseline", script)
        self.assertIn("-- Scenario: scenario-b dictionary", script)
        self.assertEqual(2, script.count("-- Scenario:"))


if __name__ == "__main__":
    unittest.main()
