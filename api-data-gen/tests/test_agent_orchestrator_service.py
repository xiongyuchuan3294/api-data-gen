from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.agents.orchestrator_service import AgentOrchestratorService
from api_data_gen.domain.models import (
    InterfaceInfo,
    InterfaceTarget,
    PlanningDraft,
    RequirementSummary,
    ScenarioDraft,
    SqlInfo,
    TableColumn,
    TableDataPlan,
    TableSchema,
)

class _FakeInterfaceTraceService:
    def get_table_info(self, api_name: str, api_path: str) -> InterfaceInfo:
        return InterfaceInfo(
            name=api_name,
            path=api_path,
            sql_infos=[SqlInfo("demo_table", ["cust_id = '1'"])],
        )


class _FakeSchemaService:
    def get_all_table_schemas(self, interface_infos: list[InterfaceInfo]) -> dict[str, TableSchema]:
        return {
            "demo_table": TableSchema(
                table_name="demo_table",
                table_type="innodb",
                columns=[TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18)],
                primary_keys=[],
            )
        }


class _FakeLocalFieldRuleService:
    def identify_local_fields(self, schema: TableSchema) -> set[str]:
        return {"cust_id"}


class _FakePlanningService:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def build_draft(
        self,
        requirement_text: str,
        interfaces: list[InterfaceTarget],
        sample_limit: int = 3,
        fixed_values: list[str] | None = None,
        dependent_fixed_values: list[str] | None = None,
        use_ai_scenarios: bool = False,
    ) -> PlanningDraft:
        self.calls.append(
            {
                "use_ai_scenarios": use_ai_scenarios,
                "fixed_values": fixed_values,
                "dependent_fixed_values": dependent_fixed_values,
            }
        )
        return PlanningDraft(
            requirement=RequirementSummary(summary="draft", constraints=[], keywords=[]),
            scenarios=[
                ScenarioDraft(
                    id="scenario-1",
                    title="scenario-1",
                    api_name="demo",
                    api_path="/demo",
                    objective="demo objective",
                )
            ],
            table_plans=[TableDataPlan(table_name="demo_table")],
        )


class _FakeSampleRepository:
    def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
        return [{"cust_id": "1"}]


class AgentOrchestratorServiceTest(unittest.TestCase):
    def test_build_draft_returns_prompt_bundle_instead_of_final_scenarios(self) -> None:
        planning_service = _FakePlanningService()
        orchestrator = AgentOrchestratorService(
            planning_service=planning_service,
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            local_field_rule_service=_FakeLocalFieldRuleService(),
        )

        draft = orchestrator.build_draft(
            requirement_text="agent draft",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
            fixed_values=["cust_id=1"],
        )

        self.assertFalse(planning_service.calls[0]["use_ai_scenarios"])
        self.assertIsNotNone(draft.agent_run)
        self.assertEqual("agent_prompt", draft.agent_run.decision.mode)
        self.assertEqual([], draft.scenarios)
        self.assertIsNotNone(draft.agent_bundle)
        self.assertEqual(2, len(draft.agent_bundle.prompt_specs))
        self.assertEqual("generate_test_scenarios", draft.agent_bundle.prompt_specs[-1].name)
        self.assertEqual("build_table_plans_local", draft.agent_run.executed_skills[-1].skill_name)

    def test_generate_returns_prompt_bundle_and_samples_without_final_rows(self) -> None:
        orchestrator = AgentOrchestratorService(
            planning_service=_FakePlanningService(),
            interface_trace_service=_FakeInterfaceTraceService(),
            schema_service=_FakeSchemaService(),
            sample_repository=_FakeSampleRepository(),
            local_field_rule_service=_FakeLocalFieldRuleService(),
        )

        report = orchestrator.generate(
            requirement_text="agent generate",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
            generation_tag="RUN20260302",
        )

        self.assertIsNotNone(report.agent_run)
        self.assertEqual("agent_prompt", report.agent_run.decision.mode)
        self.assertEqual([], report.generated_tables)
        self.assertEqual("RUN20260302", report.generation_tag)
        self.assertIsNotNone(report.agent_bundle)
        self.assertEqual(3, len(report.agent_bundle.prompt_specs))
        self.assertEqual("generate_test_data", report.agent_bundle.prompt_specs[-1].name)
        self.assertEqual([{"cust_id": "1"}], report.agent_bundle.sample_rows_by_table["demo_table"])
        self.assertEqual("sample_table_data", report.agent_run.executed_skills[-1].skill_name)


if __name__ == "__main__":
    unittest.main()
