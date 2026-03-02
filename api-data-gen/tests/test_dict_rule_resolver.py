from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.services.dict_rule_resolver import DictRuleResolver


class _FakeDictRepository:
    def __init__(self, import_codes=None, mapping_columns=None, mapped_codes=None, search_codes=None):
        if isinstance(import_codes, dict):
            self._import_codes_by_type = {key: list(value) for key, value in import_codes.items()}
        else:
            self._import_codes_by_type = {"*": list(import_codes or [])}
        self._mapping_columns = mapping_columns or []
        self._mapped_codes = mapped_codes or {}
        self._search_codes = search_codes or []

    def get_import_codes(self, type_code: str) -> list[str]:
        if type_code in self._import_codes_by_type:
            return list(self._import_codes_by_type[type_code])
        return list(self._import_codes_by_type.get("*", []))

    def get_mapping_columns(self, db_col: str) -> list[str]:
        return list(self._mapping_columns)

    def get_sys_codes(self, mapping_col: str) -> list[str]:
        return list(self._mapped_codes.get(mapping_col, []))

    def search_codes(self, type_code_like: str, type_name_like: str) -> list[str]:
        return list(self._search_codes)


class DictRuleResolverTest(unittest.TestCase):
    def test_import_codes_have_highest_priority(self) -> None:
        resolver = DictRuleResolver(_FakeDictRepository(import_codes=["01", "02"], mapping_columns=["receive_pay"]))
        self.assertEqual(["01", "02"], resolver.resolve_code_values("receive_pay_cd", "资金收付表示"))

    def test_single_mapping_uses_system_dict(self) -> None:
        resolver = DictRuleResolver(
            _FakeDictRepository(mapping_columns=["receive_pay"], mapped_codes={"receive_pay": ["01", "02"]})
        )
        self.assertEqual(["01", "02"], resolver.resolve_code_values("receive_pay_cd", "资金收付表示"))

    def test_mapping_column_prefers_import_codes_before_system_dict(self) -> None:
        resolver = DictRuleResolver(
            _FakeDictRepository(
                import_codes={"receive_pay": ["A", "B"]},
                mapping_columns=["receive_pay"],
                mapped_codes={"receive_pay": ["01", "02"]},
            )
        )
        self.assertEqual(["A", "B"], resolver.resolve_code_values("receive_pay_cd", "资金收付表示"))

    def test_comment_search_is_last_fallback(self) -> None:
        resolver = DictRuleResolver(_FakeDictRepository(search_codes=["01", "02"]))
        self.assertEqual(["01", "02"], resolver.resolve_code_values("receive_pay_cd", "资金收付表示"))


if __name__ == "__main__":
    unittest.main()
