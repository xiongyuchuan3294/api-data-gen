from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import GeneratedRow, TableColumn, TableSchema
from api_data_gen.services.record_validation_service import RecordValidationService


class RecordValidationServiceTest(unittest.TestCase):
    def test_validate_table_truncates_and_fills_required_values(self) -> None:
        service = RecordValidationService()
        schema = TableSchema(
            table_name="demo_table",
            table_type="innodb",
            columns=[
                TableColumn("name", "varchar(4)", False, None, "", False, False, 4),
                TableColumn("biz_date", "date", False, None, "", False, False, 10),
            ],
            primary_keys=[],
        )

        rows, checks = service.validate_table(
            schema,
            [GeneratedRow(values={"name": "ABCDEFG", "biz_date": None})],
            check_prefix="record_validation:demo_table",
        )

        self.assertEqual("ABCD", rows[0].values["name"])
        self.assertEqual("1970-01-01", rows[0].values["biz_date"])
        self.assertEqual(1, len(checks))
        self.assertIn("truncated", checks[0].detail)
        self.assertIn("filled runtime default", checks[0].detail)


if __name__ == "__main__":
    unittest.main()
