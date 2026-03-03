from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    FieldGenerationStrategy,
    GenerationReport,
    GeneratedTable,
)
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService

_GENERIC_GENERATORS = {
    "",
    "ai_value",
    "condition_value",
    "default_value",
    "dictionary_cycle",
    "fallback_value",
    "fixed_value",
    "generated_value",
    "null",
    "sample_cycle",
}


class StrategyExportService:
    def load_field_decisions(self, path: str | Path) -> dict[str, AiTableGenerationAdvice]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = _extract_strategy_entries(payload)
        decisions: dict[str, AiTableGenerationAdvice] = {}

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            table_name = str(entry.get("table_name") or entry.get("table") or "").strip()
            if not table_name:
                continue
            raw_labels = entry.get("field_strategies")
            raw_generation_strategies = entry.get("field_generation_strategies")
            field_generation_strategies = _normalize_field_generation_strategies(raw_generation_strategies)
            field_strategies = _normalize_field_strategies(raw_labels)
            for field_name, strategy in field_generation_strategies.items():
                field_strategies.setdefault(field_name, "ai" if strategy.executor == "ai" else "local")

            loaded = AiTableGenerationAdvice(
                table_name=table_name,
                field_strategies=field_strategies,
                field_generation_strategies=field_generation_strategies,
            )
            current = decisions.get(table_name)
            decisions[table_name] = _merge_loaded_advice(current, loaded) if current is not None else loaded

        return decisions

    def render_strategy_config(
        self,
        report: GenerationReport,
        strategy_mode: str,
        generated_at: str = "",
        source_result_file: str = "",
    ) -> dict[str, object]:
        return {
            "version": 1,
            "strategy_mode": strategy_mode,
            "generated_at": generated_at,
            "generation_tag": report.generation_tag,
            "source_result_file": source_result_file,
            "requirement_summary": report.requirement.summary,
            "table_strategy_count": len(report.generated_tables),
            "table_strategies": [
                self._render_table_strategy(generated_table)
                for generated_table in report.generated_tables
            ],
        }

    def render_generator_candidates(
        self,
        report: GenerationReport,
        strategy_mode: str,
        generated_at: str = "",
        source_result_file: str = "",
        source_strategy_file: str = "",
    ) -> dict[str, object]:
        candidates: dict[tuple[str, ...], dict[str, object]] = {}
        supported_generators = LocalFieldRuleService.supported_generators()

        for generated_table in report.generated_tables:
            for field_name, strategy in generated_table.field_generation_strategies.items():
                if not self._has_candidate_payload(strategy):
                    continue
                suggested_generator_code = _suggested_generator_code(field_name, strategy.generator)
                signature = self._candidate_signature(
                    generated_table=generated_table,
                    field_name=field_name,
                    strategy=strategy,
                    suggested_generator_code=suggested_generator_code,
                )
                scenario_ref = {
                    "scenario_id": generated_table.scenario_id,
                    "scenario_title": generated_table.scenario_title,
                }
                if signature not in candidates:
                    candidates[signature] = {
                        "candidate_id": _candidate_id(
                            generated_table.table_name,
                            field_name,
                            suggested_generator_code,
                            signature,
                        ),
                        "table_name": generated_table.table_name,
                        "field_name": field_name,
                        "suggested_generator_code": suggested_generator_code,
                        "current_executor": strategy.executor,
                        "current_generator": strategy.generator,
                        "params": dict(strategy.params),
                        "fallback_generators": list(strategy.fallback_generators),
                        "rationale": strategy.rationale,
                        "implementation_hint": strategy.implementation_hint,
                        "implementation_code": strategy.implementation_code,
                        "local_generator_exists": suggested_generator_code in supported_generators,
                        "review_status": "pending_review",
                        "scenario_refs": [scenario_ref],
                    }
                    continue
                if scenario_ref not in candidates[signature]["scenario_refs"]:
                    candidates[signature]["scenario_refs"].append(scenario_ref)

        candidate_list = sorted(
            candidates.values(),
            key=lambda item: (
                str(item["table_name"]),
                str(item["field_name"]),
                str(item["suggested_generator_code"]),
                str(item["candidate_id"]),
            ),
        )

        return {
            "version": 1,
            "strategy_mode": strategy_mode,
            "generated_at": generated_at,
            "generation_tag": report.generation_tag,
            "source_result_file": source_result_file,
            "source_strategy_file": source_strategy_file,
            "supported_generators": supported_generators,
            "candidate_count": len(candidate_list),
            "candidates": candidate_list,
        }

    @staticmethod
    def _render_table_strategy(generated_table: GeneratedTable) -> dict[str, object]:
        return {
            "scenario_id": generated_table.scenario_id,
            "scenario_title": generated_table.scenario_title,
            "table_name": generated_table.table_name,
            "generation_source": generated_table.generation_source,
            "field_generation_strategies": {
                field_name: asdict(strategy)
                for field_name, strategy in sorted(generated_table.field_generation_strategies.items())
            },
        }

    @staticmethod
    def _has_candidate_payload(strategy: FieldGenerationStrategy) -> bool:
        return bool(strategy.implementation_hint.strip() or strategy.implementation_code.strip())

    @staticmethod
    def _candidate_signature(
        generated_table: GeneratedTable,
        field_name: str,
        strategy: FieldGenerationStrategy,
        suggested_generator_code: str,
    ) -> tuple[str, ...]:
        return (
            generated_table.table_name,
            field_name,
            strategy.executor,
            strategy.generator,
            suggested_generator_code,
            json.dumps(strategy.params, ensure_ascii=False, sort_keys=True),
            json.dumps(strategy.fallback_generators, ensure_ascii=False),
            strategy.rationale,
            strategy.implementation_hint,
            strategy.implementation_code,
        )


def _suggested_generator_code(field_name: str, current_generator: str) -> str:
    normalized_current = _normalize_generator_code(current_generator)
    if normalized_current and normalized_current not in _GENERIC_GENERATORS:
        return normalized_current
    normalized_field = _normalize_generator_code(field_name)
    return normalized_field or "custom_generator"


def _normalize_generator_code(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def _candidate_id(
    table_name: str,
    field_name: str,
    suggested_generator_code: str,
    signature: tuple[str, ...],
) -> str:
    digest = hashlib.sha1("|".join(signature).encode("utf-8")).hexdigest()[:8]
    return f"{table_name}.{field_name}.{suggested_generator_code}.{digest}"


def _extract_strategy_entries(payload: object) -> list[object]:
    if isinstance(payload, dict):
        if isinstance(payload.get("table_strategies"), list):
            return list(payload["table_strategies"])
        if isinstance(payload.get("generated_tables"), list):
            return list(payload["generated_tables"])
    if isinstance(payload, list):
        return list(payload)
    raise ValueError("Strategy file must contain table_strategies or generated_tables.")


def _normalize_field_strategies(raw_data: object) -> dict[str, str]:
    if not isinstance(raw_data, dict):
        return {}
    normalized: dict[str, str] = {}
    for field_name, raw_value in raw_data.items():
        decision = str(raw_value or "").strip().lower()
        if decision in {"ai", "local"}:
            normalized[str(field_name)] = decision
    return normalized


def _normalize_field_generation_strategies(raw_data: object) -> dict[str, FieldGenerationStrategy]:
    if not isinstance(raw_data, dict):
        return {}
    normalized: dict[str, FieldGenerationStrategy] = {}
    for field_name, raw_strategy in raw_data.items():
        if not isinstance(raw_strategy, dict):
            continue
        normalized[str(field_name)] = FieldGenerationStrategy(
            executor=_normalize_executor(raw_strategy.get("executor")),
            generator=str(raw_strategy.get("generator") or "").strip(),
            params=_normalize_params(raw_strategy.get("params")),
            fallback_generators=_normalize_fallback_generators(raw_strategy.get("fallback_generators")),
            rationale=str(raw_strategy.get("rationale") or "").strip(),
            implementation_hint=str(raw_strategy.get("implementation_hint") or "").strip(),
            implementation_code=str(raw_strategy.get("implementation_code") or "").strip(),
        )
    return normalized


def _normalize_executor(raw_value: object) -> str:
    normalized = str(raw_value or "").strip().lower()
    return normalized if normalized in {"ai", "local"} else "local"


def _normalize_params(raw_value: object) -> dict[str, object]:
    return dict(raw_value) if isinstance(raw_value, dict) else {}


def _normalize_fallback_generators(raw_value: object) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if raw_value is None:
        return []
    value = str(raw_value).strip()
    return [value] if value else []


def _merge_loaded_advice(
    current: AiTableGenerationAdvice,
    loaded: AiTableGenerationAdvice,
) -> AiTableGenerationAdvice:
    return AiTableGenerationAdvice(
        table_name=loaded.table_name or current.table_name,
        field_strategies={**current.field_strategies, **loaded.field_strategies},
        field_generation_strategies={
            **current.field_generation_strategies,
            **loaded.field_generation_strategies,
        },
    )
