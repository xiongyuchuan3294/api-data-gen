from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.services.sql_parser import SqlParser


class SqlParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SqlParser()

    def test_extract_sql_info(self) -> None:
        sql = (
            "SELECT uuid,result_key,model_key FROM aml_f_tidb_model_result "
            "WHERE (cust_id = ''962020122711000002'' AND result_date <= ''2020-12-27'' "
            "AND model_key = ''WSTY001'')"
        )
        info = self.parser.extract_sql_info(sql)
        self.assertEqual("aml_f_tidb_model_result", info.table_name)
        self.assertEqual(
            [
                "(cust_id = ''962020122711000002''",
                "result_date <= ''2020-12-27''",
                "model_key = ''WSTY001'')",
            ],
            info.conditions,
        )

    def test_count_query_is_detected(self) -> None:
        self.assertTrue(self.parser.is_count_query("SELECT COUNT(*) FROM aml_f_wst_alert_cust_trans_info"))
        self.assertFalse(self.parser.is_count_query("SELECT uuid FROM aml_f_wst_alert_cust_trans_info"))


if __name__ == "__main__":
    unittest.main()
