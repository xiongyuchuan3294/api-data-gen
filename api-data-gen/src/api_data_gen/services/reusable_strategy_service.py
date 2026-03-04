from __future__ import annotations

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    StoredFieldStrategy,
    StoredRelationStrategy,
)

_GENERIC_GENERATORS = {
    "customer_id",
    "transaction_key",
    "model_seq_blank",
    "copy_from_field",
    "copy_from_context",
    "concat_template",
    "date_format_from_field",
}
_CONDITIONAL_GENERIC_GENERATORS = {
    "dictionary_cycle",
    "sequence_cycle",
}
_NON_GENERIC_GENERATORS = {
    "",
    "ai_value",
    "fixed_value",
    "condition_value",
    "sample_cycle",
    "generated_value",
    "default_value",
    "fallback_value",
    "local_rule",
    "null",
    "datetime_range_cycle",
    "amount_pattern_cycle",
}


class ReusableStrategyService:
    def __init__(self, repository):
        self._repository = repository

    def load_table_advice(
        self,
        table_name: str,
        available_tables: list[str] | None = None,
    ) -> AiTableGenerationAdvice:
        advice = AiTableGenerationAdvice(table_name=table_name)
        for record in self._repository.list_field_strategies([table_name]):
            if record.table_name != table_name:
                continue
            advice.field_strategies[record.field_name] = record.strategy.executor
            advice.field_generation_strategies[record.field_name] = record.strategy
        return advice

    def list_relation_strategies(self, available_tables: list[str]) -> list[StoredRelationStrategy]:
        return self._repository.list_relation_strategies(available_tables)

    def save_generic_field_strategies(self, table_name: str, advice: AiTableGenerationAdvice) -> None:
        records: list[StoredFieldStrategy] = []
        for field_name, strategy in advice.field_generation_strategies.items():
            if not _is_generic_field_strategy(field_name, strategy):
                continue
            records.append(
                StoredFieldStrategy(
                    table_name=table_name,
                    field_name=field_name,
                    strategy=strategy,
                    strategy_source="ai_generic",
                )
            )
        if records:
            self._repository.save_field_strategies(records)

    def save_relation_strategies(self, strategies: list[StoredRelationStrategy]) -> None:
        records = [
            record
            for record in strategies
            if record.target_table and record.target_field and record.source_table and record.source_field
        ]
        if records:
            self._repository.save_relation_strategies(records)


def _is_generic_field_strategy(field_name: str, strategy: FieldGenerationStrategy) -> bool:
    if strategy.executor != "local":
        return False
    generator = (strategy.generator or "").strip().lower()
    if generator in _NON_GENERIC_GENERATORS:
        return False
    if generator in _GENERIC_GENERATORS:
        return True
    if generator == "dictionary_cycle":
        values = strategy.params.get("values")
        if not isinstance(values, list):
            return False
        if len(values) > 10:
            return False
        return field_name.lower().endswith(("_cd", "_type", "_flag", "_status"))
    if generator == "sequence_cycle":
        values = strategy.params.get("values")
        if values in {None, ""}:
            return True
        if not isinstance(values, list):
            return False
        return bool(values) and all(str(item).isdigit() and len(str(item)) <= 8 for item in values)
    return False
