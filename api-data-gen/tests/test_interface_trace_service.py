from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.domain.models import DatabaseOperation, TraceRequest
from api_data_gen.services.interface_trace_service import InterfaceTraceService
from api_data_gen.services.sql_parser import SqlParser


class _FakeTraceRepository:
    def find_latest_request(self, url_prefix: str) -> TraceRequest | None:
        if url_prefix.endswith("/wst/custTransInfo"):
            return TraceRequest(trace_id="trace-1", url=url_prefix, method="POST")
        return None

    def list_operations(self, trace_id: str) -> list[DatabaseOperation]:
        return [
            DatabaseOperation(
                trace_id=trace_id,
                sequence=1,
                sql_text="SELECT COUNT(*) AS total FROM aml_f_wst_alert_cust_trans_info",
                operation_type="SELECT",
            ),
            DatabaseOperation(
                trace_id=trace_id,
                sequence=2,
                sql_text="SELECT uuid FROM aml_f_sys_dict WHERE type_code = ''receive_pay''",
                operation_type="SELECT",
            ),
            DatabaseOperation(
                trace_id=trace_id,
                sequence=3,
                sql_text=(
                    "SELECT uuid,model_key FROM aml_f_wst_alert_cust_trans_info "
                    "WHERE (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'')"
                ),
                operation_type="SELECT",
            ),
            DatabaseOperation(
                trace_id=trace_id,
                sequence=4,
                sql_text=(
                    "SELECT uuid,model_key FROM aml_f_wst_alert_cust_trans_info "
                    "WHERE (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'')"
                ),
                operation_type="SELECT",
            ),
        ]


class InterfaceTraceServiceTest(unittest.TestCase):
    def test_get_table_info_filters_count_system_tables_and_duplicates(self) -> None:
        service = InterfaceTraceService(_FakeTraceRepository(), SqlParser(), Settings())
        info = service.get_table_info("预警日期近1个月交易展示", "/wst/custTransInfo")

        self.assertEqual("预警日期近1个月交易展示", info.name)
        self.assertEqual("/wst/custTransInfo", info.path)
        self.assertEqual(1, len(info.sql_infos))
        self.assertEqual("aml_f_wst_alert_cust_trans_info", info.sql_infos[0].table_name)

    def test_get_table_info_handles_missing_trace(self) -> None:
        service = InterfaceTraceService(_FakeTraceRepository(), SqlParser(), Settings())
        info = service.get_table_info("missing", "/wst/missing")
        self.assertEqual([], info.sql_infos)


if __name__ == "__main__":
    unittest.main()
