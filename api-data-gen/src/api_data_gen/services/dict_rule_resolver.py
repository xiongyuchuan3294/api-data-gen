from __future__ import annotations


class DictRuleResolver:
    def __init__(self, dict_repository):
        self._dict_repository = dict_repository

    def resolve_code_values(self, column_name: str, column_comment: str) -> list[str]:
        import_codes = self._dict_repository.get_import_codes(column_name)
        if import_codes:
            return import_codes

        mapping_columns = self._dict_repository.get_mapping_columns(column_name)
        if len(mapping_columns) == 1:
            mapped_import_codes = self._dict_repository.get_import_codes(mapping_columns[0])
            if mapped_import_codes:
                return mapped_import_codes
            mapped_codes = self._dict_repository.get_sys_codes(mapping_columns[0])
            if mapped_codes:
                return mapped_codes

        if len(mapping_columns) > 1:
            candidates: list[str] = []
            for mapping_column in mapping_columns:
                candidates.extend(self._dict_repository.get_import_codes(mapping_column))
                candidates.extend(self._dict_repository.get_sys_codes(mapping_column))
            return _deduplicate(candidates)

        if column_comment:
            return _deduplicate(self._dict_repository.search_codes(column_name, column_comment))
        return []


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
