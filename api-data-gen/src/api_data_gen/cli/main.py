from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path

from api_data_gen.config import load_settings
from api_data_gen.domain.models import InterfaceTarget
from api_data_gen.infra.db.field_match_repository import FieldMatchRepository
from api_data_gen.services.data_generation_service import DataGenerationService
from api_data_gen.services.ai_chat_client import AiChatClient
from api_data_gen.services.ai_cache_service import AiCacheService
from api_data_gen.services.ai_data_analysis_service import AiDataAnalysisService
from api_data_gen.services.ai_data_generation_service import AiDataGenerationService
from api_data_gen.services.ai_scenario_service import AiScenarioService
from api_data_gen.infra.db.dict_repository import DictRepository
from api_data_gen.infra.db.mysql_client import MysqlClient
from api_data_gen.infra.db.reusable_strategy_repository import ReusableStrategyRepository
from api_data_gen.infra.db.sample_repository import SampleRepository
from api_data_gen.infra.db.schema_repository import SchemaRepository
from api_data_gen.infra.db.trace_repository import TraceRepository
from api_data_gen.services.dict_rule_resolver import DictRuleResolver
from api_data_gen.services.field_match_discovery_service import FieldMatchDiscoveryService
from api_data_gen.services.interface_trace_service import InterfaceTraceService
from api_data_gen.services.insert_render_service import InsertRenderService
from api_data_gen.services.field_match_alignment_service import FieldMatchAlignmentService
from api_data_gen.services.field_match_validation_service import FieldMatchValidationService
from api_data_gen.services.local_field_rule_service import LocalFieldRuleService
from api_data_gen.services.phase1_validation_service import Phase1ValidationService
from api_data_gen.services.planning_service import PlanningService
from api_data_gen.services.record_validation_service import RecordValidationService
from api_data_gen.services.requirement_parser import RequirementParser
from api_data_gen.services.reusable_strategy_service import ReusableStrategyService
from api_data_gen.services.schema_service import SchemaService
from api_data_gen.services.sql_apply_service import SqlApplyService
from api_data_gen.services.sql_script_export_service import SqlScriptExportService
from api_data_gen.services.sql_parser import SqlParser

DEFAULT_CUMULATIVE_SQL_PATH = Path("output/insert_20260303_235409_agent_auto.sql")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local helpers for API trace analysis, planning, and data generation")
    parser.add_argument("--env-file", default=None, help="Optional .env file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    interface_parser = subparsers.add_parser("interface", help="Extract SQL/table info from interface traces")
    interface_parser.add_argument("--api-path", required=True)
    interface_parser.add_argument("--api-name", required=True)

    schema_parser = subparsers.add_parser("schema", help="Read table schema")
    schema_parser.add_argument("--table", required=True)

    sample_parser = subparsers.add_parser("sample", help="Sample rows from a table")
    sample_parser.add_argument("--table", required=True)
    sample_parser.add_argument("--limit", type=int, default=3)

    dict_parser = subparsers.add_parser("dict", help="Resolve dictionary code values")
    dict_parser.add_argument("--column", required=True)
    dict_parser.add_argument("--comment", default="")

    validate_parser = subparsers.add_parser("validate", help="Run Phase 1 compatibility checks")
    validate_parser.add_argument("--sample-limit", type=int, default=2)

    draft_parser = subparsers.add_parser("draft", help="Build Phase 2 scenario and data drafts")
    draft_parser.add_argument("--requirement-file", required=True)
    draft_parser.add_argument("--api", action="append", required=True, help="Interface mapping in the form name=path")
    draft_parser.add_argument("--sample-limit", type=int, default=3)
    draft_parser.add_argument("--strategy-mode", choices=["agent", "local", "direct", "agent_auto"], default="agent")
    draft_parser.add_argument("--fixed-value", action="append", default=[], help="Fixed field hint, e.g. cust_id='9620...'")
    draft_parser.add_argument("--depend-fixed-value", action="append", default=[], help="Dependent fixed-value hint, free-form text")
    draft_parser.add_argument("--use-ai-scenarios", action="store_true", help="Generate scenarios with the configured AI model")
    draft_parser.add_argument("--max-agent-turns", type=int, default=10, help="Max agent turns for agent_auto mode")

    generate_parser = subparsers.add_parser("generate", help="Build Phase 3 local rows and insert SQL")
    generate_parser.add_argument("--requirement-file", required=True)
    generate_parser.add_argument("--api", action="append", required=True, help="Interface mapping in the form name=path")
    generate_parser.add_argument("--sample-limit", type=int, default=3)
    generate_parser.add_argument("--strategy-mode", choices=["agent", "local", "direct", "agent_auto"], default="agent")
    generate_parser.add_argument("--generation-tag", default=None, help="Optional batch tag for generated primary keys and local generated values")
    generate_parser.add_argument("--fixed-value", action="append", default=[], help="Fixed field hint, e.g. cust_id='9620...'")
    generate_parser.add_argument("--depend-fixed-value", action="append", default=[], help="Dependent fixed-value hint, free-form text")
    generate_parser.add_argument("--use-ai-scenarios", action="store_true", help="Generate scenarios with the configured AI model")
    generate_parser.add_argument("--use-ai-data", action="store_true", help="Let the configured AI model fill non-local fields per scenario")
    generate_parser.add_argument("--strategy-file", default=None, help="Optional strategy_*.json file to reuse field generation strategies locally")
    generate_parser.add_argument("--sql-output-file", default=None, help="Optional path to write a combined SQL script")
    generate_parser.add_argument("--apply-sql", action="store_true", help="Apply generated inserts to the configured MySQL schemas")
    generate_parser.add_argument("--force-apply", action="store_true", help="Apply SQL even when validation checks fail")
    generate_parser.add_argument("--max-agent-turns", type=int, default=10, help="Max agent turns for agent_auto mode")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = load_settings(args.env_file)
    client = MysqlClient(settings)
    trace_repository = TraceRepository(client, settings)
    schema_repository = SchemaRepository(client)
    dict_repository = DictRepository(client, settings)
    field_match_repository = FieldMatchRepository(client, settings)
    field_match_discovery_service = FieldMatchDiscoveryService(
        schema_repository=schema_repository,
        field_match_repository=field_match_repository,
        candidate_schema_names=[settings.business_schema],
    )
    sample_repository = SampleRepository(
        client,
        settings.trace_schema,
        schema_repository,
        field_match_discovery_service=field_match_discovery_service,
    )
    schema_service = SchemaService(schema_repository)
    dict_rule_resolver = DictRuleResolver(dict_repository)
    local_field_rule_service = LocalFieldRuleService(dict_rule_resolver)
    requirement_parser = RequirementParser()
    ai_chat_client = AiChatClient(settings)
    ai_cache_service = AiCacheService()
    reusable_strategy_repository = ReusableStrategyRepository(client, settings)
    reusable_strategy_service = ReusableStrategyService(reusable_strategy_repository)
    optional_ai_scenario_service = _build_optional_ai_scenario_service(ai_chat_client)
    optional_ai_analysis_service = _build_optional_ai_analysis_service(ai_chat_client)
    optional_ai_data_service = _build_optional_ai_data_service(ai_chat_client)

    if args.command == "interface":
        service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        result = service.get_table_info(args.api_name, args.api_path)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "schema":
        result = schema_repository.get_table_schema(args.table)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "sample":
        result = sample_repository.sample_rows(args.table, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "dict":
        result = dict_rule_resolver.resolve_code_values(args.column, args.comment)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "validate":
        interface_service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        validation_service = Phase1ValidationService(
            interface_service,
            schema_repository,
            sample_repository,
            dict_rule_resolver,
        )
        result = validation_service.validate(args.sample_limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "draft":
        print(f"[1/3] 寮€濮嬫墽琛屽満鏅鍒掍换鍔?..")
        print(f"       绛栫暐妯″紡: {args.strategy_mode}")
        print(f"       闇€姹傛枃浠? {args.requirement_file}")
        print(f"       鎺ュ彛: {args.api}")

        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
        print(f"[2/3] 姝ｅ湪鍒濆鍖栨湇鍔＄粍浠?..")

        interface_service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        planning_service = PlanningService(
            settings=settings,
            trace_repository=trace_repository,
            interface_trace_service=interface_service,
            schema_service=schema_service,
            sample_repository=sample_repository,
            dict_rule_resolver=dict_rule_resolver,
            requirement_parser=requirement_parser,
            ai_scenario_service=optional_ai_scenario_service,
            ai_cache_service=ai_cache_service,
        )
        interfaces = [_parse_interface_target(raw_value) for raw_value in args.api]

        if args.strategy_mode == "agent_auto":
            print(f"[3/3] 鎵ц agent_auto 妯″紡 (寮哄埗 AI 鐢熸垚鍦烘櫙)...")
            print(f"       姝ｅ湪浣跨敤澶у瀷鐢熸垚娴嬭瘯鍦烘櫙...")
            result = planning_service.build_draft(
                requirement_text,
                interfaces,
                args.sample_limit,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=True,
            )
            _assert_ai_scenarios(result.scenarios, "agent_auto draft")
        elif args.strategy_mode == "agent":
            from api_data_gen.agents.orchestrator_service import AgentOrchestratorService

            print(f"[3/3] 鎵ц agent 妯″紡 (鐢熸垚鎻愮ず璇嶅寘)...")
            agent_orchestrator = AgentOrchestratorService(
                planning_service=planning_service,
                interface_trace_service=interface_service,
                schema_service=schema_service,
                sample_repository=sample_repository,
                local_field_rule_service=local_field_rule_service,
            )
            result = agent_orchestrator.build_draft(
                requirement_text,
                interfaces,
                args.sample_limit,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
            )
        else:
            use_ai_scenarios = args.strategy_mode == "direct" and args.use_ai_scenarios
            if use_ai_scenarios:
                print(f"[3/3] 鎵ц {args.strategy_mode} 妯″紡 (AI鐢熸垚鍦烘櫙)...")
                _require_ai_config(ai_chat_client)
            else:
                print(f"[3/3] 鎵ц {args.strategy_mode} 妯″紡 (绾湰鍦拌鍒?...")
            result = planning_service.build_draft(
                requirement_text,
                interfaces,
                args.sample_limit,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=use_ai_scenarios,
            )

        print(f"       鍦烘櫙瑙勫垝瀹屾垚锛屾鍦ㄤ繚瀛樼粨鏋?..")

        # 鑷姩杈撳嚭鍒?output 鏂囦欢澶?
        _auto_save_output(result, args.strategy_mode, None, client)
        print(f"\n=== 浠诲姟瀹屾垚 ===")
        if hasattr(result, 'scenarios') and result.scenarios:
            print(f"       鐢熸垚鍦烘櫙鏁? {len(result.scenarios)}")
        if hasattr(result, 'table_plans') and result.table_plans:
            print(f"       鐢熸垚琛ㄨ鍒掓暟: {len(result.table_plans)}")

        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "generate":
        print(f"[1/4] 寮€濮嬫墽琛屾暟鎹敓鎴愪换鍔?..")
        print(f"       绛栫暐妯″紡: {args.strategy_mode}")
        print(f"       闇€姹傛枃浠? {args.requirement_file}")
        print(f"       鎺ュ彛: {args.api}")

        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
        print(f"[2/4] 姝ｅ湪鍒濆鍖栨湇鍔＄粍浠?..")

        interface_service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        planning_service = PlanningService(
            settings=settings,
            trace_repository=trace_repository,
            interface_trace_service=interface_service,
            schema_service=schema_service,
            sample_repository=sample_repository,
            dict_rule_resolver=dict_rule_resolver,
            requirement_parser=requirement_parser,
            ai_scenario_service=optional_ai_scenario_service,
            ai_cache_service=ai_cache_service,
        )
        generation_service = DataGenerationService(
            planning_service=planning_service,
            schema_repository=schema_repository,
            insert_render_service=InsertRenderService(),
            sample_repository=sample_repository,
            field_match_alignment_service=FieldMatchAlignmentService(field_match_repository),
            field_match_validation_service=FieldMatchValidationService(field_match_repository),
            local_field_rule_service=local_field_rule_service,
            record_validation_service=RecordValidationService(),
            ai_data_analysis_service=optional_ai_analysis_service,
            ai_data_generation_service=optional_ai_data_service,
            ai_cache_service=ai_cache_service,
            reusable_strategy_service=reusable_strategy_service,
            field_match_repository=field_match_repository,
        )
        interfaces = [_parse_interface_target(raw_value) for raw_value in args.api]
        generation_tag = args.generation_tag
        if generation_tag is None and args.apply_sql:
            generation_tag = _build_generation_tag()
        imported_field_decisions = {}
        if args.strategy_file:
            from api_data_gen.services.strategy_export_service import StrategyExportService

            strategy_export_service = StrategyExportService()
            imported_field_decisions = strategy_export_service.load_field_decisions(args.strategy_file)
            print(f"       复用策略文件: {args.strategy_file}")

        if args.strategy_mode == "agent_auto":
            if args.strategy_file:
                print(f"[3/4] 鎵ц agent_auto 妯″紡 (AI 鐢熸垚鍦烘櫙 + 复用策略文件 + 鏈湴鐢熸垚鏁版嵁)...")
            else:
                print(f"[3/4] 鎵ц agent_auto 妯″紡 (AI 鐢熸垚鍦烘櫙 + AI 琛ㄧ骇瀛楁鍐崇瓥 + 鏈湴鐢熸垚鏁版嵁)...")
            if args.strategy_file:
                print(f"       姝ｅ湪浣跨敤 AI 鐢熸垚鍦烘櫙锛屽瓧娈垫潵婧愮瓥鐣ュ皢鐩存帴澶嶇敤 strategy-file锛屼笉鍐嶈姹?AI 鍐崇瓥...")
            else:
                print(f"       姝ｅ湪浣跨敤 AI 鐢熸垚鍦烘櫙锛屽苟鍦ㄦ瘡寮犺〃涓婂仛涓€娆″瓧娈垫潵婧愬喅绛栵紝鏁版嵁浠嶇敱鏈湴瑙勫垯鐢熸垚...")
            result = generation_service.generate(
                requirement_text,
                interfaces,
                args.sample_limit,
                generation_tag=generation_tag,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=True,
                use_ai_field_decisions=not bool(args.strategy_file),
                imported_field_decisions=imported_field_decisions,
            )
            _assert_ai_scenarios(result.scenarios, "agent_auto generate")
        elif args.strategy_mode == "agent":
            if args.strategy_file:
                raise ValueError("Agent mode only prepares prompt specs and cannot consume --strategy-file.")
            from api_data_gen.agents.orchestrator_service import AgentOrchestratorService

            agent_orchestrator = AgentOrchestratorService(
                planning_service=planning_service,
                interface_trace_service=interface_service,
                schema_service=schema_service,
                sample_repository=sample_repository,
                local_field_rule_service=local_field_rule_service,
            )
            print(f"[3/4] 鎵ц agent 妯″紡 (鐢熸垚鎻愮ず璇嶅寘)...")
            result = agent_orchestrator.generate(
                requirement_text,
                interfaces,
                args.sample_limit,
                generation_tag=generation_tag,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
            )
        else:
            use_ai_scenarios = args.strategy_mode == "direct" and args.use_ai_scenarios
            use_ai_data = args.strategy_mode == "direct" and args.use_ai_data
            if use_ai_scenarios:
                print(f"[3/4] 鎵ц {args.strategy_mode} 妯″紡 (AI鐢熸垚鍦烘櫙 + 鏈湴鐢熸垚鏁版嵁)...")
            elif use_ai_data:
                print(f"[3/4] 鎵ц {args.strategy_mode} 妯″紡 (鏈湴鐢熸垚鍦烘櫙 + AI鐢熸垚鏁版嵁)...")
            else:
                print(f"[3/4] 鎵ц {args.strategy_mode} 妯″紡 (绾湰鍦拌鍒?...")
            if use_ai_scenarios or use_ai_data:
                _require_ai_config(ai_chat_client)
            print(f"       姝ｅ湪鐢熸垚娴嬭瘯鏁版嵁...")
            result = generation_service.generate(
                requirement_text,
                interfaces,
                args.sample_limit,
                generation_tag=generation_tag,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=use_ai_scenarios,
                use_ai_data=use_ai_data,
                imported_field_decisions=imported_field_decisions,
            )
        print(f"[4/4] 鏁版嵁鐢熸垚瀹屾垚锛屾鍦ㄤ繚瀛樼粨鏋?..")

        if args.strategy_mode == "agent" and (args.sql_output_file or args.apply_sql):
            raise ValueError("Agent mode only prepares prompt specs and local context. Use local/direct/agent_auto mode to render or apply SQL.")

        # 鑷姩杈撳嚭鍒?output 鏂囦欢澶?
        _auto_save_output(
            result,
            args.strategy_mode,
            generation_tag,
            client,
            requirement_file=args.requirement_file,
            interfaces=interfaces,
        )

        if args.sql_output_file:
            print(f"       姝ｅ湪淇濆瓨 SQL 鏂囦欢鍒? {args.sql_output_file}")
            sql_export_service = SqlScriptExportService(client)
            output_path = Path(args.sql_output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                script = sql_export_service.append_missing_scenarios(
                    existing_script=output_path.read_text(encoding="utf-8"),
                    generated_tables=result.generated_tables,
                    validation_checks=result.validation_checks,
                    generation_tag=result.generation_tag,
                    batch_label=datetime.now().isoformat(timespec="seconds"),
                )
            else:
                script = sql_export_service.render(
                    result.generated_tables,
                    result.validation_checks,
                    generation_tag=result.generation_tag,
                )
            output_path.write_text(script, encoding="utf-8")
        if args.apply_sql:
            print(f"       姝ｅ湪灏?SQL 搴旂敤鍒版暟鎹簱...")
            apply_result = SqlApplyService(client).apply(
                result.generated_tables,
                result.validation_checks,
                force=args.force_apply,
            )
            result = replace(result, apply_result=apply_result)

        print(f"\n=== 浠诲姟瀹屾垚 ===")
        if hasattr(result, 'generated_tables') and result.generated_tables:
            total_tables = len(result.generated_tables)
            total_rows = sum(t.row_count for t in result.generated_tables)
            print(f"       鐢熸垚琛ㄦ暟: {total_tables}, 鎬昏鏁? {total_rows}")
        if hasattr(result, 'scenarios') and result.scenarios:
            print(f"       鍦烘櫙鏁? {len(result.scenarios)}")

        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return


def _parse_interface_target(raw_value: str) -> InterfaceTarget:
    if "=" not in raw_value:
        raise ValueError(f"Invalid --api value: {raw_value}")
    name, path = raw_value.split("=", 1)
    return InterfaceTarget(name=name.strip(), path=path.strip())


def _build_generation_tag() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _assert_ai_scenarios(scenarios, operation: str) -> None:
    if not scenarios:
        raise ValueError(f"{operation} produced no scenarios.")

    non_ai_ids = [
        getattr(scenario, "id", "<unknown>")
        for scenario in scenarios
        if getattr(scenario, "generation_source", "") != "ai"
    ]
    if non_ai_ids:
        raise ValueError(
            f"{operation} must return AI-generated scenarios, but found non-AI scenarios: {non_ai_ids}"
        )


def _assert_ai_generated_tables(generated_tables, operation: str) -> None:
    if not generated_tables:
        raise ValueError(f"{operation} produced no generated tables.")

    non_ai_tables = [
        getattr(table, "table_name", "<unknown>")
        for table in generated_tables
        if getattr(table, "generation_source", "") != "ai"
    ]
    if non_ai_tables:
        raise ValueError(
            f"{operation} must keep AI-generated table markers, but found non-AI tables: {non_ai_tables}"
        )


def _auto_save_output(
    result,
    strategy_mode: str,
    generation_tag: str | None,
    client: MysqlClient,
    requirement_file: str = "",
    interfaces: list[InterfaceTarget] | None = None,
) -> None:
    """Persist the command result to the local output directory."""
    from api_data_gen.services.sql_script_export_service import SqlScriptExportService
    from api_data_gen.services.strategy_export_service import StrategyExportService

    # 鍒涘缓 output 鏂囦欢澶?
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 鐢熸垚鏃堕棿鎴?
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_suffix = strategy_mode

    # 淇濆瓨 JSON 缁撴灉
    json_filename = f"result_{timestamp}_{mode_suffix}.json"
    json_path = output_dir / json_filename
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Output] JSON saved to: {json_path}")

    if hasattr(result, "generated_tables") and result.generated_tables:
        strategy_export_service = StrategyExportService()
        generated_at = datetime.now().isoformat(timespec="seconds")

        strategy_filename = f"strategy_{timestamp}_{mode_suffix}.json"
        strategy_path = output_dir / strategy_filename
        strategy_payload = strategy_export_service.render_strategy_config(
            report=result,
            strategy_mode=strategy_mode,
            generated_at=generated_at,
            source_result_file=json_filename,
        )
        strategy_path.write_text(json.dumps(strategy_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Output] Strategy JSON saved to: {strategy_path}")

        candidate_filename = f"generator_candidates_{timestamp}_{mode_suffix}.json"
        candidate_path = output_dir / candidate_filename
        candidate_payload = strategy_export_service.render_generator_candidates(
            report=result,
            strategy_mode=strategy_mode,
            generated_at=generated_at,
            source_result_file=json_filename,
            source_strategy_file=strategy_filename,
        )
        candidate_path.write_text(json.dumps(candidate_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Output] Generator candidates saved to: {candidate_path}")

    # 瀵逛簬 local銆乨irect 鍜?agent_auto 妯″紡锛岄澶栦繚瀛?SQL 鏂囦欢
    if strategy_mode in ("local", "direct", "agent_auto") and hasattr(result, "generated_tables") and result.generated_tables:
        sql_export_service = SqlScriptExportService(client)
        sql_filename = f"insert_{timestamp}_{mode_suffix}.sql"
        sql_path = output_dir / sql_filename
        script = sql_export_service.render(
            result.generated_tables,
            result.validation_checks,
            generation_tag=generation_tag,
        )
        sql_path.write_text(script, encoding="utf-8")
        print(f"[Output] SQL saved to: {sql_path}")

        cumulative_sql_path = DEFAULT_CUMULATIVE_SQL_PATH
        if cumulative_sql_path.exists():
            cumulative_script = sql_export_service.append_missing_scenarios(
                existing_script=cumulative_sql_path.read_text(encoding="utf-8"),
                generated_tables=result.generated_tables,
                validation_checks=result.validation_checks,
                generation_tag=generation_tag,
                batch_label=datetime.now().isoformat(timespec="seconds"),
            )
        else:
            cumulative_script = script
        cumulative_sql_path.write_text(cumulative_script, encoding="utf-8")
        print(f"[Output] Cumulative SQL saved to: {cumulative_sql_path}")


def _build_optional_ai_scenario_service(ai_chat_client: AiChatClient):
    if not ai_chat_client.is_configured():
        return None
    return AiScenarioService(ai_chat_client)


def _build_optional_ai_analysis_service(ai_chat_client: AiChatClient):
    if not ai_chat_client.is_configured():
        return None
    return AiDataAnalysisService(ai_chat_client)


def _build_optional_ai_data_service(ai_chat_client: AiChatClient):
    if not ai_chat_client.is_configured():
        return None
    return AiDataGenerationService(ai_chat_client)
def _require_ai_config(ai_chat_client: AiChatClient) -> None:
    if not ai_chat_client.is_configured():
        raise ValueError(
            "AI mode requested but AI settings are incomplete. Configure API_DATA_GEN_AI_PROVIDER and its required settings."
        )


if __name__ == "__main__":
    main()
