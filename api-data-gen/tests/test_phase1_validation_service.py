from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import InterfaceInfo, SqlInfo, TableColumn, TableSchema
from api_data_gen.services.phase1_validation_service import Phase1ValidationService


class _FakeInterfaceTraceService:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_table_info(self, api_name: str, api_path: str) -> InterfaceInfo:
        return self._mapping[api_path]


class _FakeSchemaRepository:
    def get_table_schema(self, table_name: str) -> TableSchema:
        return TableSchema(
            table_name=table_name,
            table_type="innodb",
            columns=[
                TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
            ],
            primary_keys=["uuid"],
        )


class _FakeSampleRepository:
    def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
        return [{"uuid": f"{table_name}-1", "cust_id": "962020122711000002"}][:limit]


class _FakeDictRuleResolver:
    def __init__(self, values: list[str]):
        self._values = values

    def resolve_code_values(self, column_name: str, column_comment: str) -> list[str]:
        return list(self._values)


class Phase1ValidationServiceTest(unittest.TestCase):
    def test_validate_reports_success_for_complete_phase1_chain(self) -> None:
        interface_service = _FakeInterfaceTraceService(
            {
                "/wst/custTransInfo": InterfaceInfo(
                    name="custTransInfo",
                    path="/wst/custTransInfo",
                    sql_infos=[
                        SqlInfo("aml_f_tidb_model_result", ["cust_id = 'x'"]),
                        SqlInfo("aml_f_wst_alert_cust_trans_info", ["alert_date = '2020-12-20'"]),
                    ],
                ),
                "/wst/custDrftRecord": InterfaceInfo(
                    name="custDrftRecord",
                    path="/wst/custDrftRecord",
                    sql_infos=[
                        SqlInfo("aml_f_tidb_model_result", ["cust_id = 'x'"]),
                        SqlInfo("aml_f_wst_alert_cust_drft_record", ["alert_date = '2020-12-20'"]),
                    ],
                ),
            }
        )

        service = Phase1ValidationService(
            interface_service,
            _FakeSchemaRepository(),
            _FakeSampleRepository(),
            _FakeDictRuleResolver(["01", "02"]),
        )

        report = service.validate(sample_limit=1)

        self.assertTrue(report["success"])
        self.assertEqual(["01", "02"], report["dict_values"])
        self.assertEqual(2, len(report["interfaces"]))
        self.assertIn("aml_f_tidb_model_result", report["schemas"])
        self.assertIn("aml_f_wst_alert_cust_trans_info", report["samples"])
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_validate_reports_failures_when_chain_is_incomplete(self) -> None:
        interface_service = _FakeInterfaceTraceService(
            {
                "/wst/custTransInfo": InterfaceInfo(
                    name="custTransInfo",
                    path="/wst/custTransInfo",
                    sql_infos=[],
                ),
                "/wst/custDrftRecord": InterfaceInfo(
                    name="custDrftRecord",
                    path="/wst/custDrftRecord",
                    sql_infos=[SqlInfo("aml_f_tidb_model_result", [])],
                ),
            }
        )

        service = Phase1ValidationService(
            interface_service,
            _FakeSchemaRepository(),
            _FakeSampleRepository(),
            _FakeDictRuleResolver([]),
        )

        report = service.validate(sample_limit=1)

        self.assertFalse(report["success"])
        failed_checks = [check for check in report["checks"] if not check["passed"]]
        self.assertGreaterEqual(len(failed_checks), 2)


if __name__ == "__main__":
    unittest.main()
