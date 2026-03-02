from __future__ import annotations

from api_data_gen.domain.models import ApplyResult, GeneratedTable, ValidationCheck


class SqlApplyService:
    def __init__(self, client):
        self._client = client

    def apply(
        self,
        generated_tables: list[GeneratedTable],
        validation_checks: list[ValidationCheck],
        force: bool = False,
    ) -> ApplyResult:
        failed_checks = [check for check in validation_checks if not check.passed]
        if failed_checks and not force:
            raise ValueError(
                "Refusing to apply SQL because validation failed: "
                + ", ".join(check.name for check in failed_checks)
            )

        statements_by_schema: dict[str, list[str]] = {}
        applied_tables: list[str] = []
        for generated_table in generated_tables:
            if not generated_table.insert_sql:
                continue
            schema_name, _ = self._client.resolve_table_location(generated_table.table_name)
            statements_by_schema.setdefault(schema_name, []).extend(generated_table.insert_sql)
            applied_tables.append(generated_table.table_name)

        for schema_name, statements in statements_by_schema.items():
            self._client.execute_statements(schema_name, statements)

        return ApplyResult(
            applied=True,
            forced=force,
            statement_count=sum(len(statements) for statements in statements_by_schema.values()),
            schemas=sorted(statements_by_schema),
            tables=applied_tables,
        )
