from __future__ import annotations

from dataclasses import asdict


_PHASE1_INTERFACES = (
    ("custTransInfo", "/wst/custTransInfo", ("aml_f_tidb_model_result", "aml_f_wst_alert_cust_trans_info")),
    ("custDrftRecord", "/wst/custDrftRecord", ("aml_f_tidb_model_result", "aml_f_wst_alert_cust_drft_record")),
)

_PHASE1_TABLES = (
    "aml_f_tidb_model_result",
    "aml_f_wst_alert_cust_trans_info",
    "aml_f_wst_alert_cust_drft_record",
)


class Phase1ValidationService:
    def __init__(self, interface_trace_service, schema_repository, sample_repository, dict_rule_resolver):
        self._interface_trace_service = interface_trace_service
        self._schema_repository = schema_repository
        self._sample_repository = sample_repository
        self._dict_rule_resolver = dict_rule_resolver

    def validate(self, sample_limit: int = 2) -> dict[str, object]:
        checks: list[dict[str, object]] = []
        interfaces = []

        for api_name, api_path, expected_tables in _PHASE1_INTERFACES:
            interface_info = self._interface_trace_service.get_table_info(api_name, api_path)
            interfaces.append(interface_info)

            extracted_tables = {sql_info.table_name for sql_info in interface_info.sql_infos}
            checks.append(
                _make_check(
                    name=f"{api_path}:trace",
                    passed=bool(interface_info.sql_infos),
                    detail=f"extracted {len(interface_info.sql_infos)} SQL statement(s)",
                )
            )

            missing_tables = [table for table in expected_tables if table not in extracted_tables]
            checks.append(
                _make_check(
                    name=f"{api_path}:tables",
                    passed=not missing_tables,
                    detail=(
                        f"missing expected tables: {', '.join(missing_tables)}"
                        if missing_tables
                        else f"tables: {', '.join(sorted(extracted_tables))}"
                    ),
                )
            )

        schemas: dict[str, dict[str, object]] = {}
        samples: dict[str, list[dict[str, str]]] = {}
        for table_name in _PHASE1_TABLES:
            try:
                schema = self._schema_repository.get_table_schema(table_name)
            except Exception as exc:
                checks.append(_make_check(f"{table_name}:schema", False, str(exc)))
            else:
                schemas[table_name] = asdict(schema)
                checks.append(
                    _make_check(
                        name=f"{table_name}:schema",
                        passed=True,
                        detail=f"{len(schema.columns)} column(s), primary keys: {schema.primary_keys}",
                    )
                )

            try:
                sample_rows = self._sample_repository.sample_rows(table_name, sample_limit)
            except Exception as exc:
                checks.append(_make_check(f"{table_name}:sample", False, str(exc)))
            else:
                samples[table_name] = sample_rows
                checks.append(
                    _make_check(
                        name=f"{table_name}:sample",
                        passed=bool(sample_rows),
                        detail=f"{len(sample_rows)} sample row(s)",
                    )
                )

        try:
            dict_values = self._dict_rule_resolver.resolve_code_values("receive_pay_cd", "资金收付表示")
        except Exception as exc:
            dict_values = []
            checks.append(_make_check("receive_pay_cd:dict", False, str(exc)))
        else:
            checks.append(
                _make_check(
                    name="receive_pay_cd:dict",
                    passed=bool(dict_values),
                    detail=f"values: {', '.join(dict_values) if dict_values else '[EMPTY]'}",
                )
            )

        return {
            "success": all(bool(check["passed"]) for check in checks),
            "checks": checks,
            "interfaces": [asdict(interface_info) for interface_info in interfaces],
            "schemas": schemas,
            "samples": samples,
            "dict_values": dict_values,
        }


def _make_check(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
    }
