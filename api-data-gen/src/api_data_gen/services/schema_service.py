from __future__ import annotations

from api_data_gen.domain.models import InterfaceInfo, TableSchema


class SchemaService:
    def __init__(self, schema_repository):
        self._schema_repository = schema_repository

    def get_all_table_schemas(self, interface_infos: list[InterfaceInfo]) -> dict[str, TableSchema]:
        table_names: list[str] = []
        seen: set[str] = set()
        for interface_info in interface_infos:
            for sql_info in interface_info.sql_infos:
                if sql_info.table_name not in seen:
                    seen.add(sql_info.table_name)
                    table_names.append(sql_info.table_name)

        return {
            table_name: self._schema_repository.get_table_schema(table_name)
            for table_name in table_names
        }
