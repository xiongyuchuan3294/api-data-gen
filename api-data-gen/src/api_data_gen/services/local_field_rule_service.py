from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from datetime import datetime, timedelta
import re

from api_data_gen.domain.models import TableColumn, TableSchema

_CUSTOMER_FIELDS = {
    "cust_id",
    "fcust_id",
    "cust_no",
    "ccif_no",
    "cst_no",
    "party_id",
    "ecif_no",
}


class LocalFieldRuleService:
    _SUPPORTED_GENERATORS: dict[str, str] = {
        "fixed_value": "固定值",
        "condition_value": "条件值",
        "dictionary_cycle": "字典轮询",
        "customer_id": "客户号生成器",
        "transaction_key": "交易流水号生成器",
        "model_seq_blank": "模型序列空串",
        "sample_cycle": "采样值轮询",
        "copy_from_field": "复制当前行字段值",
        "copy_from_context": "复制场景上下文字段值",
        "concat_template": "按模板拼接字段",
        "date_format_from_field": "按格式转换日期字段",
        "sequence_cycle": "序列轮询生成器",
        "datetime_range_cycle": "时间范围轮询生成器",
        "amount_pattern_cycle": "金额模式轮询生成器",
        "null": "空值",
    }
    _CONTEXTUAL_GENERATORS = {
        "copy_from_field",
        "copy_from_context",
        "concat_template",
        "date_format_from_field",
    }

    def __init__(self, dict_rule_resolver=None):
        self._dict_rule_resolver = dict_rule_resolver

    @classmethod
    def supported_generators(cls) -> dict[str, str]:
        return dict(cls._SUPPORTED_GENERATORS)

    @classmethod
    def is_contextual_generator(cls, generator: str) -> bool:
        return (generator or "").strip().lower() in cls._CONTEXTUAL_GENERATORS

    def identify_local_fields(self, schema: TableSchema) -> set[str]:
        return {
            column.name
            for column in schema.columns
            if self.has_local_rule(column)
        }

    def has_local_rule(self, column: TableColumn) -> bool:
        if self._resolve_dict_values(column):
            return True
        name = column.name.lower()
        comment = column.comment.lower()
        return (
            name in _CUSTOMER_FIELDS
            or "客户号" in comment
            or name == "transactionkey"
            or "交易流水号" in comment
            or name == "model_seq"
            or "模型树结果序列化" in comment
        )

    def generate_value(
        self,
        column: TableColumn,
        row_index: int,
        generation_tag: str | None = None,
        fixed_values: dict[str, str] | None = None,
    ) -> str | None:
        fixed_values = fixed_values or {}
        if column.name in fixed_values:
            return fixed_values[column.name]

        dict_values = self._resolve_dict_values(column)
        if dict_values:
            return dict_values[row_index % len(dict_values)]

        name = column.name.lower()
        comment = column.comment.lower()
        if name in _CUSTOMER_FIELDS or "客户号" in comment:
            return _generate_customer_id(row_index, generation_tag)
        if name == "transactionkey" or "交易流水号" in comment:
            return _generate_transaction_key(row_index, generation_tag)
        if name == "model_seq" or "模型树结果序列化" in comment:
            return ""
        return None

    def generate_with_generator(
        self,
        column: TableColumn,
        generator: str,
        params: dict[str, object] | None,
        row_index: int,
        generation_tag: str | None = None,
        fixed_values: dict[str, str] | None = None,
        row_values: dict[str, str | None] | None = None,
        scenario_context: dict[str, list[str | None]] | None = None,
    ) -> str | None:
        fixed_values = fixed_values or {}
        params = params or {}
        row_values = row_values or {}
        scenario_context = scenario_context or {}
        normalized = (generator or "").strip().lower()
        if not normalized:
            return None
        if normalized == "fixed_value":
            value = params.get("value")
            if value is not None:
                return str(value)
            return fixed_values.get(column.name)
        if normalized == "condition_value":
            values = _as_string_list(params.get("values"))
            return values[0] if values else None
        if normalized == "dictionary_cycle":
            values = _as_string_list(params.get("values")) or self._resolve_dict_values(column)
            return values[row_index % len(values)] if values else None
        if normalized == "customer_id":
            return _generate_customer_id(row_index, generation_tag)
        if normalized == "transaction_key":
            return _generate_transaction_key(row_index, generation_tag)
        if normalized == "model_seq_blank":
            return ""
        if normalized == "sample_cycle":
            values = _as_string_list(params.get("values"))
            return values[row_index % len(values)] if values else None
        if normalized == "copy_from_field":
            source_field = str(params.get("source_field") or params.get("field") or "").strip()
            if not source_field:
                return None
            return _resolve_context_value(source_field, row_values, scenario_context, row_index)
        if normalized == "copy_from_context":
            source_field = str(params.get("source_field") or params.get("field") or "").strip()
            if not source_field:
                return None
            values = scenario_context.get(source_field) or []
            if not values:
                return row_values.get(source_field)
            return values[row_index % len(values)]
        if normalized == "date_format_from_field":
            source_field = str(params.get("source_field") or params.get("field") or "").strip()
            if not source_field:
                return None
            raw_value = _resolve_context_value(source_field, row_values, scenario_context, row_index)
            if raw_value is None:
                return None
            parsed = _parse_datetime_like(raw_value)
            if parsed is None:
                return None
            output_format = str(params.get("output_format") or params.get("format") or "%Y%m%d")
            return parsed.strftime(output_format)
        if normalized == "concat_template":
            template = str(params.get("template") or "").strip()
            if not template:
                return None
            transforms = params.get("transforms") if isinstance(params.get("transforms"), dict) else {}
            rendered = template
            placeholders = re.findall(r"{([^{}]+)}", template)
            for placeholder in placeholders:
                raw_value = _resolve_context_value(placeholder, row_values, scenario_context, row_index)
                if raw_value is None:
                    return None
                transformed = _apply_transform(raw_value, transforms.get(placeholder))
                if transformed is None:
                    return None
                rendered = rendered.replace(f"{{{placeholder}}}", transformed)
            return rendered
        if normalized == "sequence_cycle":
            values = _as_string_list(params.get("values"))
            if values:
                return values[row_index % len(values)]
            start = _as_int(params.get("start"), 1)
            step = _as_int(params.get("step"), 1)
            width = _as_int(params.get("width"), 0)
            current = start + (row_index * step)
            return str(current).zfill(width) if width > 0 else str(current)
        if normalized == "datetime_range_cycle":
            values = _as_string_list(params.get("values"))
            if values:
                return values[row_index % len(values)]
            start_text = str(params.get("start") or "").strip()
            if not start_text:
                return None
            start_dt = _parse_datetime_like(start_text)
            if start_dt is None:
                return None
            end_dt = _parse_datetime_like(params.get("end")) if params.get("end") else None
            step_minutes = max(1, _as_int(params.get("step_minutes"), 60))
            if end_dt is not None and end_dt >= start_dt:
                span_minutes = int((end_dt - start_dt).total_seconds() // 60)
                slot_count = max(1, (span_minutes // step_minutes) + 1)
                offset = row_index % slot_count
            else:
                offset = row_index
            current = start_dt + timedelta(minutes=offset * step_minutes)
            output_format = str(
                params.get("output_format")
                or params.get("format")
                or ("%Y-%m-%d %H:%M:%S" if ":" in start_text else "%Y-%m-%d")
            )
            return current.strftime(output_format)
        if normalized == "amount_pattern_cycle":
            values = _as_string_list(params.get("values"))
            if values:
                return values[row_index % len(values)]
            base = _as_decimal(params.get("base"), Decimal("10000"))
            step = _as_decimal(params.get("step"), Decimal("0"))
            scale = max(0, _as_int(params.get("scale"), 2))
            signs = _as_string_list(params.get("pattern")) or _as_string_list(params.get("signs")) or ["+"]
            sign_token = signs[row_index % len(signs)].strip().lower()
            amount = base + (step * row_index)
            if sign_token in {"-", "negative", "neg"}:
                amount = -abs(amount)
            else:
                amount = abs(amount)
            return _format_decimal(amount, scale)
        if normalized == "null":
            return None
        return None

    def mask_rows(self, rows: list[dict[str, str]], local_fields: set[str]) -> list[dict[str, str]]:
        masked_rows: list[dict[str, str]] = []
        for row in rows:
            masked = dict(row)
            for field_name in local_fields:
                if field_name in masked:
                    masked[field_name] = "[DEFAULT]"
            masked_rows.append(masked)
        return masked_rows

    def _resolve_dict_values(self, column: TableColumn) -> list[str]:
        if self._dict_rule_resolver is None:
            return []
        return self._dict_rule_resolver.resolve_code_values(column.name, column.comment)


def _generate_customer_id(row_index: int, generation_tag: str | None) -> str:
    token = _numeric_token(generation_tag, row_index, 16)
    prefix = "09" if row_index % 2 == 0 else "99"
    return prefix + token


def _generate_transaction_key(row_index: int, generation_tag: str | None) -> str:
    date_part = _date_token(generation_tag)
    random_numbers = _numeric_token(generation_tag, row_index, 5)
    return f"6008C{date_part}00000600{random_numbers}99996"


def _date_token(generation_tag: str | None) -> str:
    if generation_tag:
        digits = "".join(character for character in generation_tag if character.isdigit())
        if len(digits) >= 8:
            return digits[:8]
    return datetime.now().strftime("%Y%m%d")


def _numeric_token(generation_tag: str | None, row_index: int, width: int) -> str:
    seed = f"{generation_tag or 'LOCAL'}:{row_index}".encode("utf-8")
    digits = str(int(hashlib.sha1(seed).hexdigest(), 16))
    return digits[-width:].zfill(width)


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item) != ""]
    if value is None or value == "":
        return []
    return [str(value)]


def _resolve_context_value(
    field_name: str,
    row_values: dict[str, str | None],
    scenario_context: dict[str, list[str | None]],
    row_index: int,
) -> str | None:
    if field_name in row_values:
        return row_values[field_name]
    values = scenario_context.get(field_name) or []
    if not values:
        return None
    return values[row_index % len(values)]


def _apply_transform(value: str, transform: object) -> str | None:
    if transform is None:
        return value
    normalized = str(transform).strip()
    if not normalized:
        return value
    if normalized.startswith("date:"):
        parsed = _parse_datetime_like(value)
        if parsed is None:
            return None
        return parsed.strftime(normalized.split(":", 1)[1])
    if normalized.startswith("replace:"):
        _, source, target = (normalized.split(":", 2) + [""])[:3]
        return value.replace(source, target)
    if normalized == "upper":
        return value.upper()
    if normalized == "lower":
        return value.lower()
    return value


def _parse_datetime_like(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _as_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _as_decimal(value: object, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _format_decimal(value: Decimal, scale: int) -> str:
    quantized = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    return f"{quantized:.{scale}f}"
