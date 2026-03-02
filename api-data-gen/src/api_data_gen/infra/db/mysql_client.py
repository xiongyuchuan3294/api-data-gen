from __future__ import annotations

from typing import Any
import re

import pymysql
from pymysql.cursors import DictCursor

from api_data_gen.config import Settings

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def quote_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f"`{name}`"


class MysqlClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _connect(self) -> pymysql.Connection:
        return pymysql.connect(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_user,
            password=self._settings.mysql_password,
            charset=self._settings.mysql_charset,
            cursorclass=DictCursor,
            autocommit=True,
        )

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return list(cursor.fetchall())

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.fetch_all(query, params)
        return rows[0] if rows else None

    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        if "." in table_name:
            schema_name, local_name = table_name.split(".", 1)
            return schema_name, local_name

        support_tables = {
            "t_request_info",
            "t_database_operation",
            "field_match_relations",
            "t_aml_sys_dict_info",
            "t_aml_f_import_info",
        }
        if table_name in support_tables:
            return self._settings.trace_schema, table_name

        query = """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN (%s, %s) AND table_name = %s
            ORDER BY FIELD(table_schema, %s, %s)
            LIMIT 1
        """
        row = self.fetch_one(
            query,
            (
                self._settings.trace_schema,
                self._settings.business_schema,
                table_name,
                self._settings.business_schema,
                self._settings.trace_schema,
            ),
        )
        if row is None:
            raise ValueError(f"Table not found in configured schemas: {table_name}")
        return str(row["table_schema"]), str(row["table_name"])
