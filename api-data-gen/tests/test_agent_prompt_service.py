from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.agents.prompt_service import AgentPromptService
from api_data_gen.domain.models import RequirementSummary, ScenarioDraft, TableColumn, TableDataPlan, TableSchema


class AgentPromptServiceTest(unittest.TestCase):
    def test_build_scenario_prompt_contains_local_context(self) -> None:
        service = AgentPromptService()

        prompt = service.build_scenario_prompt(
            requirement=RequirementSummary(summary="为票据链路生成测试场景", constraints=["优先本地规则"], keywords=["agent"]),
            interface_infos=[],
            schemas={
                "demo_table": TableSchema(
                    table_name="demo_table",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
            table_plans=[TableDataPlan(table_name="demo_table")],
            local_fields_by_table={"demo_table": ["cust_id"]},
            fixed_values=["cust_id=1"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
            local_reference_scenarios=[
                ScenarioDraft(
                    id="baseline",
                    title="baseline",
                    api_name="demo",
                    api_path="/demo",
                    objective="baseline",
                    tables=["demo_table"],
                )
            ],
        )

        self.assertEqual("generate_test_scenarios", prompt.name)
        self.assertIn("cust_id=1", prompt.user_prompt)
        self.assertIn("baseline", prompt.user_prompt)
        self.assertIn("tableRequirements", prompt.expected_output)

    def test_build_data_prompt_contains_scenario_placeholder(self) -> None:
        service = AgentPromptService()

        prompt = service.build_data_prompt(
            requirement=RequirementSummary(summary="生成测试数据", constraints=[], keywords=[]),
            schemas={
                "demo_table": TableSchema(
                    table_name="demo_table",
                    table_type="innodb",
                    columns=[TableColumn("amount", "decimal(20,4)", False, None, "", False, False, 20)],
                    primary_keys=[],
                )
            },
            table_plans=[TableDataPlan(table_name="demo_table")],
            sample_rows_by_table={"demo_table": [{"amount": "10.00"}]},
            local_fields_by_table={"demo_table": ["cust_id"]},
        )

        self.assertEqual("generate_test_data", prompt.name)
        self.assertIn("{{SELECTED_SCENARIO_JSON}}", prompt.user_prompt)
        self.assertIn("demo_table", prompt.user_prompt)


if __name__ == "__main__":
    unittest.main()
