from __future__ import annotations

from api_data_gen.config import Settings
from api_data_gen.domain.models import DatabaseOperation, TraceRequest
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier


class TraceRepository:
    def __init__(self, client: QueryClient, settings: Settings):
        self._client = client
        self._settings = settings

    def find_latest_request(self, url_prefix: str) -> TraceRequest | None:
        schema_name = quote_identifier(self._settings.trace_schema)
        query = f"""
            SELECT trace_id, url, method, request_body, query_params, status_code, start_time, end_time
            FROM {schema_name}.t_request_info
            WHERE url LIKE %s
            ORDER BY update_time
            LIMIT 1
        """
        row = self._client.fetch_one(query, (f"{url_prefix}%",))
        if row is None:
            return None
        return TraceRequest(
            trace_id=str(row["trace_id"]),
            url=str(row["url"]),
            method=str(row["method"]),
            request_body=row.get("request_body"),
            query_params=row.get("query_params"),
            status_code=row.get("status_code"),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
        )

    def list_operations(self, trace_id: str) -> list[DatabaseOperation]:
        schema_name = quote_identifier(self._settings.trace_schema)
        query = f"""
            SELECT trace_id, sequence, sql_text, operation_type, parameters, result_rows, query_result_data
            FROM {schema_name}.t_database_operation
            WHERE trace_id = %s
            ORDER BY sequence ASC
        """
        rows = self._client.fetch_all(query, (trace_id,))
        return [
            DatabaseOperation(
                trace_id=str(row["trace_id"]),
                sequence=int(row["sequence"]),
                sql_text=str(row["sql_text"]),
                operation_type=str(row["operation_type"]),
                parameters=row.get("parameters"),
                result_rows=row.get("result_rows"),
                query_result_data=row.get("query_result_data"),
            )
            for row in rows
        ]
