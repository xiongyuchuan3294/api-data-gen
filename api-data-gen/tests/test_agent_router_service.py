from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.agents.router_service import AgentRouterService
from api_data_gen.domain.models import InterfaceInfo, InterfaceTarget, RequirementSummary, SqlInfo, TableColumn, TableSchema


class AgentRouterServiceTest(unittest.TestCase):
    def test_build_prompt_outputs_router_prompt_spec(self) -> None:
        service = AgentRouterService()

        prompt = service.build_prompt(
            operation="generate",
            requirement=RequirementSummary(summary="复杂跨表测试", constraints=["需要多场景"], keywords=["agent"]),
            interfaces=[InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo")],
            interface_infos=[InterfaceInfo(name="custTransInfo", path="/wst/custTransInfo", sql_infos=[SqlInfo("table_a", ["cust_id='1'"])])],
            schemas={
                "table_a": TableSchema(
                    table_name="table_a",
                    table_type="innodb",
                    columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                    primary_keys=[],
                )
            },
            local_fields_by_table={"table_a": ["cust_id"]},
            fixed_values=["cust_id=1"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
        )

        self.assertEqual("route_generation_strategy", prompt.name)
        self.assertIn("scenario_strategy", prompt.expected_output)
        self.assertIn("custTransInfo", prompt.user_prompt)
        self.assertIn("table_a", prompt.user_prompt)
        self.assertIn("generate_scenarios_ai", prompt.user_prompt)

    def test_default_decision_describes_external_agent_mode(self) -> None:
        decision = AgentRouterService.default_decision("generate", "external agent decides")

        self.assertEqual("agent_prompt", decision.mode)
        self.assertEqual("agent_decides", decision.scenario_strategy)
        self.assertEqual("agent_decides", decision.data_strategy)
        self.assertIn("generate_scenarios_local", decision.selected_skills)


if __name__ == "__main__":
    unittest.main()
