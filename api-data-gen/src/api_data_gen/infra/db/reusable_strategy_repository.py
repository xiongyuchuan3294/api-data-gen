from __future__ import annotations

import json

from api_data_gen.config import Settings
from api_data_gen.domain.models import FieldGenerationStrategy, StoredFieldStrategy, StoredRelationStrategy
from api_data_gen.infra.db.contracts import QueryClient
from api_data_gen.infra.db.mysql_client import quote_identifier, quote_literal


class ReusableStrategyRepository:
    def __init__(self, client: QueryClient, settings: Settings):
        self._client = client
        self._settings = settings
        self._ensured = False

    def list_field_strategies(self, table_names: list[str]) -> list[StoredFieldStrategy]:
        unique_tables = _deduplicate(table_names)
        if not unique_tables:
            return []
        self._ensure_tables()
        placeholders = ", ".join(["%s"] * len(unique_tables))
        schema_name = quote_identifier(self._settings.trace_schema)
        query = f"""
            SELECT table_name, field_name, executor, generator, params_json, fallback_generators_json,
                   rationale, implementation_hint, implementation_code, strategy_source
            FROM {schema_name}.reusable_field_strategies
            WHERE is_active = 1 AND table_name IN ({placeholders})
            ORDER BY table_name, field_name
        """
        return [
            StoredFieldStrategy(
                table_name=str(row["table_name"]),
                field_name=str(row["field_name"]),
                strategy=_build_strategy(row),
                strategy_source=str(row.get("strategy_source") or ""),
            )
            for row in self._client.fetch_all(query, tuple(unique_tables))
        ]

    def save_field_strategies(self, strategies: list[StoredFieldStrategy]) -> None:
        if not strategies:
            return
        self._ensure_tables()
        schema_name = quote_identifier(self._settings.trace_schema)
        statements: list[str] = []
        for item in strategies:
            params_json = json.dumps(item.strategy.params, ensure_ascii=False, sort_keys=True)
            fallbacks_json = json.dumps(item.strategy.fallback_generators, ensure_ascii=False)
            statements.append(
                f"""
                INSERT INTO {schema_name}.reusable_field_strategies
                (
                    table_name, field_name, executor, generator, params_json, fallback_generators_json,
                    rationale, implementation_hint, implementation_code, strategy_source, use_count, is_active
                )
                VALUES (
                    {quote_literal(item.table_name)},
                    {quote_literal(item.field_name)},
                    {quote_literal(item.strategy.executor)},
                    {quote_literal(item.strategy.generator)},
                    {quote_literal(params_json)},
                    {quote_literal(fallbacks_json)},
                    {quote_literal(item.strategy.rationale)},
                    {quote_literal(item.strategy.implementation_hint)},
                    {quote_literal(item.strategy.implementation_code)},
                    {quote_literal(item.strategy_source or "ai")},
                    1,
                    1
                )
                ON DUPLICATE KEY UPDATE
                    executor = VALUES(executor),
                    generator = VALUES(generator),
                    params_json = VALUES(params_json),
                    fallback_generators_json = VALUES(fallback_generators_json),
                    rationale = VALUES(rationale),
                    implementation_hint = VALUES(implementation_hint),
                    implementation_code = VALUES(implementation_code),
                    strategy_source = VALUES(strategy_source),
                    use_count = use_count + 1,
                    last_used_at = CURRENT_TIMESTAMP,
                    is_active = 1
                """.strip()
            )
        self._client.execute_statements(self._settings.trace_schema, statements)

    def list_relation_strategies(self, table_names: list[str]) -> list[StoredRelationStrategy]:
        unique_tables = _deduplicate(table_names)
        if not unique_tables:
            return []
        self._ensure_tables()
        placeholders = ", ".join(["%s"] * len(unique_tables))
        schema_name = quote_identifier(self._settings.trace_schema)
        query = f"""
            SELECT target_table, target_field, source_table, source_field,
                   executor, generator, params_json, fallback_generators_json,
                   rationale, implementation_hint, implementation_code,
                   relation_reason, strategy_source
            FROM {schema_name}.reusable_relation_strategies
            WHERE is_active = 1 AND (target_table IN ({placeholders}) OR source_table IN ({placeholders}))
            ORDER BY target_table, target_field, source_table, source_field
        """
        params = tuple(unique_tables + unique_tables)
        return [
            StoredRelationStrategy(
                target_table=str(row["target_table"]),
                target_field=str(row["target_field"]),
                source_table=str(row["source_table"]),
                source_field=str(row["source_field"]),
                strategy=_build_strategy(row),
                relation_reason=str(row.get("relation_reason") or ""),
                strategy_source=str(row.get("strategy_source") or ""),
            )
            for row in self._client.fetch_all(query, params)
        ]

    def save_relation_strategies(self, strategies: list[StoredRelationStrategy]) -> None:
        if not strategies:
            return
        self._ensure_tables()
        schema_name = quote_identifier(self._settings.trace_schema)
        statements: list[str] = []
        for item in strategies:
            params_json = json.dumps(item.strategy.params, ensure_ascii=False, sort_keys=True)
            fallbacks_json = json.dumps(item.strategy.fallback_generators, ensure_ascii=False)
            statements.append(
                f"""
                INSERT INTO {schema_name}.reusable_relation_strategies
                (
                    target_table, target_field, source_table, source_field,
                    executor, generator, params_json, fallback_generators_json,
                    rationale, implementation_hint, implementation_code,
                    relation_reason, strategy_source, use_count, is_active
                )
                VALUES (
                    {quote_literal(item.target_table)},
                    {quote_literal(item.target_field)},
                    {quote_literal(item.source_table)},
                    {quote_literal(item.source_field)},
                    {quote_literal(item.strategy.executor)},
                    {quote_literal(item.strategy.generator)},
                    {quote_literal(params_json)},
                    {quote_literal(fallbacks_json)},
                    {quote_literal(item.strategy.rationale)},
                    {quote_literal(item.strategy.implementation_hint)},
                    {quote_literal(item.strategy.implementation_code)},
                    {quote_literal(item.relation_reason)},
                    {quote_literal(item.strategy_source or "field_match")},
                    1,
                    1
                )
                ON DUPLICATE KEY UPDATE
                    executor = VALUES(executor),
                    generator = VALUES(generator),
                    params_json = VALUES(params_json),
                    fallback_generators_json = VALUES(fallback_generators_json),
                    rationale = VALUES(rationale),
                    implementation_hint = VALUES(implementation_hint),
                    implementation_code = VALUES(implementation_code),
                    relation_reason = VALUES(relation_reason),
                    strategy_source = VALUES(strategy_source),
                    use_count = use_count + 1,
                    last_used_at = CURRENT_TIMESTAMP,
                    is_active = 1
                """.strip()
            )
        self._client.execute_statements(self._settings.trace_schema, statements)

    def _ensure_tables(self) -> None:
        if self._ensured:
            return
        schema_name = quote_identifier(self._settings.trace_schema)
        statements = [
            f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.reusable_field_strategies (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                table_name VARCHAR(128) NOT NULL,
                field_name VARCHAR(128) NOT NULL,
                executor VARCHAR(16) NOT NULL,
                generator VARCHAR(64) NOT NULL,
                params_json TEXT NULL,
                fallback_generators_json TEXT NULL,
                rationale VARCHAR(512) NULL,
                implementation_hint TEXT NULL,
                implementation_code MEDIUMTEXT NULL,
                strategy_source VARCHAR(32) NOT NULL DEFAULT 'ai',
                use_count INT NOT NULL DEFAULT 1,
                last_used_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                UNIQUE KEY uk_reusable_field_strategy (table_name, field_name)
            )
            """.strip(),
            f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.reusable_relation_strategies (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                target_table VARCHAR(128) NOT NULL,
                target_field VARCHAR(128) NOT NULL,
                source_table VARCHAR(128) NOT NULL,
                source_field VARCHAR(128) NOT NULL,
                executor VARCHAR(16) NOT NULL,
                generator VARCHAR(64) NOT NULL,
                params_json TEXT NULL,
                fallback_generators_json TEXT NULL,
                rationale VARCHAR(512) NULL,
                implementation_hint TEXT NULL,
                implementation_code MEDIUMTEXT NULL,
                relation_reason VARCHAR(512) NULL,
                strategy_source VARCHAR(32) NOT NULL DEFAULT 'field_match',
                use_count INT NOT NULL DEFAULT 1,
                last_used_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                UNIQUE KEY uk_reusable_relation_strategy (target_table, target_field, source_table, source_field)
            )
            """.strip(),
        ]
        self._client.execute_statements(self._settings.trace_schema, statements)
        self._ensured = True


def _build_strategy(row: dict[str, object]) -> FieldGenerationStrategy:
    params = _parse_json_object(row.get("params_json"))
    fallbacks = _parse_json_list(row.get("fallback_generators_json"))
    return FieldGenerationStrategy(
        executor=str(row.get("executor") or "local"),
        generator=str(row.get("generator") or ""),
        params=params,
        fallback_generators=fallbacks,
        rationale=str(row.get("rationale") or ""),
        implementation_hint=str(row.get("implementation_hint") or ""),
        implementation_code=str(row.get("implementation_code") or ""),
    )


def _parse_json_object(value: object) -> dict[str, object]:
    if value in {None, ""}:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_json_list(value: object) -> list[str]:
    if value in {None, ""}:
        return []
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def _deduplicate(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
