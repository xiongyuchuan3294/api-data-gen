from __future__ import annotations

from dataclasses import replace
import json
import re

from api_data_gen.domain.models import AiTableGenerationAdvice, FieldGenerationStrategy, ScenarioDraft, TableSchema
from api_data_gen.services.ai_utils import parse_json_payload, salvage_json_array_objects
from api_data_gen.services.fixed_value_service import format_fixed_value_lines
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService

_FIELD_STRATEGY_SCHEMA_COLUMN_LIMIT = 12
_FIELD_STRATEGY_SUMMARY_LIMIT = 3
_FIELD_STRATEGY_SUMMARY_CHAR_LIMIT = 140
_FIELD_STRATEGY_SINGLE_MAX_OUTPUT_TOKENS = 700
_FIELD_STRATEGY_REPAIR_MAX_OUTPUT_TOKENS = 900
_HIGH_VALUE_FIELD_NAMES = {
    "uuid",
    "cust_id",
    "fcust_id",
    "model_key",
    "result_key",
    "result_date",
    "alert_date",
    "ds",
    "transactionkey",
    "drft_no",
    "seq_no",
    "trans_time",
    "trans_amount",
    "receive_pay_cd",
    "cust_name",
    "req_nm",
    "rcv_nm",
    "last_req_nm",
    "drwr_nm",
}


class AiDataGenerationService:
    def __init__(self, ai_chat_client):
        self._ai_chat_client = ai_chat_client

    def generate(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> dict[str, AiTableGenerationAdvice]:
        try:
            return self._generate_batch(
                scenario,
                schemas,
                sample_rows_by_table,
                local_generated_columns,
                analysis_by_table,
                fixed_values,
                dependent_fixed_values,
                strategy_only=False,
            )
        except ValueError:
            if len(schemas) <= 1:
                raise
            return self._generate_table_by_table(
                scenario,
                schemas,
                sample_rows_by_table,
                local_generated_columns,
                analysis_by_table,
                fixed_values,
                dependent_fixed_values,
                strategy_only=False,
            )

    def decide_table_field_strategies(
        self,
        requirement_text: str,
        table_name: str,
        schema: TableSchema,
        scenario_summaries: list[str],
        local_generated_columns: set[str],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        prior_advice: AiTableGenerationAdvice | None = None,
    ) -> AiTableGenerationAdvice:
        prompt = self._build_table_strategy_prompt(
            requirement_text=requirement_text,
            table_name=table_name,
            schema=schema,
            scenario_summaries=scenario_summaries,
            local_generated_columns=local_generated_columns,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
            prior_advice=prior_advice,
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一位数据库测试字段策略专家，只负责判断字段更适合 AI 还是本地规则。",
            user_prompt=prompt,
            max_output_tokens=_FIELD_STRATEGY_SINGLE_MAX_OUTPUT_TOKENS,
        )
        compact_advice = _parse_compact_field_decisions(response, default_table_name=table_name)
        if compact_advice:
            return compact_advice.get(table_name) or next(iter(compact_advice.values()))
        payload = self._load_object_payload(prompt, response)
        strategies = _extract_field_strategies(payload)
        generation_strategies = _extract_field_generation_strategies(payload, strategies)
        return AiTableGenerationAdvice(
            table_name=table_name,
            rows=[],
            field_strategies=strategies,
            field_generation_strategies=generation_strategies,
        )

    def decide_tables_field_strategies(
        self,
        requirement_text: str,
        table_requests: list[dict[str, object]],
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
    ) -> dict[str, AiTableGenerationAdvice]:
        prompt = self._build_batch_table_strategy_prompt(
            requirement_text=requirement_text,
            table_requests=table_requests,
            fixed_values=fixed_values,
            dependent_fixed_values=dependent_fixed_values,
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一位数据库测试字段策略专家，只负责批量判断字段更适合 AI 还是本地规则。",
            user_prompt=prompt,
            max_output_tokens=_batch_strategy_max_output_tokens(len(table_requests)),
        )
        compact_advice = _parse_compact_field_decisions(response)
        if compact_advice:
            return compact_advice
        payload = self._load_payload(prompt, response, allow_partial_recovery=True)
        result = self._normalize_payload(payload)
        return {
            table_name: AiTableGenerationAdvice(
                table_name=advice.table_name,
                rows=[],
                field_strategies=advice.field_strategies,
                field_generation_strategies=advice.field_generation_strategies,
            )
            for table_name, advice in result.items()
        }

    def _generate_batch(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        strategy_only: bool = False,
    ) -> dict[str, AiTableGenerationAdvice]:
        prompt = self._build_prompt(
            scenario,
            schemas,
            sample_rows_by_table,
            local_generated_columns,
            analysis_by_table,
            fixed_values,
            dependent_fixed_values,
            strategy_only=strategy_only,
        )
        response = self._ai_chat_client.complete(
            system_prompt="你是一位数据库测试数据生成专家，负责为给定测试场景生成结构化表数据。",
            user_prompt=prompt,
        )
        payload = self._load_payload(prompt, response)
        return self._normalize_payload(payload)

    def _generate_table_by_table(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        strategy_only: bool,
    ) -> dict[str, AiTableGenerationAdvice]:
        result: dict[str, AiTableGenerationAdvice] = {}
        table_names = [table_name for table_name in scenario.tables if table_name in schemas] or list(schemas)
        for table_name in table_names:
            table_scenario = replace(
                scenario,
                tables=[table_name],
                table_requirements={table_name: scenario.table_requirements.get(table_name, "")},
            )
            table_result = self._generate_batch(
                table_scenario,
                {table_name: schemas[table_name]},
                {table_name: sample_rows_by_table.get(table_name, [])},
                {table_name: local_generated_columns.get(table_name, set())},
                {table_name: analysis_by_table.get(table_name, "{}")},
                fixed_values,
                dependent_fixed_values,
                strategy_only=strategy_only,
            )
            advice = table_result.get(table_name)
            if advice is not None:
                result[table_name] = advice
        return result

    def _normalize_payload(self, payload: object) -> dict[str, AiTableGenerationAdvice]:
        if not isinstance(payload, list):
            raise ValueError("AI data generation response must be a JSON array.")
        result: dict[str, AiTableGenerationAdvice] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            table_name = str(item.get("table") or "")
            if not table_name:
                continue
            raw_data = item.get("data")
            rows = _normalize_rows(raw_data)
            field_strategies = _normalize_field_strategies(item.get("field_strategies") or item.get("fieldStrategies"))
            field_generation_strategies = _normalize_field_generation_strategies(
                item.get("field_generation_strategies") or item.get("fieldGenerationStrategies"),
                field_strategies,
            )
            current = result.get(table_name)
            if current is None:
                result[table_name] = AiTableGenerationAdvice(
                    table_name=table_name,
                    rows=rows,
                    field_strategies=field_strategies,
                    field_generation_strategies=field_generation_strategies,
                )
                continue
            result[table_name] = AiTableGenerationAdvice(
                table_name=table_name,
                rows=current.rows + rows,
                field_strategies={**current.field_strategies, **field_strategies},
                field_generation_strategies={
                    **current.field_generation_strategies,
                    **field_generation_strategies,
                },
            )
        return result

    def _build_prompt(
        self,
        scenario: ScenarioDraft,
        schemas: dict[str, TableSchema],
        sample_rows_by_table: dict[str, list[dict[str, str]]],
        local_generated_columns: dict[str, set[str]],
        analysis_by_table: dict[str, str],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        strategy_only: bool = False,
    ) -> str:
        sections = [
            "测试场景:",
            f"- 名称: {scenario.title}",
            f"- 描述: {scenario.objective}",
            f"- 表需求: {scenario.table_requirements or {table: '' for table in scenario.tables}}",
            "",
            f"固定字段: {format_fixed_value_lines(fixed_values) or '[无]'}",
            f"依赖固定值: {format_fixed_value_lines(dependent_fixed_values) or '[无]'}",
            "",
            "以下字段具备本地规则能力，仅供参考，不是强制约束:",
            str({table: sorted(values) for table, values in local_generated_columns.items()}),
            "",
            "你需要逐字段判断是走 AI 生成还是走本地规则:",
            "1. 请尽量输出结构化 field_generation_strategies，让本地代码按生成器执行。",
            "2. 如果字段更适合本地规则，请使用 executor=local，并选择合适 generator。",
            "3. 如果字段本地生成器暂时做不了，再使用 executor=ai；必要时补 implementation_hint / implementation_code。",
            "4. 如果你直接在 data 中输出了某字段值，系统会优先把它视为 AI 生成。",
            "",
        ]
        for table_name, schema in schemas.items():
            if strategy_only:
                sections.extend(
                    [
                        f"表: {table_name}",
                        f"字段: {_summarize_schema(schema)}",
                        "",
                    ]
                )
            else:
                sections.extend(
                    [
                        f"表: {table_name}",
                        f"结构: {schema}",
                        f"样本: {sample_rows_by_table.get(table_name, [])[:5]}",
                        f"分析建议: {analysis_by_table.get(table_name, '{}')}",
                        "",
                    ]
                )
        if strategy_only:
            sections.extend(
                [
                    "输出要求:",
                    "1. 严格输出 JSON 数组",
                    '2. 默认每个元素格式为 {"table":"表名","field_strategies":{"字段名":"ai|local"},"field_generation_strategies":{"字段名":{"executor":"local|ai","generator":"生成器编码","params":{},"fallback_generators":[],"implementation_hint":"","implementation_code":""}}}',
                    "3. 只有极少数字段必须由 AI 直接赋值时，才额外输出 data，且 data 只允许 1 行、只包含这些 AI 字段",
                    "4. field_strategies 只允许 ai 或 local；field_generation_strategies 里的 executor 也只允许 local 或 ai",
                    "5. 优先复用这些本地生成器编码:",
                    _format_supported_generators(),
                    "6. 组合字段、日期派生字段、上下游复用字段优先使用结构化本地策略。",
                    '7. 示例: {"table":"aml_f_tidb_model_result","field_generation_strategies":{"result_key":{"executor":"local","generator":"concat_template","params":{"template":"{model_key}{result_date}{cust_id}","transforms":{"result_date":"date:%Y%m%d"}}}}}',
                    "8. 保持跨表字段一致性，不要输出额外解释",
                ]
            )
        else:
            sections.extend(
                [
                    "输出要求:",
                    "1. 严格输出 JSON 数组",
                    '2. 每个元素格式为 {"table":"表名","field_strategies":{"字段名":"ai|local"},"field_generation_strategies":{"字段名":{"executor":"local|ai","generator":"生成器编码","params":{},"fallback_generators":[]}},"data":{...}} 或 {"table":"表名","field_strategies":{...},"field_generation_strategies":{...},"data":[{...}]}',
                    "3. 如果某张表无需 AI 直接给值，可省略 data 或输出空对象 {}",
                    "4. field_strategies 只允许 ai 或 local；能描述成结构化生成器时，不要只给口头描述",
                    "5. 保持跨表字段一致性，不要输出额外解释",
                ]
            )
        return "\n".join(sections)

    def _build_table_strategy_prompt(
        self,
        requirement_text: str,
        table_name: str,
        schema: TableSchema,
        scenario_summaries: list[str],
        local_generated_columns: set[str],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
        prior_advice: AiTableGenerationAdvice | None = None,
    ) -> str:
        sections = [
            "任务:",
            "请只做字段策略判断，不要生成测试数据行。",
            "",
            "业务需求:",
            requirement_text,
            "",
            "相关场景:",
            _format_scenario_summaries(scenario_summaries),
            "",
            f"表名: {table_name}",
            f"字段: {_summarize_schema(schema, important_fields=set(local_generated_columns))}",
            f"本地规则能力字段: {sorted(local_generated_columns) or ['[无]']}",
            f"固定字段: {format_fixed_value_lines(fixed_values) or '[无]'}",
            f"依赖固定值: {format_fixed_value_lines(dependent_fixed_values) or '[无]'}",
            "",
            "判断原则:",
            "1. 主键、固定值、条件值、明显可由本地规则稳定生成的字段优先 local。",
            "2. 需要业务语义、文本理解、跨字段组合判断的字段标 ai。",
            "3. 未明确需要 AI 的字段尽量不要标 ai。",
            "",
            "优先使用这些本地生成器编码:",
            _format_supported_generators(),
            "",
        ]
        if _has_explicit_field_decisions(prior_advice):
            sections.extend(
                [
                    "可复用历史策略:",
                    _format_prior_strategy_hint(prior_advice),
                    "如果本场景与历史策略大体一致，只输出需要调整的差异字段；未输出字段系统会沿用历史策略。",
                    "",
                ]
            )
        sections.extend(
            [
                "输出要求:",
                "1. 优先输出紧凑行格式:",
                f"   TABLE|{table_name}",
                "   FIELD|字段名|local或ai|generator编码|params(k=v;k2=v2)|fallback1,fallback2|implementation_hint|implementation_code",
                "2. params 为空时可留空；列表可写成 values=a,b,c；嵌套转换写成 transform.result_date=date:%Y%m%d。",
                "3. 只输出你需要显式判断的字段；未输出的字段系统会视为 local。",
                "4. 如果确实无法输出紧凑行格式，再退回 JSON 对象。",
                "5. 不要输出 data，不要输出解释文字。",
                "6. 优先把组合字段、日期派生字段、上下游复用字段描述成结构化本地策略。",
                "7. 示例: FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d|||",
            ]
        )
        return "\n".join(sections)

    def _build_batch_table_strategy_prompt(
        self,
        requirement_text: str,
        table_requests: list[dict[str, object]],
        fixed_values: list[str] | None,
        dependent_fixed_values: list[str] | None,
    ) -> str:
        sections = [
            "任务:",
            "请批量判断多张表的字段生成策略，不要生成测试数据行。",
            "",
            "业务需求:",
            requirement_text,
            "",
            f"固定字段: {format_fixed_value_lines(fixed_values) or '[无]'}",
            f"依赖固定值: {format_fixed_value_lines(dependent_fixed_values) or '[无]'}",
            "",
            "判断原则:",
            "1. 主键、固定值、条件值、明显可由本地规则稳定生成的字段优先 local。",
            "2. 组合字段、日期格式转换字段、上下游复用字段尽量使用结构化本地生成器。",
            "3. 只有本地生成器确实覆盖不了的字段才标 ai。",
            "",
            "优先使用这些本地生成器编码:",
            _format_supported_generators(),
            "",
            "紧凑示例:",
            "FIELD|result_key|local|concat_template|template={model_key}{result_date}{cust_id};transform.result_date=date:%Y%m%d|||",
            "FIELD|ds|local|date_format_from_field|source_field=alert_date;output_format=%Y%m%d|||",
            "FIELD|drft_no|local|copy_from_context|source_field=drft_no|||",
            "FIELD|seq_no|local|sequence_cycle|values=8,7,10|||",
            "",
        ]
        for request in table_requests:
            schema = request.get("schema")
            if not isinstance(schema, TableSchema):
                continue
            table_name = str(request.get("table_name") or schema.table_name)
            scenario_summaries = request.get("scenario_summaries")
            local_generated_columns = request.get("local_generated_columns")
            prior_advice = request.get("prior_advice")
            sections.extend(
                [
                    f"表名: {table_name}",
                    "相关场景:",
                    _format_scenario_summaries(scenario_summaries),
                    f"字段: {_summarize_schema(schema, important_fields=set(local_generated_columns or []))}",
                    f"本地规则能力字段: {sorted(local_generated_columns or []) or ['[无]']}",
                ]
            )
            if _has_explicit_field_decisions(prior_advice):
                sections.extend(
                    [
                        "可复用历史策略:",
                        _format_prior_strategy_hint(prior_advice),
                        "如果本场景与历史策略大体一致，只输出需要调整的差异字段；未输出字段系统会沿用历史策略。",
                    ]
                )
            sections.append("")
        sections.extend(
            [
                "输出要求:",
                "1. 优先输出紧凑行格式，按表分块:",
                "   TABLE|表名",
                "   FIELD|字段名|local或ai|generator编码|params(k=v;k2=v2)|fallback1,fallback2|implementation_hint|implementation_code",
                "2. params 为空时可留空；列表可写成 values=a,b,c；嵌套转换写成 transform.result_date=date:%Y%m%d。",
                "3. 只输出你需要显式判断的字段；未输出的字段系统会视为 local。",
                "4. 如果确实无法输出紧凑行格式，再退回 JSON 数组。",
                "5. 不要输出 data，不要输出解释文字。",
            ]
        )
        return "\n".join(sections)

    def _load_payload(self, prompt: str, response: str, allow_partial_recovery: bool = False) -> object:
        try:
            return parse_json_payload(response)
        except (json.JSONDecodeError, ValueError) as exc:
            recovered = salvage_json_array_objects(response) if allow_partial_recovery else []
            if recovered:
                return recovered
            repaired = self._repair_payload(prompt, response, str(exc))
            try:
                return parse_json_payload(repaired)
            except (json.JSONDecodeError, ValueError) as repaired_exc:
                recovered = salvage_json_array_objects(repaired) if allow_partial_recovery else []
                if recovered:
                    return recovered
                repaired_again = self._repair_payload(
                    prompt,
                    repaired,
                    (
                        "上一次修复后的内容仍不是合法 JSON。\n"
                        f"错误信息: {repaired_exc}\n"
                        "请务必补全缺失的引号、逗号、右括号、右中括号，并将字符串中的换行转义为 \\n。"
                    ),
                )
                return parse_json_payload(repaired_again)

    def _repair_payload(self, prompt: str, response: str, error_detail: str) -> str:
        return self._ai_chat_client.complete(
            system_prompt="你是一位 JSON 修复助手，只负责把给定内容修复为合法 JSON。",
            user_prompt=(
                "下面是一次测试数据生成的模型输出，但它不是合法 JSON。\n"
                "请保留原有语义，只输出修复后的 JSON 数组，不要附加解释。\n"
                "如果字符串里包含换行，必须转义为 \\n。\n"
                f"当前解析错误: {error_detail}\n\n"
                f"原始提示:\n{prompt}\n\n"
                f"待修复输出:\n{response}"
            ),
            max_output_tokens=_FIELD_STRATEGY_REPAIR_MAX_OUTPUT_TOKENS,
        )

    def _load_object_payload(self, prompt: str, response: str) -> object:
        try:
            return _normalize_object_payload(parse_json_payload(response))
        except (json.JSONDecodeError, ValueError) as exc:
            repaired = self._repair_object_payload(prompt, response, str(exc))
            return _normalize_object_payload(parse_json_payload(repaired))

    def _repair_object_payload(self, prompt: str, response: str, error_detail: str) -> str:
        return self._ai_chat_client.complete(
            system_prompt="你是一位 JSON 修复助手，只负责把给定内容修复为合法 JSON。",
            user_prompt=(
                "下面是一次字段策略判断的模型输出，但它不是合法 JSON。\n"
                "请保留原有语义，只输出修复后的 JSON 对象，不要附加解释。\n"
                f"当前解析错误: {error_detail}\n\n"
                f"原始提示:\n{prompt}\n\n"
                f"待修复输出:\n{response}"
            ),
            max_output_tokens=_FIELD_STRATEGY_REPAIR_MAX_OUTPUT_TOKENS,
        )


def _normalize_rows(raw_data: object) -> list[dict[str, str]]:
    if isinstance(raw_data, dict):
        return [{str(key): str(value) for key, value in raw_data.items()}]
    if isinstance(raw_data, list):
        rows: list[dict[str, str]] = []
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            rows.append({str(key): str(value) for key, value in item.items()})
        return rows
    return []


def _normalize_field_strategies(raw_data: object) -> dict[str, str]:
    if not isinstance(raw_data, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in raw_data.items():
        field_name = str(key)
        strategy = str(value).strip().lower()
        if strategy in {"ai", "llm", "model"}:
            normalized[field_name] = "ai"
        elif strategy in {"local", "rule", "deterministic"}:
            normalized[field_name] = "local"
    return normalized


def _normalize_strategy_executor(value: object) -> str | None:
    normalized = str(value).strip().lower()
    if normalized in {"ai", "local"}:
        return normalized
    return None


def _extract_field_strategies(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    return _normalize_field_strategies(
        payload.get("field_strategies") or payload.get("fieldStrategies") or payload.get("strategies")
    )


def _extract_field_generation_strategies(
    payload: object,
    field_strategies: dict[str, str],
) -> dict[str, FieldGenerationStrategy]:
    if not isinstance(payload, dict):
        return {}
    return _normalize_field_generation_strategies(
        payload.get("field_generation_strategies")
        or payload.get("fieldGenerationStrategies")
        or payload.get("generator_strategies"),
        field_strategies,
    )


def _normalize_object_payload(payload: object) -> object:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
        return {}
    return payload


def _summarize_schema(schema: TableSchema, important_fields: set[str] | None = None) -> str:
    important_fields = {field.lower() for field in (important_fields or set())}
    ranked_columns = sorted(
        schema.columns,
        key=lambda column: (
            _field_strategy_column_rank(column, important_fields),
            schema.columns.index(column),
        ),
    )
    parts: list[str] = []
    selected_columns = ranked_columns[:_FIELD_STRATEGY_SCHEMA_COLUMN_LIMIT]
    for column in selected_columns:
        description = f"{column.name}:{column.type}"
        if column.comment:
            description = f"{description}({column.comment})"
        parts.append(description)
    omitted_count = max(0, len(schema.columns) - len(selected_columns))
    if omitted_count:
        parts.append(f"...省略{omitted_count}列")
    return ", ".join(parts)


def _normalize_field_generation_strategies(
    raw_data: object,
    field_strategies: dict[str, str],
) -> dict[str, FieldGenerationStrategy]:
    normalized: dict[str, FieldGenerationStrategy] = {}
    if isinstance(raw_data, dict):
        for field_name, item in raw_data.items():
            strategy = _normalize_field_generation_strategy(str(field_name), item, field_strategies.get(str(field_name)))
            if strategy is not None:
                normalized[str(field_name)] = strategy
    for field_name, strategy_name in field_strategies.items():
        normalized.setdefault(
            field_name,
            FieldGenerationStrategy(
                executor=strategy_name,
                generator="ai_value" if strategy_name == "ai" else "local_rule",
            ),
        )
    return normalized


def _normalize_field_generation_strategy(
    field_name: str,
    raw_data: object,
    fallback_strategy: str | None,
) -> FieldGenerationStrategy | None:
    if not isinstance(raw_data, dict):
        if fallback_strategy in {"ai", "local"}:
            return FieldGenerationStrategy(
                executor=fallback_strategy,
                generator="ai_value" if fallback_strategy == "ai" else "local_rule",
            )
        return None

    executor = _normalize_strategy_executor(raw_data.get("executor") or fallback_strategy or "local")
    if executor is None:
        return None
    generator = str(raw_data.get("generator") or ("ai_value" if executor == "ai" else "local_rule")).strip()
    params = _normalize_strategy_params(raw_data.get("params"))
    fallback_generators = _normalize_fallback_generators(
        raw_data.get("fallback_generators") or raw_data.get("fallbacks")
    )
    return FieldGenerationStrategy(
        executor=executor,
        generator=generator,
        params=params,
        fallback_generators=fallback_generators,
        rationale=str(raw_data.get("rationale") or raw_data.get("reason") or ""),
        implementation_hint=str(
            raw_data.get("implementation_hint") or raw_data.get("implementationHint") or ""
        ),
        implementation_code=str(
            raw_data.get("implementation_code") or raw_data.get("implementationCode") or ""
        ),
    )


def _normalize_strategy_params(raw_data: object) -> dict[str, object]:
    if not isinstance(raw_data, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, value in raw_data.items():
        normalized[str(key)] = _normalize_param_value(value)
    return normalized


def _normalize_param_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalize_param_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_param_value(item) for item in value]
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _normalize_fallback_generators(raw_data: object) -> list[str]:
    if isinstance(raw_data, list):
        return [str(item).strip() for item in raw_data if str(item).strip()]
    if raw_data is None:
        return []
    text = str(raw_data).strip()
    return [text] if text else []


def _format_supported_generators() -> str:
    parts = [
        f"{name}({description})"
        for name, description in LocalFieldRuleService.supported_generators().items()
    ]
    return ", ".join(parts)


def _format_prior_strategy_hint(advice: AiTableGenerationAdvice | None) -> str:
    if not _has_explicit_field_decisions(advice):
        return "[无]"
    lines = [f"TABLE|{advice.table_name}"]
    field_names = list(advice.field_generation_strategies) or list(advice.field_strategies)
    for field_name in field_names[:24]:
        strategy = advice.field_generation_strategies.get(field_name)
        executor = advice.field_strategies.get(field_name)
        if strategy is None:
            if executor is None:
                continue
            strategy = FieldGenerationStrategy(
                executor=executor,
                generator="ai_value" if executor == "ai" else "local_rule",
            )
        lines.append(
            "|".join(
                [
                    "FIELD",
                    field_name,
                    strategy.executor or executor or "local",
                    strategy.generator or ("ai_value" if executor == "ai" else "local_rule"),
                    _format_compact_params(strategy.params),
                    ",".join(strategy.fallback_generators),
                    strategy.implementation_hint or "",
                    strategy.implementation_code or "",
                ]
            )
        )
    return "\n".join(lines)


def _format_compact_params(params: dict[str, object]) -> str:
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


def _has_explicit_field_decisions(advice: AiTableGenerationAdvice | None) -> bool:
    if advice is None:
        return False
    return bool(advice.field_strategies or advice.field_generation_strategies)


def _field_strategy_column_rank(column, important_fields: set[str]) -> tuple[int, int, int, int]:
    name = column.name.lower()
    comment = column.comment.lower()
    return (
        0 if column.is_primary_key else 1,
        0 if name in important_fields else 1,
        0 if name in _HIGH_VALUE_FIELD_NAMES else 1,
        0 if any(keyword in comment for keyword in ("客户", "模型", "日期", "时间", "票", "金额", "收付", "请求", "接收", "交易")) else 1,
    )


def _format_scenario_summaries(summaries: list[str] | None) -> str:
    if not summaries:
        return "[无]"
    trimmed: list[str] = []
    for item in summaries[:_FIELD_STRATEGY_SUMMARY_LIMIT]:
        text = " ".join(str(item).split())
        if len(text) > _FIELD_STRATEGY_SUMMARY_CHAR_LIMIT:
            text = f"{text[:_FIELD_STRATEGY_SUMMARY_CHAR_LIMIT - 1]}…"
        trimmed.append(f"- {text}")
    return "\n".join(trimmed)


def _batch_strategy_max_output_tokens(table_count: int) -> int:
    return min(1400, max(700, 260 + (table_count * 170)))


def _parse_compact_field_decisions(
    response: str,
    default_table_name: str | None = None,
) -> dict[str, AiTableGenerationAdvice]:
    lines = _compact_lines(response)
    if not any(line.startswith("TABLE|") or line.startswith("FIELD|") for line in lines):
        return {}

    result: dict[str, AiTableGenerationAdvice] = {}
    current_table = default_table_name or ""

    for line in lines:
        if line.startswith("TABLE|"):
            parts = _split_compact_fields(line, 2)
            if len(parts) < 2 or not parts[1]:
                continue
            current_table = parts[1]
            result.setdefault(current_table, AiTableGenerationAdvice(table_name=current_table))
            continue
        if not line.startswith("FIELD|"):
            continue
        parts = _split_compact_fields(line, 8)
        if len(parts) < 5 or not current_table:
            continue
        field_name = parts[1]
        executor = _normalize_strategy_executor(parts[2]) or "local"
        generator = parts[3].strip() or ("ai_value" if executor == "ai" else "local_rule")
        params = _parse_compact_params(parts[4])
        fallback_generators = _parse_compact_fallbacks(parts[5] if len(parts) > 5 else "")
        implementation_hint = parts[6] if len(parts) > 6 else ""
        implementation_code = parts[7] if len(parts) > 7 else ""
        advice = result.setdefault(current_table, AiTableGenerationAdvice(table_name=current_table))
        advice.field_strategies[field_name] = executor
        advice.field_generation_strategies[field_name] = FieldGenerationStrategy(
            executor=executor,
            generator=generator,
            params=params,
            fallback_generators=fallback_generators,
            implementation_hint=implementation_hint,
            implementation_code=implementation_code,
        )
    return {
        table_name: advice
        for table_name, advice in result.items()
        if advice.field_generation_strategies or advice.field_strategies
    }


def _parse_compact_params(raw_text: str) -> dict[str, object]:
    text = (raw_text or "").strip()
    if not text:
        return {}
    params: dict[str, object] = {}
    transforms: dict[str, object] = {}
    for item in text.split(";"):
        entry = item.strip()
        if not entry or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key.startswith("transform."):
            transforms[key.split(".", 1)[1]] = value
            continue
        if key in {"values", "value_list", "signs", "pattern"}:
            params["values" if key == "value_list" else key] = [part.strip() for part in value.split(",") if part.strip()]
            continue
        params[key] = value
    if transforms:
        params["transforms"] = transforms
    return params


def _parse_compact_fallbacks(raw_text: str) -> list[str]:
    text = (raw_text or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _compact_lines(text: str) -> list[str]:
    stripped = re.sub(r"```(?:text|json|yaml)?", "", text or "", flags=re.IGNORECASE)
    return [line.strip() for line in stripped.splitlines() if line.strip()]


def _split_compact_fields(line: str, max_parts: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escape = False
    for char in line:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == "|" and len(parts) < max_parts - 1:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts
