from __future__ import annotations

import hashlib
from datetime import datetime

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
    def __init__(self, dict_rule_resolver=None):
        self._dict_rule_resolver = dict_rule_resolver

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
