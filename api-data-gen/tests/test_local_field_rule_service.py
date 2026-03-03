from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import TableColumn, TableSchema
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService


class _FakeDictRuleResolver:
    def resolve_code_values(self, column_name: str, column_comment: str) -> list[str]:
        if column_name == "receive_pay_cd":
            return ["01", "02"]
        return []


class LocalFieldRuleServiceTest(unittest.TestCase):
    def test_identify_and_generate_local_rule_fields(self) -> None:
        service = LocalFieldRuleService(_FakeDictRuleResolver())
        schema = TableSchema(
            table_name="demo_table",
            table_type="innodb",
            columns=[
                TableColumn("receive_pay_cd", "varchar(2)", True, None, "资金收付表示", False, False, 2),
                TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18),
                TableColumn("transactionkey", "varchar(64)", True, None, "交易流水号", False, False, 64),
                TableColumn("model_seq", "longtext", True, None, "模型树结果序列化", False, False, 0),
            ],
            primary_keys=[],
        )

        local_fields = service.identify_local_fields(schema)

        self.assertEqual({"receive_pay_cd", "cust_id", "transactionkey", "model_seq"}, local_fields)
        self.assertEqual("01", service.generate_value(schema.columns[0], 0, "RUN20260302"))
        self.assertEqual("02", service.generate_value(schema.columns[0], 1, "RUN20260302"))
        self.assertEqual("962020122711000002", service.generate_value(schema.columns[1], 0, fixed_values={"cust_id": "962020122711000002"}))
        self.assertTrue(service.generate_value(schema.columns[2], 0, "RUN20260302").startswith("6008C20260302"))
        self.assertEqual("", service.generate_value(schema.columns[3], 0, "RUN20260302"))

    def test_generate_with_contextual_generators(self) -> None:
        service = LocalFieldRuleService()
        text_column = TableColumn("result_key", "varchar(128)", False, None, "", False, False, 128)
        date_column = TableColumn("ds", "varchar(8)", False, None, "", False, False, 8)
        seq_column = TableColumn("seq_no", "varchar(8)", False, None, "", False, False, 8)

        row_values = {
            "model_key": "WSTY001",
            "result_date": "2020-12-27",
            "cust_id": "962020122711000002",
            "alert_date": "2020-12-20",
        }
        scenario_context = {"drft_no": ["DRFT-001", "DRFT-002"]}

        self.assertEqual(
            "WSTY00120201227962020122711000002",
            service.generate_with_generator(
                text_column,
                "concat_template",
                {
                    "template": "{model_key}{result_date}{cust_id}",
                    "transforms": {"result_date": "date:%Y%m%d"},
                },
                0,
                row_values=row_values,
            ),
        )
        self.assertEqual(
            "20201220",
            service.generate_with_generator(
                date_column,
                "date_format_from_field",
                {"source_field": "alert_date", "output_format": "%Y%m%d"},
                0,
                row_values=row_values,
            ),
        )
        self.assertEqual(
            "DRFT-002",
            service.generate_with_generator(
                text_column,
                "copy_from_context",
                {"source_field": "drft_no"},
                1,
                scenario_context=scenario_context,
            ),
        )
        self.assertEqual(
            "07",
            service.generate_with_generator(
                seq_column,
                "sequence_cycle",
                {"values": ["08", "07", "10"]},
                1,
            ),
        )


if __name__ == "__main__":
    unittest.main()
