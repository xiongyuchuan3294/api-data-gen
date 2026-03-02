from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import (
    ColumnPlan,
    FieldMatchRelation,
    InterfaceTarget,
    PlanningDraft,
    RequirementSummary,
    ScenarioDraft,
    TableColumn,
    TableDataPlan,
    TableSchema,
)
from api_data_gen.services.data_generation_service import DataGenerationService
from api_data_gen.services.insert_render_service import InsertRenderService
from api_data_gen.services.field_match_alignment_service import FieldMatchAlignmentService
from api_data_gen.services.field_match_validation_service import FieldMatchValidationService


class _FakePlanningService:
    def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
        return PlanningDraft(
            requirement=RequirementSummary(
                summary="本地造数闭环",
                constraints=["不调用LLM"],
                keywords=["造数", "SQL"],
            ),
            scenarios=[
                ScenarioDraft(
                    id="custTransInfo:baseline",
                    title="custTransInfo baseline replay",
                    api_name="custTransInfo",
                    api_path="/wst/custTransInfo",
                    objective="回放样例",
                )
            ],
            table_plans=[
                TableDataPlan(
                    table_name="aml_f_wst_alert_cust_trans_info",
                    primary_keys=["uuid"],
                    fixed_conditions=["cust_id = ''962020122711000002''"],
                    row_hint=2,
                    column_plans=[
                        ColumnPlan("uuid", "generated", True, [], ""),
                        ColumnPlan("cust_id", "condition", True, ["962020122711000002"], ""),
                        ColumnPlan("receive_pay_cd", "dictionary", False, ["01", "02"], ""),
                        ColumnPlan("trans_amount", "default", True, [], ""),
                        ColumnPlan("memo", "optional", False, [], ""),
                    ],
                )
            ],
        )


class _FakeSchemaRepository:
    def get_table_schema(self, table_name: str) -> TableSchema:
        if table_name != "aml_f_wst_alert_cust_trans_info":
            raise AssertionError(f"unexpected table: {table_name}")
        return TableSchema(
            table_name=table_name,
            table_type="innodb",
            columns=[
                TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                TableColumn("receive_pay_cd", "varchar(2)", True, None, "", False, False, 2),
                TableColumn("trans_amount", "decimal(20,4)", False, None, "", False, False, 20),
                TableColumn("memo", "varchar(20)", True, None, "", False, False, 20),
            ],
            primary_keys=["uuid"],
        )


class _FakeFieldMatchRepository:
    def __init__(self, relations: list[FieldMatchRelation] | None = None):
        self._relations = list(relations or [])

    def list_relations(self, table_names: list[str]) -> list[FieldMatchRelation]:
        return [
            relation
            for relation in self._relations
            if relation.target_table in table_names and relation.source_table in table_names
        ]


class DataGenerationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DataGenerationService(
            planning_service=_FakePlanningService(),
            schema_repository=_FakeSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

    def test_generate_materializes_rows_and_insert_sql(self) -> None:
        report = self.service.generate(
            requirement_text="Phase 3 本地造数",
            interfaces=[InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo")],
            sample_limit=2,
        )

        self.assertEqual(1, len(report.generated_tables))
        generated_table = report.generated_tables[0]
        self.assertEqual("aml_f_wst_alert_cust_trans_info", generated_table.table_name)
        self.assertEqual(2, generated_table.row_count)

        first_row = generated_table.rows[0].values
        second_row = generated_table.rows[1].values
        self.assertEqual("AMLFWSTA_001", first_row["uuid"])
        self.assertEqual("AMLFWSTA_002", second_row["uuid"])
        self.assertEqual("962020122711000002", first_row["cust_id"])
        self.assertEqual("962020122711000002", second_row["cust_id"])
        self.assertEqual("01", first_row["receive_pay_cd"])
        self.assertEqual("02", second_row["receive_pay_cd"])
        self.assertEqual("0", first_row["trans_amount"])
        self.assertIsNone(first_row["memo"])
        self.assertEqual("", report.generation_tag)
        self.assertEqual(0, len(report.validation_checks))

        rendered_sql = generated_table.insert_sql[0]
        self.assertIn("INSERT INTO `aml_f_wst_alert_cust_trans_info`", rendered_sql)
        self.assertIn("'AMLFWSTA_001'", rendered_sql)
        self.assertIn("NULL", rendered_sql)

    def test_render_uses_default_for_auto_primary_key_and_escapes_strings(self) -> None:
        schema = TableSchema(
            table_name="demo_table",
            table_type="innodb",
            columns=[
                TableColumn("id", "bigint(20)", False, None, "", True, True, 20),
                TableColumn("customer_name", "varchar(20)", False, None, "", False, False, 20),
                TableColumn("amount", "decimal(20,4)", False, None, "", False, False, 20),
            ],
            primary_keys=["id"],
        )
        plan = TableDataPlan(
            table_name="demo_table",
            primary_keys=["id"],
            row_hint=1,
            column_plans=[
                ColumnPlan("id", "generated", True, [], ""),
                ColumnPlan("customer_name", "sample", True, ["O'Hara"], ""),
                ColumnPlan("amount", "sample", True, ["12.50"], ""),
            ],
        )

        rows = self.service.generate_table_rows(plan, schema)
        rendered_sql = InsertRenderService().render_table(schema, rows)

        self.assertEqual("[DEFAULT]", rows[0].values["id"])
        self.assertIn("DEFAULT", rendered_sql)
        self.assertIn("'O''Hara'", rendered_sql)
        self.assertIn("12.50", rendered_sql)

    def test_primary_key_sample_source_is_still_generated(self) -> None:
        schema = TableSchema(
            table_name="demo_table",
            table_type="innodb",
            columns=[
                TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
            ],
            primary_keys=["uuid"],
        )
        plan = TableDataPlan(
            table_name="demo_table",
            primary_keys=["uuid"],
            row_hint=2,
            column_plans=[
                ColumnPlan("uuid", "sample", True, ["OLD_UUID_1", "OLD_UUID_2"], ""),
                ColumnPlan("cust_id", "condition", True, ["962020122711000002"], ""),
            ],
        )

        rows = self.service.generate_table_rows(plan, schema)

        self.assertEqual("DEMOTABL_001", rows[0].values["uuid"])
        self.assertEqual("DEMOTABL_002", rows[1].values["uuid"])
        self.assertEqual("962020122711000002", rows[0].values["cust_id"])

    def test_generation_tag_changes_generated_primary_keys(self) -> None:
        report = self.service.generate(
            requirement_text="Phase 3 本地造数",
            interfaces=[InterfaceTarget(name="custTransInfo", path="/wst/custTransInfo")],
            sample_limit=2,
            generation_tag="run-20260302",
        )

        self.assertEqual("RUN20260302", report.generation_tag)
        rows = report.generated_tables[0].rows
        self.assertNotEqual("AMLFWSTA_001", rows[0].values["uuid"])
        self.assertTrue(str(rows[0].values["uuid"]).startswith("AMLFWSTA_"))
        self.assertTrue(str(rows[0].values["uuid"]).endswith("_001"))
        self.assertTrue(str(rows[1].values["uuid"]).endswith("_002"))

    def test_generation_tag_changes_generated_numeric_primary_keys(self) -> None:
        schema = TableSchema(
            table_name="demo_numeric_table",
            table_type="innodb",
            columns=[
                TableColumn("id", "int(11)", False, None, "", True, False, 11),
                TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
            ],
            primary_keys=["id"],
        )
        plan = TableDataPlan(
            table_name="demo_numeric_table",
            primary_keys=["id"],
            row_hint=2,
            column_plans=[
                ColumnPlan("id", "generated", True, [], ""),
                ColumnPlan("cust_id", "condition", True, ["962020122711000002"], ""),
            ],
        )

        rows = self.service.generate_table_rows(plan, schema, generation_tag="batch-20260302")

        self.assertTrue(str(rows[0].values["id"]).isdigit())
        self.assertTrue(str(rows[1].values["id"]).isdigit())
        self.assertNotEqual("1", rows[0].values["id"])
        self.assertNotEqual("2", rows[1].values["id"])
        self.assertNotEqual(rows[0].values["id"], rows[1].values["id"])

    def test_generate_aligns_shared_sample_columns_across_tables(self) -> None:
        class _AlignedPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="aligned shared columns", constraints=[], keywords=[]),
                    table_plans=[
                        TableDataPlan(
                            table_name="table_a",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("drft_no", "sample", True, ["D1", "D2"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="table_b",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("drft_no", "sample", True, ["D2", "D3"], ""),
                            ],
                        ),
                    ],
                )

        class _AlignedSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("drft_no", "varchar(32)", False, None, "", False, False, 32),
                    ],
                    primary_keys=["uuid"],
                )

        service = DataGenerationService(
            planning_service=_AlignedPlanningService(),
            schema_repository=_AlignedSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

        report = service.generate(
            requirement_text="aligned shared columns",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
        )

        self.assertEqual(1, len(report.validation_checks))
        self.assertEqual("shared_column:drft_no", report.validation_checks[0].name)
        self.assertTrue(report.validation_checks[0].passed)
        self.assertIn("['D2']", report.validation_checks[0].detail)
        self.assertEqual("D2", report.generated_tables[0].rows[0].values["drft_no"])
        self.assertEqual("D2", report.generated_tables[1].rows[1].values["drft_no"])

    def test_generate_reports_cross_table_consistency_failure(self) -> None:
        class _ConflictPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="cross table", constraints=[], keywords=[]),
                    table_plans=[
                        TableDataPlan(
                            table_name="table_a",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("cust_id", "condition", True, ["A100"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="table_b",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("cust_id", "condition", True, ["B200"], ""),
                            ],
                        ),
                    ],
                )

        class _ConflictSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                    ],
                    primary_keys=["uuid"],
                )

        service = DataGenerationService(
            planning_service=_ConflictPlanningService(),
            schema_repository=_ConflictSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

        report = service.generate(
            requirement_text="cross table",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
        )

        self.assertEqual(1, len(report.validation_checks))
        self.assertEqual("cross_table:cust_id", report.validation_checks[0].name)
        self.assertFalse(report.validation_checks[0].passed)
        self.assertIn("A100, B200", report.validation_checks[0].detail)

    def test_generate_aligns_cross_name_fields_via_field_match_relations(self) -> None:
        class _FieldMatchPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="field match", constraints=[], keywords=[]),
                    table_plans=[
                        TableDataPlan(
                            table_name="source_table",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("source_no", "sample", True, ["S1", "S2"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="target_table",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("target_no", "sample", True, ["T1", "T2"], ""),
                            ],
                        ),
                    ],
                )

        class _FieldMatchSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                columns = [TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64)]
                if table_name == "source_table":
                    columns.append(TableColumn("source_no", "varchar(32)", False, None, "", False, False, 32))
                else:
                    columns.append(TableColumn("target_no", "varchar(32)", False, None, "", False, False, 32))
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=columns,
                    primary_keys=["uuid"],
                )

        field_match_repository = _FakeFieldMatchRepository(
            [
                FieldMatchRelation(
                    target_table="target_table",
                    target_field="target_no",
                    source_table="source_table",
                    source_field="source_no",
                    match_reason="explicit relation",
                )
            ]
        )
        service = DataGenerationService(
            planning_service=_FieldMatchPlanningService(),
            schema_repository=_FieldMatchSchemaRepository(),
            insert_render_service=InsertRenderService(),
            field_match_alignment_service=FieldMatchAlignmentService(field_match_repository),
            field_match_validation_service=FieldMatchValidationService(field_match_repository),
        )

        report = service.generate(
            requirement_text="field match",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
        )

        source_table = next(table for table in report.generated_tables if table.table_name == "source_table")
        target_table = next(table for table in report.generated_tables if table.table_name == "target_table")
        self.assertEqual("S1", source_table.rows[0].values["source_no"])
        self.assertEqual("S2", source_table.rows[1].values["source_no"])
        self.assertEqual("S1", target_table.rows[0].values["target_no"])
        self.assertEqual("S2", target_table.rows[1].values["target_no"])
        field_check = next(check for check in report.validation_checks if check.name == "field_match:target_table.target_no<-source_table.source_no")
        self.assertTrue(field_check.passed)
        self.assertIn("reason=explicit relation", field_check.detail)

    def test_generate_reports_field_match_conflict_for_condition_target(self) -> None:
        class _FieldMatchConflictPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="field match conflict", constraints=[], keywords=[]),
                    table_plans=[
                        TableDataPlan(
                            table_name="source_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("source_no", "sample", True, ["SRC1"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="target_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("target_no", "condition", True, ["TGT1"], ""),
                            ],
                        ),
                    ],
                )

        class _FieldMatchConflictSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                columns = [TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64)]
                if table_name == "source_table":
                    columns.append(TableColumn("source_no", "varchar(32)", False, None, "", False, False, 32))
                else:
                    columns.append(TableColumn("target_no", "varchar(32)", False, None, "", False, False, 32))
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=columns,
                    primary_keys=["uuid"],
                )

        field_match_repository = _FakeFieldMatchRepository(
            [
                FieldMatchRelation(
                    target_table="target_table",
                    target_field="target_no",
                    source_table="source_table",
                    source_field="source_no",
                    match_reason="conflict relation",
                )
            ]
        )
        service = DataGenerationService(
            planning_service=_FieldMatchConflictPlanningService(),
            schema_repository=_FieldMatchConflictSchemaRepository(),
            insert_render_service=InsertRenderService(),
            field_match_alignment_service=FieldMatchAlignmentService(field_match_repository),
            field_match_validation_service=FieldMatchValidationService(field_match_repository),
        )

        report = service.generate(
            requirement_text="field match conflict",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
        )

        target_table = next(table for table in report.generated_tables if table.table_name == "target_table")
        self.assertEqual("TGT1", target_table.rows[0].values["target_no"])
        field_check = next(check for check in report.validation_checks if check.name == "field_match:target_table.target_no<-source_table.source_no")
        self.assertFalse(field_check.passed)
        self.assertIn("target=['TGT1']", field_check.detail)
        self.assertIn("source=['SRC1']", field_check.detail)

    def test_generate_merges_ai_rows_and_populates_scenario_generations(self) -> None:
        class _AiPlanningService:
            def build_draft(
                self,
                requirement_text: str,
                interfaces: list[InterfaceTarget],
                sample_limit: int = 3,
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
                use_ai_scenarios: bool = False,
            ) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="ai generation", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="ai:cashflow:1",
                            title="AI cashflow",
                            api_name="multi_api",
                            api_path="",
                            objective="补齐非本地规则字段。",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "生成 1 条交易记录"},
                            generation_source="ai",
                        )
                    ],
                    table_plans=[
                        TableDataPlan(
                            table_name="demo_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("cust_id", "sample", True, ["OLD_CUST"], ""),
                                ColumnPlan("trans_amount", "default", True, [], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _AiSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("cust_id", "varchar(18)", False, None, "客户号", False, False, 18),
                        TableColumn("trans_amount", "decimal(20,4)", False, None, "", False, False, 20),
                        TableColumn("memo", "varchar(5)", True, None, "", False, False, 5),
                    ],
                    primary_keys=["uuid"],
                )

        class _AiSampleRepository:
            def __init__(self):
                self.requests: list[tuple[str, int]] = []

            def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
                self.requests.append((table_name, limit))
                return [{"uuid": "OLD_UUID", "cust_id": "962020122711000002", "trans_amount": "10.00", "memo": "legacy"}]

        class _FakeAiAnalysisService:
            def __init__(self):
                self.calls: list[dict[str, object]] = []

            def analyze(
                self,
                table_name: str,
                schema: TableSchema,
                sample_rows: list[dict[str, str]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> str:
                self.calls.append(
                    {
                        "table_name": table_name,
                        "sample_rows": sample_rows,
                        "fixed_values": fixed_values,
                        "dependent_fixed_values": dependent_fixed_values,
                    }
                )
                return '{"memo":"prefer short text"}'

        class _FakeAiDataGenerationService:
            def __init__(self):
                self.calls: list[dict[str, object]] = []

            def generate(
                self,
                scenario: ScenarioDraft,
                schemas: dict[str, TableSchema],
                sample_rows_by_table: dict[str, list[dict[str, str]]],
                local_generated_columns: dict[str, set[str]],
                analysis_by_table: dict[str, str],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, list[dict[str, str]]]:
                self.calls.append(
                    {
                        "scenario": scenario,
                        "sample_rows_by_table": sample_rows_by_table,
                        "local_generated_columns": local_generated_columns,
                        "analysis_by_table": analysis_by_table,
                        "fixed_values": fixed_values,
                        "dependent_fixed_values": dependent_fixed_values,
                    }
                )
                return {"demo_table": [{"trans_amount": "88.50", "memo": "HELLOWORLD"}]}

        sample_repository = _AiSampleRepository()
        ai_analysis_service = _FakeAiAnalysisService()
        ai_data_generation_service = _FakeAiDataGenerationService()
        service = DataGenerationService(
            planning_service=_AiPlanningService(),
            schema_repository=_AiSchemaRepository(),
            insert_render_service=InsertRenderService(),
            sample_repository=sample_repository,
            ai_data_analysis_service=ai_analysis_service,
            ai_data_generation_service=ai_data_generation_service,
        )

        report = service.generate(
            requirement_text="ai generation",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            generation_tag="run-20260302",
            fixed_values=["cust_id=962020122711000002"],
            dependent_fixed_values=["transactionkey depends on alert_date"],
            use_ai_data=True,
        )

        self.assertEqual("RUN20260302", report.generation_tag)
        self.assertEqual(1, len(report.scenario_generations))
        self.assertEqual("ai:cashflow:1", report.generated_tables[0].scenario_id)
        self.assertEqual("AI cashflow", report.scenario_generations[0].scenario_title)
        first_row = report.generated_tables[0].rows[0].values
        self.assertEqual("962020122711000002", first_row["cust_id"])
        self.assertEqual("88.50", first_row["trans_amount"])
        self.assertEqual("HELLO", first_row["memo"])
        self.assertTrue(str(first_row["uuid"]).startswith("DEMOTABL_"))
        validation_check = next(
            check
            for check in report.validation_checks
            if check.name == "ai:cashflow:1:record_validation:demo_table:row_1"
        )
        self.assertTrue(validation_check.passed)
        self.assertIn("truncated to 5 chars", validation_check.detail)
        self.assertEqual("[DEFAULT]", ai_analysis_service.calls[0]["sample_rows"][0]["cust_id"])
        self.assertEqual(
            {"demo_table": {"cust_id"}},
            ai_data_generation_service.calls[0]["local_generated_columns"],
        )
        self.assertEqual(
            ["cust_id=962020122711000002"],
            ai_data_generation_service.calls[0]["fixed_values"],
        )


if __name__ == "__main__":
    unittest.main()
