from __future__ import annotations

from api_data_gen.config import Settings
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier


class DictRepository:
    def __init__(self, client: QueryClient, settings: Settings):
        self._client = client
        self._settings = settings

    def get_import_codes(self, type_code: str) -> list[str]:
        query = f"""
            SELECT code_value
            FROM {quote_identifier(self._settings.trace_schema)}.t_aml_f_import_info
            WHERE type_code = %s
            ORDER BY id
        """
        return [str(row["code_value"]) for row in self._client.fetch_all(query, (type_code,))]

    def get_mapping_columns(self, db_col: str) -> list[str]:
        query = f"""
            SELECT mapping_col
            FROM {quote_identifier(self._settings.trace_schema)}.t_aml_sys_dict_info
            WHERE sys_id = %s AND status = '1' AND db_col = %s
            ORDER BY id
        """
        return [str(row["mapping_col"]) for row in self._client.fetch_all(query, (self._settings.sys_id, db_col))]

    def get_sys_codes(self, mapping_col: str) -> list[str]:
        query = f"""
            SELECT code_value
            FROM {quote_identifier(self._settings.business_schema)}.aml_f_sys_dict
            WHERE type_code = %s
            ORDER BY id
        """
        return [str(row["code_value"]) for row in self._client.fetch_all(query, (mapping_col,))]

    def search_codes(self, type_code_like: str, type_name_like: str) -> list[str]:
        query = f"""
            SELECT code_value
            FROM {quote_identifier(self._settings.business_schema)}.aml_f_sys_dict
            WHERE type_code IN (
                SELECT code
                FROM {quote_identifier(self._settings.business_schema)}.aml_f_sys_dict_type
                WHERE code LIKE %s AND code_name LIKE %s
            )
            ORDER BY id
        """
        params = (f"%{type_code_like}%", f"%{type_name_like}%")
        return [str(row["code_value"]) for row in self._client.fetch_all(query, params)]
