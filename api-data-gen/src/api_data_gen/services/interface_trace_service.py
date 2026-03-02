from __future__ import annotations

from api_data_gen.config import Settings
from api_data_gen.domain.models import InterfaceInfo
from api_data_gen.services.sql_parser import SqlParser

_FILTERED_TABLES = {
    "aml_f_sys_dict",
    "aml_f_batch_config",
    "aml_f_sys_role_permission",
    "aml_f_sys_permission",
    "aml_f_sys_user_role",
}


class InterfaceTraceService:
    def __init__(self, trace_repository, sql_parser: SqlParser, settings: Settings):
        self._trace_repository = trace_repository
        self._sql_parser = sql_parser
        self._settings = settings

    def get_table_info(self, api_name: str, api_path: str) -> InterfaceInfo:
        url_prefix = f"{self._settings.system_base_url}{api_path}"
        trace_request = self._trace_repository.find_latest_request(url_prefix)
        if trace_request is None:
            return InterfaceInfo(name=api_name, path=api_path, sql_infos=[])

        seen_sql_texts: set[str] = set()
        sql_infos = []
        for operation in self._trace_repository.list_operations(trace_request.trace_id):
            if operation.sql_text in seen_sql_texts:
                continue
            seen_sql_texts.add(operation.sql_text)

            if self._sql_parser.is_count_query(operation.sql_text):
                continue

            sql_info = self._sql_parser.extract_sql_info(operation.sql_text)
            if sql_info.table_name.lower() in _FILTERED_TABLES:
                continue
            sql_infos.append(sql_info)

        return InterfaceInfo(name=api_name, path=api_path, sql_infos=sql_infos)
