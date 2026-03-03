from __future__ import annotations

import re

from api_data_gen.domain.models import GeneratedTable, ValidationCheck


class SqlScriptExportService:
    _SCENARIO_HEADER_RE = re.compile(r"^-- 场景:\s+(\S+)", re.MULTILINE)

    def __init__(self, table_locator):
        self._table_locator = table_locator

    def render(
        self,
        generated_tables: list[GeneratedTable],
        validation_checks: list[ValidationCheck],
        generation_tag: str = "",
    ) -> str:
        return self._render(
            generated_tables=generated_tables,
            validation_checks=validation_checks,
            generation_tag=generation_tag,
            include_file_header=True,
            batch_label="",
        )

    def append_missing_scenarios(
        self,
        existing_script: str,
        generated_tables: list[GeneratedTable],
        validation_checks: list[ValidationCheck],
        generation_tag: str = "",
        batch_label: str = "",
    ) -> str:
        existing_scenarios = self.extract_scenario_ids(existing_script)
        missing_tables = _filter_missing_scenario_tables(generated_tables, existing_scenarios)
        if not existing_script.strip():
            return self.render(
                generated_tables=generated_tables,
                validation_checks=validation_checks,
                generation_tag=generation_tag,
            )
        if not missing_tables:
            return existing_script
        append_block = self._render(
            generated_tables=missing_tables,
            validation_checks=validation_checks,
            generation_tag=generation_tag,
            include_file_header=False,
            batch_label=batch_label,
        )
        return existing_script.rstrip() + "\n\n" + append_block

    @classmethod
    def extract_scenario_ids(cls, script: str) -> set[str]:
        return {match.group(1).strip() for match in cls._SCENARIO_HEADER_RE.finditer(script) if match.group(1).strip()}

    def _render(
        self,
        generated_tables: list[GeneratedTable],
        validation_checks: list[ValidationCheck],
        generation_tag: str,
        include_file_header: bool,
        batch_label: str,
    ) -> str:
        lines = [
            "-- 由 api-data-gen 生成",
        ]
        if not include_file_header:
            lines = [f"-- 追加批次: {batch_label or 'append'}"]
        if generation_tag:
            lines.append(f"-- 生成标签: {generation_tag}")
        if include_file_header:
            lines.extend(
                [
                    "SET NAMES utf8mb4;",
                    "",
                ]
            )
        else:
            lines.append("")
        lines.extend(self._render_validation_checks(validation_checks))
        lines.append("START TRANSACTION;")
        lines.append("")

        current_schema = None
        current_scenario = None
        for generated_table in generated_tables:
            if not generated_table.insert_sql:
                continue
            scenario_key = (generated_table.scenario_id, generated_table.scenario_title)
            if scenario_key != current_scenario and any(scenario_key):
                if current_scenario is not None:
                    lines.append("")
                # 添加数据来源标识
                source_label = ""
                source = generated_table.generation_source
                if source == "ai":
                    source_label = " [AI生成]"
                elif source == "hybrid":
                    source_label = " [混合: AI场景+本地数据]"
                elif source == "local":
                    source_label = " [本地生成]"
                lines.append(
                    f"-- 场景: {generated_table.scenario_id or '[无ID]'} "
                    f"{generated_table.scenario_title}{source_label}".rstrip()
                )
                current_scenario = scenario_key
            schema_name, _ = self._table_locator.resolve_table_location(generated_table.table_name)
            if schema_name != current_schema:
                if current_schema is not None:
                    lines.append("")
                lines.append(f"USE `{schema_name}`;")
                current_schema = schema_name
            lines.extend(generated_table.insert_sql)
            lines.append("")

        lines.append("COMMIT;")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_validation_checks(validation_checks: list[ValidationCheck]) -> list[str]:
        if not validation_checks:
            return []

        lines = ["-- 校验检查"]
        for check in validation_checks:
            status = "通过" if check.passed else "失败"
            detail = f" {check.detail}" if check.detail else ""
            lines.append(f"-- [{status}] {check.name}{detail}")
        lines.append("")
        return lines


def _filter_missing_scenario_tables(
    generated_tables: list[GeneratedTable],
    existing_scenarios: set[str],
) -> list[GeneratedTable]:
    if not existing_scenarios:
        return list(generated_tables)
    filtered: list[GeneratedTable] = []
    for generated_table in generated_tables:
        scenario_id = (generated_table.scenario_id or "").strip()
        if not scenario_id or scenario_id not in existing_scenarios:
            filtered.append(generated_table)
    return filtered
