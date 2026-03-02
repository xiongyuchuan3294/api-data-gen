from __future__ import annotations

from api_data_gen.domain.models import GeneratedRow, TableColumn, TableSchema, ValidationCheck

DEFAULT_MARKER = "[DEFAULT]"


class RecordValidationService:
    def validate_table(
        self,
        schema: TableSchema,
        rows: list[GeneratedRow],
        check_prefix: str,
    ) -> tuple[list[GeneratedRow], list[ValidationCheck]]:
        normalized_rows: list[GeneratedRow] = []
        checks: list[ValidationCheck] = []

        for row_index, row in enumerate(rows, start=1):
            normalized_values = dict(row.values)
            warnings: list[str] = []
            for column in schema.columns:
                value = normalized_values.get(column.name)
                normalized, warning = _normalize_value(column, value)
                normalized_values[column.name] = normalized
                if warning:
                    warnings.append(f"row {row_index} {column.name}: {warning}")
            normalized_rows.append(GeneratedRow(values=normalized_values))
            checks.append(
                ValidationCheck(
                    name=f"{check_prefix}:row_{row_index}",
                    passed=not any("filled" in warning for warning in warnings),
                    detail="; ".join(warnings),
                )
            )

        # Drop empty-detail passing checks to keep output compact.
        return normalized_rows, [check for check in checks if check.detail or not check.passed]

    def validate_record(
        self,
        record: dict[str, str],
        schema: TableSchema,
    ) -> tuple[dict[str, str], list[str]]:
        """
        验证单条记录。

        :param record: 原始记录
        :param schema: 表结构
        :return: (处理后的记录, 警告列表)
        """
        warnings: list[str] = []
        validated = dict(record)

        for column in schema.columns:
            value = validated.get(column.name)

            # 检查 NULL 值
            if value is None:
                if not column.nullable and not column.is_auto_primary_key:
                    warnings.append(f"{column.name} cannot be NULL")
                continue

            # 字段截断验证
            truncated, warning = truncate_field(column, value)
            if truncated != value:
                warnings.append(f"{column.name}: {warning}")
                validated[column.name] = truncated

        return validated, warnings


def _normalize_value(column: TableColumn, value: str | None) -> tuple[str | None, str]:
    if value == DEFAULT_MARKER and not column.is_auto_primary_key:
        value = _fallback_value(column)
        return value, "filled runtime default for unresolved [DEFAULT]"

    if value is None:
        if column.nullable or column.is_auto_primary_key:
            return None, ""
        return _fallback_value(column), "filled runtime default for required NULL"

    # 字段截断验证
    truncated_value, truncate_warning = truncate_field(column, value)
    if truncated_value != value:
        return truncated_value, truncate_warning

    return value, ""


def truncate_field(column: TableColumn, value: str) -> tuple[str, str]:
    """
    根据字段类型截断值。

    - VARCHAR/CHAR/TEXT: 直接截断到 max_length
    - INT/BIGINT: 截断为 max_length 位数的最大值
    - 其他类型: 不处理
    """
    if not value:
        return value, ""

    # 字符串类型截断
    if column.max_length > 0 and _is_text_type(column.type):
        if len(value) > column.max_length:
            return value[:column.max_length], f"truncated string from {len(value)} to {column.max_length} chars"

    # 数值类型截断
    if column.max_length > 0 and _is_numeric_type(column.type):
        truncated = _truncate_numeric(value, column.max_length)
        if truncated != value:
            return truncated, f"truncated numeric from {value} to {truncated} (max {column.max_length} digits)"

    return value, ""


def _truncate_numeric(value: str, max_length: int) -> str:
    """截断数值为指定位数"""
    try:
        num = int(value)
        max_val = 10 ** max_length - 1
        if num > max_val:
            return str(max_val)
        return str(num)
    except ValueError:
        # 非数字，返回最大正值
        return str(10 ** max_length - 1)


def _fallback_value(column: TableColumn) -> str:
    if column.default_value:
        return str(column.default_value)

    lowered = column.type.lower()
    if any(token in lowered for token in ("int", "decimal", "float", "double", "numeric")):
        return "0"
    if "datetime" in lowered or "timestamp" in lowered:
        return "1970-01-01 00:00:00"
    if "date" in lowered:
        return "1970-01-01"
    if lowered.startswith("time"):
        return "00:00:00"
    return f"{column.name}_1"


def _is_text_type(data_type: str) -> bool:
    lowered = data_type.lower()
    return any(token in lowered for token in ("char", "text", "json"))


def _is_numeric_type(data_type: str) -> bool:
    """判断是否为数值类型"""
    lowered = data_type.lower()
    return any(token in lowered for token in ("int", "bigint", "smallint", "tinyint", "mediumint"))
