from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from api_data_gen.domain.models import AiTableGenerationAdvice, FieldGenerationStrategy, RelationRule, ScenarioDraft

_SCENARIO_CACHE_VERSION = 8
_FIELD_STRATEGY_CACHE_VERSION = 2
_MAX_HINT_FIELDS = 24


class AiCacheService:
    def __init__(self, cache_dir: str | Path = "output/ai_cache"):
        self._cache_dir = Path(cache_dir)

    def load_scenarios(
        self,
        *,
        requirement_text: str,
        interface_infos: list,
        schemas: dict,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        max_scenarios: int | None = None,
    ) -> list[ScenarioDraft] | None:
        path = self._cache_path(
            "scenarios",
            {
                "version": _SCENARIO_CACHE_VERSION,
                "requirement_text": requirement_text,
                "interface_infos": [asdict(item) for item in interface_infos],
                "schemas": {name: asdict(schema) for name, schema in sorted(schemas.items())},
                "fixed_values": list(fixed_values or []),
                "dependent_fixed_values": list(dependent_fixed_values or []),
                "max_scenarios": max_scenarios,
            },
        )
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            return None
        raw_scenarios = payload.get("scenarios")
        if not isinstance(raw_scenarios, list):
            return None
        scenarios: list[ScenarioDraft] = []
        for item in raw_scenarios:
            if not isinstance(item, dict):
                continue
            scenarios.append(
                ScenarioDraft(
                    id=str(item.get("id") or ""),
                    title=str(item.get("title") or ""),
                    api_name=str(item.get("api_name") or item.get("apiName") or ""),
                    api_path=str(item.get("api_path") or item.get("apiPath") or ""),
                    objective=str(item.get("objective") or ""),
                    request_inputs=_normalize_string_dict(item.get("request_inputs") or item.get("requestInputs")),
                    fixed_conditions=_normalize_string_list(item.get("fixed_conditions") or item.get("fixedConditions")),
                    assertions=_normalize_string_list(item.get("assertions")),
                    tables=_normalize_string_list(item.get("tables")),
                    table_requirements=_normalize_string_dict(
                        item.get("table_requirements") or item.get("tableRequirements")
                    ),
                    relation_rules=_normalize_relation_rules(item.get("relation_rules") or item.get("relationRules")),
                    generation_source=str(item.get("generation_source") or item.get("generationSource") or "ai"),
                )
            )
        return scenarios or None

    def save_scenarios(
        self,
        *,
        requirement_text: str,
        interface_infos: list,
        schemas: dict,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        max_scenarios: int | None = None,
        scenarios: list[ScenarioDraft],
    ) -> None:
        path = self._cache_path(
            "scenarios",
            {
                "version": _SCENARIO_CACHE_VERSION,
                "requirement_text": requirement_text,
                "interface_infos": [asdict(item) for item in interface_infos],
                "schemas": {name: asdict(schema) for name, schema in sorted(schemas.items())},
                "fixed_values": list(fixed_values or []),
                "dependent_fixed_values": list(dependent_fixed_values or []),
                "max_scenarios": max_scenarios,
            },
        )
        self._write_json(
            path,
            {
                "scenarios": [asdict(item) for item in scenarios],
            },
        )

    def load_field_decision(
        self,
        *,
        requirement_text: str,
        scenario: ScenarioDraft,
        table_name: str,
        schema,
        local_generated_columns: set[str],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> AiTableGenerationAdvice | None:
        path = self._cache_path(
            "field_strategies",
            {
                "version": _FIELD_STRATEGY_CACHE_VERSION,
                "requirement_text": requirement_text,
                "scenario": _scenario_cache_payload(scenario, table_name),
                "schema": asdict(schema),
                "local_generated_columns": sorted(local_generated_columns),
                "fixed_values": list(fixed_values or []),
                "dependent_fixed_values": list(dependent_fixed_values or []),
            },
        )
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            return None
        return _deserialize_ai_advice(payload)

    def save_field_decision(
        self,
        *,
        requirement_text: str,
        scenario: ScenarioDraft,
        table_name: str,
        schema,
        local_generated_columns: set[str],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        advice: AiTableGenerationAdvice,
    ) -> None:
        path = self._cache_path(
            "field_strategies",
            {
                "version": _FIELD_STRATEGY_CACHE_VERSION,
                "requirement_text": requirement_text,
                "scenario": _scenario_cache_payload(scenario, table_name),
                "schema": asdict(schema),
                "local_generated_columns": sorted(local_generated_columns),
                "fixed_values": list(fixed_values or []),
                "dependent_fixed_values": list(dependent_fixed_values or []),
            },
        )
        self._write_json(path, _serialize_ai_advice(advice))

    def format_strategy_hint(self, advice: AiTableGenerationAdvice) -> str:
        lines = [f"TABLE|{advice.table_name}"]
        field_names = [
            field_name
            for field_name in advice.field_generation_strategies
            if field_name in advice.field_strategies or advice.field_generation_strategies[field_name].generator
        ]
        if not field_names:
            field_names = list(advice.field_strategies)
        for field_name in field_names[:_MAX_HINT_FIELDS]:
            strategy = advice.field_generation_strategies.get(field_name)
            executor = advice.field_strategies.get(field_name)
            if strategy is None:
                if executor is None:
                    continue
                strategy = FieldGenerationStrategy(
                    executor=executor,
                    generator="ai_value" if executor == "ai" else "local_rule",
                )
            params = _format_params(strategy.params)
            fallbacks = ",".join(strategy.fallback_generators)
            lines.append(
                "|".join(
                    [
                        "FIELD",
                        field_name,
                        strategy.executor or executor or "local",
                        strategy.generator or ("ai_value" if executor == "ai" else "local_rule"),
                        params,
                        fallbacks,
                        strategy.implementation_hint or "",
                        strategy.implementation_code or "",
                    ]
                )
            )
        return "\n".join(lines)

    def _cache_path(self, namespace: str, payload: dict[str, object]) -> Path:
        raw_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self._cache_dir / namespace / f"{digest}.json"

    def _read_json(self, path: Path) -> object | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _scenario_cache_payload(scenario: ScenarioDraft, table_name: str) -> dict[str, object]:
    return {
        "title": scenario.title,
        "objective": scenario.objective,
        "api_name": scenario.api_name,
        "api_path": scenario.api_path,
        "request_inputs": dict(sorted(scenario.request_inputs.items())),
        "fixed_conditions": list(scenario.fixed_conditions),
        "assertions": list(scenario.assertions),
        "table_name": table_name,
        "table_requirement": scenario.table_requirements.get(table_name, ""),
        "relation_rules": [asdict(rule) for rule in scenario.relation_rules],
    }


def _serialize_ai_advice(advice: AiTableGenerationAdvice) -> dict[str, object]:
    return {
        "table_name": advice.table_name,
        "rows": advice.rows,
        "field_strategies": dict(advice.field_strategies),
        "field_generation_strategies": {
            field_name: asdict(strategy)
            for field_name, strategy in advice.field_generation_strategies.items()
        },
    }


def _deserialize_ai_advice(payload: dict[str, object]) -> AiTableGenerationAdvice | None:
    table_name = str(payload.get("table_name") or "")
    if not table_name:
        return None
    raw_rows = payload.get("rows")
    rows = [
        {str(key): str(value) for key, value in item.items()}
        for item in raw_rows
        if isinstance(item, dict)
    ] if isinstance(raw_rows, list) else []
    raw_field_strategies = payload.get("field_strategies")
    field_strategies = _normalize_string_dict(raw_field_strategies)
    raw_generation_strategies = payload.get("field_generation_strategies")
    generation_strategies: dict[str, FieldGenerationStrategy] = {}
    if isinstance(raw_generation_strategies, dict):
        for field_name, item in raw_generation_strategies.items():
            if not isinstance(item, dict):
                continue
            generation_strategies[str(field_name)] = FieldGenerationStrategy(
                executor=str(item.get("executor") or "local"),
                generator=str(item.get("generator") or ""),
                params=item.get("params") if isinstance(item.get("params"), dict) else {},
                fallback_generators=_normalize_string_list(
                    item.get("fallback_generators") or item.get("fallbacks")
                ),
                rationale=str(item.get("rationale") or ""),
                implementation_hint=str(item.get("implementation_hint") or ""),
                implementation_code=str(item.get("implementation_code") or ""),
            )
    return AiTableGenerationAdvice(
        table_name=table_name,
        rows=rows,
        field_strategies=field_strategies,
        field_generation_strategies=generation_strategies,
    )


def _normalize_string_dict(raw_value: object) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw_value.items()
    }


def _normalize_string_list(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    return [str(item) for item in raw_value]


def _format_params(params: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in sorted(params.items()):
        if isinstance(value, dict):
            for child_key, child_value in sorted(value.items()):
                parts.append(f"{key.rstrip('s')}.{child_key}={child_value}")
            continue
        if isinstance(value, list):
            parts.append(f"{key}={','.join(str(item) for item in value)}")
            continue
        parts.append(f"{key}={value}")
    return ";".join(parts)



def _normalize_relation_rules(raw_data: object) -> list[RelationRule]:
    if not isinstance(raw_data, list):
        return []
    normalized: list[RelationRule] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        target_table = str(item.get("target_table") or item.get("targetTable") or "").strip()
        target_field = str(item.get("target_field") or item.get("targetField") or "").strip()
        source_table = str(item.get("source_table") or item.get("sourceTable") or "").strip()
        source_field = str(item.get("source_field") or item.get("sourceField") or "").strip()
        if not (target_table and target_field and source_table and source_field):
            continue
        evidence = item.get("evidence")
        normalized.append(
            RelationRule(
                target_table=target_table,
                target_field=target_field,
                source_table=source_table,
                source_field=source_field,
                relation_type=str(item.get("relation_type") or item.get("relationType") or "same_value").strip() or "same_value",
                rationale=str(item.get("rationale") or item.get("reason") or "").strip(),
                evidence=evidence if isinstance(evidence, dict) else {},
            )
        )
    return normalized
