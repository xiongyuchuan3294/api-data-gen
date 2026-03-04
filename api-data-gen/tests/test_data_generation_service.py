from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.domain.models import (
    AiTableGenerationAdvice,
    ColumnPlan,
    FieldGenerationStrategy,
    InterfaceTarget,
    RelationRule,
    PlanningDraft,
    RequirementSummary,
    ScenarioDraft,
    StoredRelationStrategy,
    TableColumn,
    TableDataPlan,
    TableSchema,
)
from api_data_gen.services.data_generation_service import DataGenerationService
from api_data_gen.services.insert_render_service import InsertRenderService
from api_data_gen.services.relation_strategy_alignment_service import RelationStrategyAlignmentService
from api_data_gen.services.relation_strategy_validation_service import RelationStrategyValidationService
from api_data_gen.services.reusable_strategy_service import ReusableStrategyService


class _FakePlanningService:
    def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
        return PlanningDraft(
            requirement=RequirementSummary(
                summary="local generation loop",

                constraints=["do not call LLM"],
                keywords=["local generation", "SQL"],
            ),
            scenarios=[
                ScenarioDraft(
                    id="custTransInfo:baseline",
                    title="custTransInfo baseline replay",
                    api_name="custTransInfo",
                    api_path="/wst/custTransInfo",
                    objective="replay sample rows",
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



class _FakeReusableStrategyRepository:
    def __init__(self):
        self.field_records = []
        self.relation_records = []

    def list_field_strategies(self, table_names: list[str]):
        return [record for record in self.field_records if record.table_name in table_names]

    def save_field_strategies(self, strategies):
        by_key = {(record.table_name, record.field_name): record for record in self.field_records}
        for strategy in strategies:
            by_key[(strategy.table_name, strategy.field_name)] = strategy
        self.field_records = list(by_key.values())

    def list_relation_strategies(self, table_names: list[str]):
        return [
            record
            for record in self.relation_records
            if record.target_table in table_names or record.source_table in table_names
        ]

    def save_relation_strategies(self, strategies):
        by_key = {
            (record.target_table, record.target_field, record.source_table, record.source_field): record
            for record in self.relation_records
        }
        for strategy in strategies:
            by_key[(strategy.target_table, strategy.target_field, strategy.source_table, strategy.source_field)] = strategy
        self.relation_records = list(by_key.values())


class DataGenerationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DataGenerationService(
            planning_service=_FakePlanningService(),
            schema_repository=_FakeSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

    def test_generate_materializes_rows_and_insert_sql(self) -> None:
        report = self.service.generate(
            requirement_text="Phase 3 local generation",
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
            requirement_text="Phase 3 local generation",
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

    def test_generate_leaves_shared_sample_columns_unaligned_without_relation_rules(self) -> None:
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

        self.assertEqual([], report.validation_checks)
        self.assertEqual("D1", report.generated_tables[0].rows[0].values["drft_no"])
        self.assertEqual("D2", report.generated_tables[0].rows[1].values["drft_no"])
        self.assertEqual("D2", report.generated_tables[1].rows[0].values["drft_no"])
        self.assertEqual("D3", report.generated_tables[1].rows[1].values["drft_no"])

    def test_generate_does_not_apply_legacy_alignment_to_non_condition_columns(self) -> None:
        class _FallbackAlignmentPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="fallback shared columns", constraints=[], keywords=[]),
                    table_plans=[
                        TableDataPlan(
                            table_name="table_a",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("drft_no", "sample", True, ["D1", "D2"], ""),
                                ColumnPlan("ds", "sample", True, ["2020-12-20"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="table_b",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("drft_no", "sample", True, ["X1", "X2"], ""),
                                ColumnPlan("ds", "sample", True, ["20201220"], ""),
                            ],
                        ),
                    ],
                )

        class _FallbackAlignmentSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("drft_no", "varchar(32)", False, None, "", False, False, 32),
                        TableColumn("ds", "varchar(16)", False, None, "", False, False, 16),
                    ],
                    primary_keys=["uuid"],
                )

        service = DataGenerationService(
            planning_service=_FallbackAlignmentPlanningService(),
            schema_repository=_FallbackAlignmentSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

        report = service.generate(
            requirement_text="fallback shared columns",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
        )

        self.assertEqual([], report.validation_checks)
        self.assertEqual("D1", report.generated_tables[0].rows[0].values["drft_no"])
        self.assertEqual("X1", report.generated_tables[1].rows[0].values["drft_no"])
        self.assertEqual("2020-12-20", report.generated_tables[0].rows[0].values["ds"])
        self.assertEqual("20201220", report.generated_tables[1].rows[0].values["ds"])

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
        self.assertEqual("cross_table_alignment:cust_id", report.validation_checks[0].name)
        self.assertFalse(report.validation_checks[0].passed)
        self.assertIn("table_b has values not in table_a", report.validation_checks[0].detail)

    def test_generate_aligns_cross_name_fields_via_reusable_relation_strategies(self) -> None:
        class _RelationPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="relation strategy", constraints=[], keywords=[]),
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

        class _RelationSchemaRepository:
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

        repository = _FakeReusableStrategyRepository()
        repository.relation_records = [
            StoredRelationStrategy(
                target_table="target_table",
                target_field="target_no",
                source_table="source_table",
                source_field="source_no",
                strategy=FieldGenerationStrategy(
                    executor="local",
                    generator="copy_from_context",
                    params={"source_table": "source_table", "source_field": "source_no"},
                ),
                relation_reason="explicit relation",
                strategy_source="manual",
            )
        ]
        reusable_strategy_service = ReusableStrategyService(repository)
        service = DataGenerationService(
            planning_service=_RelationPlanningService(),
            schema_repository=_RelationSchemaRepository(),
            insert_render_service=InsertRenderService(),
            relation_strategy_alignment_service=RelationStrategyAlignmentService(reusable_strategy_service),
            relation_strategy_validation_service=RelationStrategyValidationService(reusable_strategy_service),
        )

        report = service.generate(
            requirement_text="relation strategy",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
        )

        source_table = next(table for table in report.generated_tables if table.table_name == "source_table")
        target_table = next(table for table in report.generated_tables if table.table_name == "target_table")
        self.assertEqual("S1", source_table.rows[0].values["source_no"])
        self.assertEqual("S2", source_table.rows[1].values["source_no"])
        self.assertEqual("S1", target_table.rows[0].values["target_no"])
        self.assertEqual("S2", target_table.rows[1].values["target_no"])
        field_check = next(check for check in report.validation_checks if check.name == "relation_strategy:target_table.target_no<-source_table.source_no")
        self.assertTrue(field_check.passed)
        self.assertIn("reason=explicit relation", field_check.detail)

    def test_generate_skips_legacy_cross_table_checks_for_explicit_relation_rules(self) -> None:
        class _ScenarioRelationPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="scenario relation validation", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="scenario:relation-check",
                            title="scenario relation validation",
                            api_name="demo",
                            api_path="/demo",
                            objective="prefer explicit relation validation",
                            tables=["table_a", "table_b"],
                            table_requirements={"table_a": "1 row", "table_b": "1 row"},
                            relation_rules=[
                                RelationRule(
                                    target_table="table_b",
                                    target_field="cust_id",
                                    source_table="table_a",
                                    source_field="cust_id",
                                    rationale="scenario relation",
                                )
                            ],
                        )
                    ],
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
                                ColumnPlan("cust_id", "condition", True, ["A100"], ""),
                            ],
                        ),
                    ],
                )

        class _ScenarioRelationSchemaRepository:
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

        repository = _FakeReusableStrategyRepository()
        reusable_strategy_service = ReusableStrategyService(repository)
        service = DataGenerationService(
            planning_service=_ScenarioRelationPlanningService(),
            schema_repository=_ScenarioRelationSchemaRepository(),
            insert_render_service=InsertRenderService(),
            relation_strategy_alignment_service=RelationStrategyAlignmentService(reusable_strategy_service),
            relation_strategy_validation_service=RelationStrategyValidationService(reusable_strategy_service),
            reusable_strategy_service=reusable_strategy_service,
        )

        report = service.generate(
            requirement_text="scenario relation validation",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
        )

        check_names = {check.name for check in report.validation_checks}
        self.assertIn("scenario:relation-check:relation_strategy:table_b.cust_id<-table_a.cust_id", check_names)
        self.assertNotIn("cross_table_alignment:cust_id", check_names)

    def test_generate_reports_relation_strategy_conflict_for_condition_target(self) -> None:
        class _RelationConflictPlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="relation strategy conflict", constraints=[], keywords=[]),
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

        class _RelationConflictSchemaRepository:
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

        repository = _FakeReusableStrategyRepository()
        repository.relation_records = [
            StoredRelationStrategy(
                target_table="target_table",
                target_field="target_no",
                source_table="source_table",
                source_field="source_no",
                strategy=FieldGenerationStrategy(
                    executor="local",
                    generator="copy_from_context",
                    params={"source_table": "source_table", "source_field": "source_no"},
                ),
                relation_reason="conflict relation",
                strategy_source="manual",
            )
        ]
        reusable_strategy_service = ReusableStrategyService(repository)
        service = DataGenerationService(
            planning_service=_RelationConflictPlanningService(),
            schema_repository=_RelationConflictSchemaRepository(),
            insert_render_service=InsertRenderService(),
            relation_strategy_alignment_service=RelationStrategyAlignmentService(reusable_strategy_service),
            relation_strategy_validation_service=RelationStrategyValidationService(reusable_strategy_service),
        )

        report = service.generate(
            requirement_text="relation strategy conflict",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
        )

        target_table = next(table for table in report.generated_tables if table.table_name == "target_table")
        self.assertEqual("TGT1", target_table.rows[0].values["target_no"])
        field_check = next(check for check in report.validation_checks if check.name == "relation_strategy:target_table.target_no<-source_table.source_no")
        self.assertFalse(field_check.passed)
        self.assertIn("target=['TGT1']", field_check.detail)
        self.assertIn("source=['SRC1']", field_check.detail)

    def test_generate_persists_scenario_relation_rules_before_alignment(self) -> None:
        class _ScenarioRulePlanningService:
            def build_draft(self, requirement_text: str, interfaces: list[InterfaceTarget], sample_limit: int = 3) -> PlanningDraft:
                return PlanningDraft(
                    requirement=RequirementSummary(summary="scenario rule persistence", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="scenario:1",
                            title="scenario relation",
                            api_name="demo",
                            api_path="/demo",
                            objective="persist relation rules",
                            tables=["source_table", "target_table"],
                            table_requirements={"source_table": "2 rows", "target_table": "2 rows"},
                            relation_rules=[
                                RelationRule(
                                    target_table="target_table",
                                    target_field="target_no",
                                    source_table="source_table",
                                    source_field="source_no",
                                    rationale="scenario relation",
                                )
                            ],
                        )
                    ],
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

        class _ScenarioRuleSchemaRepository:
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

        repository = _FakeReusableStrategyRepository()
        reusable_strategy_service = ReusableStrategyService(repository)
        service = DataGenerationService(
            planning_service=_ScenarioRulePlanningService(),
            schema_repository=_ScenarioRuleSchemaRepository(),
            insert_render_service=InsertRenderService(),
            relation_strategy_alignment_service=RelationStrategyAlignmentService(reusable_strategy_service),
            relation_strategy_validation_service=RelationStrategyValidationService(reusable_strategy_service),
            reusable_strategy_service=reusable_strategy_service,
        )

        report = service.generate(
            requirement_text="scenario relation persistence",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
        )

        target_table = next(table for table in report.generated_tables if table.table_name == "target_table")
        self.assertEqual("S1", target_table.rows[0].values["target_no"])
        self.assertEqual("S2", target_table.rows[1].values["target_no"])
        self.assertEqual(1, len(repository.relation_records))
        self.assertEqual("scenario_inferred", repository.relation_records[0].strategy_source)
        self.assertEqual("copy_from_context", repository.relation_records[0].strategy.generator)
        self.assertEqual("same_value", repository.relation_records[0].relation_type)
        self.assertEqual({}, repository.relation_records[0].evidence)

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
                            objective="fill AI-only fields",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 transaction row"},
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
                        TableColumn("cust_id", "varchar(18)", False, None, "customer id", False, False, 18),
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
            ) -> dict[str, AiTableGenerationAdvice]:
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
                return {
                    "demo_table": AiTableGenerationAdvice(
                        table_name="demo_table",
                        rows=[{"trans_amount": "88.50", "memo": "HELLOWORLD"}],
                        field_strategies={"trans_amount": "ai", "memo": "ai", "cust_id": "local"},
                    )
                }

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
        self.assertEqual("ai", report.scenarios[0].generation_source)
        self.assertEqual("ai", report.generated_tables[0].generation_source)
        self.assertEqual("ai", report.scenario_generations[0].generated_tables[0].generation_source)
        self.assertEqual("ai:cashflow:1", report.generated_tables[0].scenario_id)
        self.assertEqual("AI cashflow", report.scenario_generations[0].scenario_title)
        self.assertEqual(
            {"uuid": "local", "cust_id": "local", "trans_amount": "ai", "memo": "ai"},
            report.generated_tables[0].field_strategies,
        )
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
        self.assertIn("truncated string from 10 to 5 chars", validation_check.detail)
        self.assertEqual("962020122711000002", ai_analysis_service.calls[0]["sample_rows"][0]["cust_id"])
        self.assertEqual(
            {"demo_table": {"cust_id"}},
            ai_data_generation_service.calls[0]["local_generated_columns"],
        )
        self.assertEqual(
            ["cust_id=962020122711000002"],
            ai_data_generation_service.calls[0]["fixed_values"],
        )

    def test_generate_allows_ai_to_override_local_rule_field_when_ai_marks_it(self) -> None:
        class _AiOverridePlanningService:
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
                    requirement=RequirementSummary(summary="ai override local", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="ai:override:1",
                            title="AI override local",
                            api_name="multi_api",
                            api_path="",
                            objective="AI generates transactionkey",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 row"},
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
                                ColumnPlan("transactionkey", "sample", True, ["LOCAL_OLD"], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _AiOverrideSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("transactionkey", "varchar(64)", False, None, "transaction key", False, False, 64),
                        TableColumn("memo", "varchar(20)", True, None, "", False, False, 20),
                    ],
                    primary_keys=["uuid"],
                )

        class _AiOverrideSampleRepository:
            def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
                return [{"transactionkey": "LOCAL_SAMPLE", "memo": "legacy"}]

        class _AiOverrideDataGenerationService:
            def generate(
                self,
                scenario: ScenarioDraft,
                schemas: dict[str, TableSchema],
                sample_rows_by_table: dict[str, list[dict[str, str]]],
                local_generated_columns: dict[str, set[str]],
                analysis_by_table: dict[str, str],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, AiTableGenerationAdvice]:
                return {
                    "demo_table": AiTableGenerationAdvice(
                        table_name="demo_table",
                        rows=[{"transactionkey": "AI_TXN_001", "memo": "from-ai"}],
                        field_strategies={"transactionkey": "ai", "memo": "ai"},
                    )
                }

        service = DataGenerationService(
            planning_service=_AiOverridePlanningService(),
            schema_repository=_AiOverrideSchemaRepository(),
            insert_render_service=InsertRenderService(),
            sample_repository=_AiOverrideSampleRepository(),
            ai_data_generation_service=_AiOverrideDataGenerationService(),
        )

        report = service.generate(
            requirement_text="ai override local",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_data=True,
        )

        first_row = report.generated_tables[0].rows[0].values
        self.assertEqual("AI_TXN_001", first_row["transactionkey"])
        self.assertEqual("from-ai", first_row["memo"])
        self.assertEqual(
            {"uuid": "local", "transactionkey": "ai", "memo": "ai"},
            report.generated_tables[0].field_strategies,
        )

    def test_generate_caches_ai_analysis_across_scenarios(self) -> None:
        class _CachedPlanningService:
            def build_draft(
                self,
                requirement_text: str,
                interfaces: list[InterfaceTarget],
                sample_limit: int = 3,
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
                use_ai_scenarios: bool = False,
            ) -> PlanningDraft:
                scenario = lambda idx: ScenarioDraft(
                    id=f"ai:cache:{idx}",
                    title=f"cache-{idx}",
                    api_name="multi_api",
                    api_path="",
                    objective="cache AI samples",
                    tables=["demo_table"],
                    table_requirements={"demo_table": "generate 1 row"},
                    generation_source="ai",
                )
                return PlanningDraft(
                    requirement=RequirementSummary(summary="cache ai analysis", constraints=[], keywords=[]),
                    scenarios=[scenario(1), scenario(2)],
                    table_plans=[
                        TableDataPlan(
                            table_name="demo_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _CachedSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("memo", "varchar(20)", True, None, "", False, False, 20),
                    ],
                    primary_keys=["uuid"],
                )

        class _CachedSampleRepository:
            def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
                return [{"memo": "legacy"}]

        class _CachedAiAnalysisService:
            def __init__(self):
                self.calls: list[str] = []

            def analyze(
                self,
                table_name: str,
                schema: TableSchema,
                sample_rows: list[dict[str, str]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> str:
                self.calls.append(table_name)
                return '{"memo":"short text"}'

        class _CachedAiDataGenerationService:
            def generate(
                self,
                scenario: ScenarioDraft,
                schemas: dict[str, TableSchema],
                sample_rows_by_table: dict[str, list[dict[str, str]]],
                local_generated_columns: dict[str, set[str]],
                analysis_by_table: dict[str, str],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, AiTableGenerationAdvice]:
                return {
                    "demo_table": AiTableGenerationAdvice(
                        table_name="demo_table",
                        rows=[{"memo": scenario.title}],
                        field_strategies={"memo": "ai"},
                    )
                }

        ai_analysis_service = _CachedAiAnalysisService()
        service = DataGenerationService(
            planning_service=_CachedPlanningService(),
            schema_repository=_CachedSchemaRepository(),
            insert_render_service=InsertRenderService(),
            sample_repository=_CachedSampleRepository(),
            ai_data_analysis_service=ai_analysis_service,
            ai_data_generation_service=_CachedAiDataGenerationService(),
        )

        report = service.generate(
            requirement_text="cache ai analysis",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_data=True,
        )

        self.assertEqual(1, len(ai_analysis_service.calls))
        self.assertEqual(2, len(report.generated_tables))

    def test_generate_uses_one_time_ai_field_decisions_and_keeps_local_rows(self) -> None:
        class _DecisionPlanningService:
            def build_draft(
                self,
                requirement_text: str,
                interfaces: list[InterfaceTarget],
                sample_limit: int = 3,
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
                use_ai_scenarios: bool = False,
            ) -> PlanningDraft:
                scenario = lambda idx: ScenarioDraft(
                    id=f"ai:decision:{idx}",
                    title=f"decision-{idx}",
                    api_name="multi_api",
                    api_path="",
                    objective="only decide field strategies",
                    tables=["demo_table"],
                    table_requirements={"demo_table": "generate 1 row"},
                    generation_source="ai",
                )
                return PlanningDraft(
                    requirement=RequirementSummary(summary="field decisions only", constraints=[], keywords=[]),
                    scenarios=[scenario(1), scenario(2)],
                    table_plans=[
                        TableDataPlan(
                            table_name="demo_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("transactionkey", "sample", True, ["LOCAL_TXN"], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _DecisionSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("transactionkey", "varchar(64)", False, None, "transaction key", False, False, 64),
                        TableColumn("memo", "varchar(20)", True, None, "memo", False, False, 20),
                    ],
                    primary_keys=["uuid"],
                )

        class _DecisionSampleRepository:
            def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
                return [{"transactionkey": "LOCAL_SAMPLE", "memo": "legacy"}]

        class _DecisionAiAnalysisService:
            def __init__(self):
                self.calls: list[str] = []

            def analyze(
                self,
                table_name: str,
                schema: TableSchema,
                sample_rows: list[dict[str, str]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> str:
                self.calls.append(table_name)
                return '{"memo":"text"}'

        class _DecisionAiDataService:
            def __init__(self):
                self.calls: list[dict[str, object]] = []

            def decide_table_field_strategies(
                self,
                requirement_text: str,
                table_name: str,
                schema: TableSchema,
                scenario_summaries: list[str],
                local_generated_columns: set[str],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
                prior_advice: AiTableGenerationAdvice | None = None,
            ) -> AiTableGenerationAdvice:
                self.calls.append(
                    {
                        "requirement_text": requirement_text,
                        "table_name": table_name,
                        "scenario_summaries": scenario_summaries,
                        "local_generated_columns": local_generated_columns,
                        "prior_advice": prior_advice,
                    }
                )
                return AiTableGenerationAdvice(
                    table_name=table_name,
                    rows=[],
                    field_strategies={"memo": "ai", "transactionkey": "local"},
                    field_generation_strategies={
                        "memo": FieldGenerationStrategy(
                            executor="ai",
                            generator="ai_value",
                            fallback_generators=["sample_cycle"],
                            implementation_hint="add a short-summary generator later",

                        ),
                        "transactionkey": FieldGenerationStrategy(
                            executor="local",
                            generator="transaction_key",
                            fallback_generators=["sample_cycle"],
                        ),
                    },
                )

        ai_analysis_service = _DecisionAiAnalysisService()
        ai_data_service = _DecisionAiDataService()
        service = DataGenerationService(
            planning_service=_DecisionPlanningService(),
            schema_repository=_DecisionSchemaRepository(),
            insert_render_service=InsertRenderService(),
            sample_repository=_DecisionSampleRepository(),
            ai_data_analysis_service=ai_analysis_service,
            ai_data_generation_service=ai_data_service,
        )

        report = service.generate(
            requirement_text="field decisions only",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
            use_ai_scenarios=True,
        )

        self.assertEqual(2, len(ai_data_service.calls))
        self.assertIsNone(ai_data_service.calls[0]["prior_advice"])
        self.assertIsInstance(ai_data_service.calls[1]["prior_advice"], AiTableGenerationAdvice)
        self.assertEqual(0, len(ai_analysis_service.calls))
        self.assertEqual("hybrid", report.generated_tables[0].generation_source)
        self.assertEqual(
            {"uuid": "local", "transactionkey": "local", "memo": "ai"},
            report.generated_tables[0].field_strategies,
        )
        self.assertEqual(
            "ai_value",
            report.generated_tables[0].field_generation_strategies["memo"].generator,
        )
        self.assertEqual(
            "add a short-summary generator later",

            report.generated_tables[0].field_generation_strategies["memo"].implementation_hint,
        )
        self.assertEqual(
            "transaction_key",
            report.generated_tables[0].field_generation_strategies["transactionkey"].generator,
        )
        first_row = report.generated_tables[0].rows[0].values
        self.assertIsNotNone(first_row["transactionkey"])
        self.assertNotEqual("AI_TXN_001", first_row["transactionkey"])
        self.assertIsNone(first_row["memo"])
        self.assertEqual(2, len(report.generated_tables))

    def test_generate_skips_placeholder_fixed_values_and_uses_local_fallbacks(self) -> None:
        class _PlaceholderPlanningService:
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
                    requirement=RequirementSummary(summary="placeholder strategies", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="ai:placeholder:1",
                            title="placeholder",
                            api_name="multi_api",
                            api_path="",
                            objective="support batch field decisions",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 row"},
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
                                ColumnPlan("trans_time", "sample", False, ["2020-11-26 09:48:54"], ""),
                                ColumnPlan("trans_amount", "sample", False, ["129876.4000"], ""),
                            ],
                        )
                    ],
                )

        class _PlaceholderSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("trans_time", "varchar(32)", True, None, "", False, False, 32),
                        TableColumn("trans_amount", "varchar(32)", True, None, "", False, False, 32),
                    ],
                    primary_keys=["uuid"],
                )

        class _PlaceholderSampleRepository:
            def sample_rows(self, table_name: str, limit: int) -> list[dict[str, str]]:
                return [{"trans_time": "2020-11-26 09:48:54", "trans_amount": "129876.4000"}]

        class _PlaceholderAiDataService:
            def decide_table_field_strategies(
                self,
                requirement_text: str,
                table_name: str,
                schema: TableSchema,
                scenario_summaries: list[str],
                local_generated_columns: set[str],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
                prior_advice: AiTableGenerationAdvice | None = None,
            ) -> AiTableGenerationAdvice:
                return AiTableGenerationAdvice(
                    table_name=table_name,
                    field_strategies={"trans_time": "local", "trans_amount": "local"},
                    field_generation_strategies={
                        "trans_time": FieldGenerationStrategy(
                            executor="local",
                            generator="fixed_value",
                            params={"value": "2020-12-20 generate different timestamp"},
                            fallback_generators=["sample_cycle"],
                        ),
                        "trans_amount": FieldGenerationStrategy(
                            executor="local",
                            generator="fixed_value",
                            params={"value": "amount placeholder"},

                            fallback_generators=["sample_cycle"],
                        ),
                    },
                )

        service = DataGenerationService(
            planning_service=_PlaceholderPlanningService(),
            schema_repository=_PlaceholderSchemaRepository(),
            insert_render_service=InsertRenderService(),
            sample_repository=_PlaceholderSampleRepository(),
            ai_data_generation_service=_PlaceholderAiDataService(),
        )

        report = service.generate(
            requirement_text="placeholder strategies",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
            use_ai_scenarios=True,
        )

        first_row = report.generated_tables[0].rows[0].values
        self.assertEqual("2020-12-20 09:00:00", first_row["trans_time"])
        self.assertEqual("129876.4000", first_row["trans_amount"])

    def test_generate_reuses_imported_field_decisions_without_calling_ai(self) -> None:
        class _ImportedDecisionPlanningService:
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
                    requirement=RequirementSummary(summary="imported strategies", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="scenario-imported",
                            title="imported",
                            api_name="demo",
                            api_path="/demo",
                            objective="reuse imported strategy file",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 row"},
                            generation_source="ai" if use_ai_scenarios else "local",
                        )
                    ],
                    table_plans=[
                        TableDataPlan(
                            table_name="demo_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("trans_time", "sample", False, ["2020-11-26 09:48:54"], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _ImportedDecisionSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("trans_time", "varchar(32)", True, None, "", False, False, 32),
                        TableColumn("memo", "varchar(64)", True, None, "", False, False, 64),
                    ],
                    primary_keys=["uuid"],
                )

        class _ForbiddenAiDataService:
            def decide_table_field_strategies(self, *args, **kwargs):
                raise AssertionError("AI field decision should not be called when imported strategies are provided.")

        service = DataGenerationService(
            planning_service=_ImportedDecisionPlanningService(),
            schema_repository=_ImportedDecisionSchemaRepository(),
            insert_render_service=InsertRenderService(),
            ai_data_generation_service=_ForbiddenAiDataService(),
        )

        report = service.generate(
            requirement_text="imported strategies",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_scenarios=True,
            use_ai_field_decisions=True,
            imported_field_decisions={
                "demo_table": AiTableGenerationAdvice(
                    table_name="demo_table",
                    field_strategies={"trans_time": "ai", "memo": "local"},
                    field_generation_strategies={
                        "trans_time": FieldGenerationStrategy(
                            executor="local",
                            generator="fixed_value",
                            params={"value": "2020-12-20 generate different timestamp"},
                            fallback_generators=["sample_cycle"],
                        ),
                        "memo": FieldGenerationStrategy(
                            executor="local",
                            generator="fixed_value",
                            params={"value": "imported memo value"},
                        ),
                    },
                )
            },
        )

        self.assertEqual(1, len(report.generated_tables))
        generated_table = report.generated_tables[0]
        self.assertEqual("hybrid", generated_table.generation_source)
        self.assertEqual("fixed_value", generated_table.field_generation_strategies["trans_time"].generator)
        self.assertEqual("fixed_value", generated_table.field_generation_strategies["memo"].generator)
        first_row = generated_table.rows[0].values
        self.assertEqual("2020-12-20 09:00:00", first_row["trans_time"])
        self.assertEqual("imported memo value", first_row["memo"])

    def test_generate_reuses_db_backed_generic_field_strategies_without_ai_service(self) -> None:
        class _ReusableFieldPlanningService:
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
                    requirement=RequirementSummary(summary="reusable field decisions", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="reusable-field-1",
                            title="reusable field",
                            api_name="demo",
                            api_path="/demo",
                            objective="reuse generic field strategy",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 row"},
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
                                ColumnPlan("result_key", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _ReusableFieldSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("result_key", "varchar(128)", True, None, "", False, False, 128),
                    ],
                    primary_keys=["uuid"],
                )

        class _CountingAiFieldDecisionService:
            def __init__(self):
                self.calls = 0

            def decide_tables_field_strategies(
                self,
                requirement_text: str,
                table_requests: list[dict[str, object]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, AiTableGenerationAdvice]:
                self.calls += 1
                return {
                    "demo_table": AiTableGenerationAdvice(
                        table_name="demo_table",
                        field_strategies={"result_key": "local"},
                        field_generation_strategies={
                            "result_key": FieldGenerationStrategy(
                                executor="local",
                                generator="concat_template",
                                params={"template": "{uuid}-R"},
                            )
                        },
                    )
                }

        reusable_strategy_service = ReusableStrategyService(_FakeReusableStrategyRepository())
        ai_data_service = _CountingAiFieldDecisionService()
        service = DataGenerationService(
            planning_service=_ReusableFieldPlanningService(),
            schema_repository=_ReusableFieldSchemaRepository(),
            insert_render_service=InsertRenderService(),
            ai_data_generation_service=ai_data_service,
            reusable_strategy_service=reusable_strategy_service,
        )

        first_report = service.generate(
            requirement_text="reusable field decisions",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
        )

        cached_service = DataGenerationService(
            planning_service=_ReusableFieldPlanningService(),
            schema_repository=_ReusableFieldSchemaRepository(),
            insert_render_service=InsertRenderService(),
            ai_data_generation_service=None,
            reusable_strategy_service=reusable_strategy_service,
        )

        second_report = cached_service.generate(
            requirement_text="reusable field decisions",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
        )

        self.assertEqual(1, ai_data_service.calls)
        self.assertEqual("DEMOTABL_001-R", first_report.generated_tables[0].rows[0].values["result_key"])
        self.assertEqual("DEMOTABL_001-R", second_report.generated_tables[0].rows[0].values["result_key"])

    def test_generate_decides_field_strategies_in_scenario_order_with_prior_hints(self) -> None:
        class _SequentialPlanningService:
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
                    requirement=RequirementSummary(summary="sequential field decisions", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="scenario-1",
                            title="baseline",
                            api_name="demo",
                            api_path="/demo",
                            objective="fallback to local defaults",
                            tables=["demo_table"],
                            table_requirements={"demo_table": "default local row"},

                            generation_source="ai",
                        ),
                        ScenarioDraft(
                            id="scenario-2",
                            title="boundary-date",
                            api_name="demo",
                            api_path="/demo",
                            objective="change only the date boundary",

                            tables=["demo_table"],
                            table_requirements={"demo_table": "local fallback row"},
                            generation_source="ai",
                        ),
                    ],
                    table_plans=[
                        TableDataPlan(
                            table_name="demo_table",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _SequentialSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("memo", "varchar(64)", True, None, "", False, False, 64),
                    ],
                    primary_keys=["uuid"],
                )

        class _SequentialAiDataService:
            def __init__(self):
                self.calls: list[list[dict[str, object]]] = []

            def decide_tables_field_strategies(
                self,
                requirement_text: str,
                table_requests: list[dict[str, object]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, AiTableGenerationAdvice]:
                self.calls.append(table_requests)
                if len(self.calls) == 1:
                    return {
                        "demo_table": AiTableGenerationAdvice(
                            table_name="demo_table",
                            field_strategies={"memo": "local"},
                            field_generation_strategies={
                                "memo": FieldGenerationStrategy(
                                    executor="local",
                                    generator="fixed_value",
                                    params={"value": "baseline-memo"},
                                )
                            },
                        )
                    }
                return {}

        ai_data_service = _SequentialAiDataService()
        service = DataGenerationService(
            planning_service=_SequentialPlanningService(),
            schema_repository=_SequentialSchemaRepository(),
            insert_render_service=InsertRenderService(),
            ai_data_generation_service=ai_data_service,
        )

        report = service.generate(
            requirement_text="sequential field decisions",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
            use_ai_scenarios=True,
        )

        self.assertEqual(2, len(ai_data_service.calls))
        self.assertIsNone(ai_data_service.calls[0][0]["prior_advice"])
        self.assertIsInstance(ai_data_service.calls[1][0]["prior_advice"], AiTableGenerationAdvice)
        self.assertEqual(
            "fixed_value",
            ai_data_service.calls[1][0]["prior_advice"].field_generation_strategies["memo"].generator,
        )
        self.assertEqual("baseline-memo", report.generated_tables[0].rows[0].values["memo"])
        self.assertEqual("baseline-memo", report.generated_tables[1].rows[0].values["memo"])

    def test_generate_falls_back_to_local_defaults_when_ai_and_reusable_strategies_are_missing(self) -> None:
        class _FallbackPlanningService:
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
                    requirement=RequirementSummary(summary="fallback local defaults", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="fallback-1",
                            title="fallback",
                            api_name="demo",
                            api_path="/demo",
                            objective="fall back to local defaults when AI strategies are missing",

                            tables=["demo_table"],
                            table_requirements={"demo_table": "generate 1 row"},
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
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        )
                    ],
                )

        class _FallbackSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("memo", "varchar(64)", True, None, "", False, False, 64),
                    ],
                    primary_keys=["uuid"],
                )

        service = DataGenerationService(
            planning_service=_FallbackPlanningService(),
            schema_repository=_FallbackSchemaRepository(),
            insert_render_service=InsertRenderService(),
            reusable_strategy_service=ReusableStrategyService(_FakeReusableStrategyRepository()),
        )

        report = service.generate(
            requirement_text="fallback local defaults",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
        )

        self.assertEqual(1, len(report.generated_tables))
        self.assertIsNone(report.generated_tables[0].rows[0].values["memo"])

    def test_generate_supports_contextual_local_generators_across_field_order_and_tables(self) -> None:
        class _ContextPlanningService:
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
                    requirement=RequirementSummary(summary="context generators", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="scenario-context",
                            title="context",
                            api_name="demo",
                            api_path="/demo",
                            objective="reuse context values across fields and tables",

                            tables=["table_a", "table_b"],
                            table_requirements={"table_a": "generate 2 rows", "table_b": "reuse upstream draft no"},
                            generation_source="ai" if use_ai_scenarios else "local",
                        )
                    ],
                    table_plans=[
                        TableDataPlan(
                            table_name="table_a",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("result_key", "optional", False, [], ""),
                                ColumnPlan("ds", "optional", False, [], ""),
                                ColumnPlan("model_key", "condition", True, ["WSTY001"], ""),
                                ColumnPlan("result_date", "condition", True, ["2020-12-27"], ""),
                                ColumnPlan("cust_id", "condition", True, ["962020122711000002"], ""),
                                ColumnPlan("alert_date", "condition", True, ["2020-12-20"], ""),
                                ColumnPlan("drft_no", "sample", True, ["DRFT-001", "DRFT-002"], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="table_b",
                            primary_keys=["uuid"],
                            row_hint=2,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("drft_no", "optional", False, [], ""),
                            ],
                        ),
                    ],
                )

        class _ContextSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                if table_name == "table_a":
                    return TableSchema(
                        table_name=table_name,
                        table_type="innodb",
                        columns=[
                            TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                            TableColumn("result_key", "varchar(128)", False, None, "", False, False, 128),
                            TableColumn("ds", "varchar(8)", False, None, "", False, False, 8),
                            TableColumn("model_key", "varchar(16)", False, None, "", False, False, 16),
                            TableColumn("result_date", "varchar(16)", False, None, "", False, False, 16),
                            TableColumn("cust_id", "varchar(32)", False, None, "", False, False, 32),
                            TableColumn("alert_date", "varchar(16)", False, None, "", False, False, 16),
                            TableColumn("drft_no", "varchar(32)", False, None, "", False, False, 32),
                        ],
                        primary_keys=["uuid"],
                    )
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
            planning_service=_ContextPlanningService(),
            schema_repository=_ContextSchemaRepository(),
            insert_render_service=InsertRenderService(),
        )

        report = service.generate(
            requirement_text="context generators",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=2,
            use_ai_scenarios=True,
            use_ai_field_decisions=True,
            imported_field_decisions={
                "table_a": AiTableGenerationAdvice(
                    table_name="table_a",
                    field_generation_strategies={
                        "result_key": FieldGenerationStrategy(
                            executor="local",
                            generator="concat_template",
                            params={
                                "template": "{model_key}{result_date}{cust_id}",
                                "transforms": {"result_date": "date:%Y%m%d"},
                            },
                        ),
                        "ds": FieldGenerationStrategy(
                            executor="local",
                            generator="date_format_from_field",
                            params={"source_field": "alert_date", "output_format": "%Y%m%d"},
                        ),
                    },
                ),
                "table_b": AiTableGenerationAdvice(
                    table_name="table_b",
                    field_generation_strategies={
                        "drft_no": FieldGenerationStrategy(
                            executor="local",
                            generator="copy_from_context",
                            params={"source_field": "drft_no"},
                        )
                    },
                ),
            },
        )

        table_a = next(table for table in report.generated_tables if table.table_name == "table_a")
        table_b = next(table for table in report.generated_tables if table.table_name == "table_b")
        self.assertEqual("WSTY00120201227962020122711000002", table_a.rows[0].values["result_key"])
        self.assertEqual("20201220", table_a.rows[0].values["ds"])
        self.assertEqual("DRFT-001", table_b.rows[0].values["drft_no"])
        self.assertEqual("DRFT-002", table_b.rows[1].values["drft_no"])

    def test_generate_prefers_batch_ai_field_decisions_when_available(self) -> None:
        class _BatchDecisionPlanningService:
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
                    requirement=RequirementSummary(summary="batch decisions", constraints=[], keywords=[]),
                    scenarios=[
                        ScenarioDraft(
                            id="ai:batch:1",
                            title="batch-1",
                            api_name="multi_api",
                            api_path="",
                            objective="batch field decisions",
                            tables=["table_a", "table_b"],
                            table_requirements={"table_a": "generate 1 row", "table_b": "generate 1 row"},
                            generation_source="ai",
                        )
                    ],
                    table_plans=[
                        TableDataPlan(
                            table_name="table_a",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("memo", "optional", False, [], ""),
                            ],
                        ),
                        TableDataPlan(
                            table_name="table_b",
                            primary_keys=["uuid"],
                            row_hint=1,
                            column_plans=[
                                ColumnPlan("uuid", "generated", True, [], ""),
                                ColumnPlan("seq_no", "optional", False, [], ""),
                            ],
                        ),
                    ],
                )

        class _BatchDecisionSchemaRepository:
            def get_table_schema(self, table_name: str) -> TableSchema:
                if table_name == "table_a":
                    return TableSchema(
                        table_name=table_name,
                        table_type="innodb",
                        columns=[
                            TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                            TableColumn("memo", "varchar(32)", True, None, "", False, False, 32),
                        ],
                        primary_keys=["uuid"],
                    )
                return TableSchema(
                    table_name=table_name,
                    table_type="innodb",
                    columns=[
                        TableColumn("uuid", "varchar(64)", False, None, "", True, False, 64),
                        TableColumn("seq_no", "varchar(8)", True, None, "historical sequence", False, False, 8),
                    ],
                    primary_keys=["uuid"],
                )

        class _BatchDecisionAiDataService:
            def __init__(self):
                self.batch_calls: list[dict[str, object]] = []

            def decide_tables_field_strategies(
                self,
                requirement_text: str,
                table_requests: list[dict[str, object]],
                fixed_values: list[str] | None = None,
                dependent_fixed_values: list[str] | None = None,
            ) -> dict[str, AiTableGenerationAdvice]:
                self.batch_calls.append(
                    {
                        "requirement_text": requirement_text,
                        "table_requests": table_requests,
                        "fixed_values": fixed_values,
                        "dependent_fixed_values": dependent_fixed_values,
                    }
                )
                return {
                    "table_a": AiTableGenerationAdvice(
                        table_name="table_a",
                        field_generation_strategies={
                            "memo": FieldGenerationStrategy(
                                executor="local",
                                generator="fixed_value",
                                params={"value": "from-batch"},
                            )
                        },
                    ),
                    "table_b": AiTableGenerationAdvice(
                        table_name="table_b",
                        field_generation_strategies={
                            "seq_no": FieldGenerationStrategy(
                                executor="local",
                                generator="sequence_cycle",
                                params={"values": ["08", "07"]},
                            )
                        },
                    ),
                }

        ai_data_service = _BatchDecisionAiDataService()
        service = DataGenerationService(
            planning_service=_BatchDecisionPlanningService(),
            schema_repository=_BatchDecisionSchemaRepository(),
            insert_render_service=InsertRenderService(),
            ai_data_generation_service=ai_data_service,
        )

        report = service.generate(
            requirement_text="batch decisions",
            interfaces=[InterfaceTarget(name="demo", path="/demo")],
            sample_limit=1,
            use_ai_field_decisions=True,
            use_ai_scenarios=True,
        )

        self.assertEqual(1, len(ai_data_service.batch_calls))
        generated = {(table.table_name, next(iter(table.rows)).values.get("memo") or next(iter(table.rows)).values.get("seq_no")) for table in report.generated_tables}
        self.assertIn(("table_a", "from-batch"), generated)
        self.assertIn(("table_b", "08"), generated)


if __name__ == "__main__":
    unittest.main()

