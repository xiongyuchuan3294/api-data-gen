from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path

from api_data_gen.agents.orchestrator_service import AgentOrchestratorService
from api_data_gen.agents.hybrid_orchestrator import HybridAgentOrchestrator, ExecutionMode, ExecutionConfig
from api_data_gen.agents.executor import ReActExecutor
from api_data_gen.agents.skills.manager import SkillManager
from api_data_gen.config import load_settings
from api_data_gen.domain.models import InterfaceTarget
from api_data_gen.infra.db.field_match_repository import FieldMatchRepository
from api_data_gen.services.data_generation_service import DataGenerationService
from api_data_gen.services.ai_chat_client import AiChatClient
from api_data_gen.services.ai_data_analysis_service import AiDataAnalysisService
from api_data_gen.services.ai_data_generation_service import AiDataGenerationService
from api_data_gen.services.ai_scenario_service import AiScenarioService
from api_data_gen.infra.db.dict_repository import DictRepository
from api_data_gen.infra.db.mysql_client import MysqlClient
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
from api_data_gen.services.schema_service import SchemaService
from api_data_gen.services.sql_apply_service import SqlApplyService
from api_data_gen.services.sql_script_export_service import SqlScriptExportService
from api_data_gen.services.sql_parser import SqlParser


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
        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
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
        )
        interfaces = [_parse_interface_target(raw_value) for raw_value in args.api]

        # 处理 agent_auto 模式
        if args.strategy_mode == "agent_auto":
            _require_ai_config(ai_chat_client)
            hybrid_orchestrator = _build_hybrid_orchestrator(
                planning_service=planning_service,
                interface_trace_service=interface_service,
                schema_service=schema_service,
                sample_repository=sample_repository,
                local_field_rule_service=local_field_rule_service,
                ai_chat_client=ai_chat_client,
                schema_repository=schema_repository,
                ai_scenario_service=optional_ai_scenario_service,
                ai_data_generation_service=optional_ai_data_service,
                ai_data_analysis_service=optional_ai_analysis_service,
            )
            config = ExecutionConfig(
                mode=ExecutionMode.AGENT_AUTO,
                max_agent_turns=args.max_agent_turns,
            )
            result = hybrid_orchestrator.build_draft(
                requirement_text,
                interfaces,
                config=config,
                sample_limit=args.sample_limit,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
            )
        elif args.strategy_mode == "agent":
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
                _require_ai_config(ai_chat_client)
            result = planning_service.build_draft(
                requirement_text,
                interfaces,
                args.sample_limit,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=use_ai_scenarios,
            )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "generate":
        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
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
        )
        interfaces = [_parse_interface_target(raw_value) for raw_value in args.api]
        generation_tag = args.generation_tag
        if generation_tag is None and args.apply_sql:
            generation_tag = _build_generation_tag()

        # 处理 agent_auto 模式
        if args.strategy_mode == "agent_auto":
            _require_ai_config(ai_chat_client)
            hybrid_orchestrator = _build_hybrid_orchestrator(
                planning_service=planning_service,
                interface_trace_service=interface_service,
                schema_service=schema_service,
                sample_repository=sample_repository,
                local_field_rule_service=local_field_rule_service,
                ai_chat_client=ai_chat_client,
                schema_repository=schema_repository,
                ai_scenario_service=optional_ai_scenario_service,
                ai_data_generation_service=optional_ai_data_service,
                ai_data_analysis_service=optional_ai_analysis_service,
            )
            config = ExecutionConfig(
                mode=ExecutionMode.AGENT_AUTO,
                max_agent_turns=args.max_agent_turns,
            )
            result = hybrid_orchestrator.generate(
                requirement_text,
                interfaces,
                config=config,
                sample_limit=args.sample_limit,
                generation_tag=generation_tag,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
            )
        elif args.strategy_mode == "agent":
            agent_orchestrator = AgentOrchestratorService(
                planning_service=planning_service,
                interface_trace_service=interface_service,
                schema_service=schema_service,
                sample_repository=sample_repository,
                local_field_rule_service=local_field_rule_service,
            )
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
            if use_ai_scenarios or use_ai_data:
                _require_ai_config(ai_chat_client)
            result = generation_service.generate(
                requirement_text,
                interfaces,
                args.sample_limit,
                generation_tag=generation_tag,
                fixed_values=args.fixed_value,
                dependent_fixed_values=args.depend_fixed_value,
                use_ai_scenarios=use_ai_scenarios,
                use_ai_data=use_ai_data,
            )
        if args.strategy_mode in ("agent", "agent_auto") and (args.sql_output_file or args.apply_sql):
            raise ValueError("Agent mode only prepares prompt specs and local context. Use local/direct mode to render or apply SQL.")
        if args.sql_output_file:
            script = SqlScriptExportService(client).render(
                result.generated_tables,
                result.validation_checks,
                generation_tag=result.generation_tag,
            )
            output_path = Path(args.sql_output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(script, encoding="utf-8")
        if args.apply_sql:
            apply_result = SqlApplyService(client).apply(
                result.generated_tables,
                result.validation_checks,
                force=args.force_apply,
            )
            result = replace(result, apply_result=apply_result)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return


def _parse_interface_target(raw_value: str) -> InterfaceTarget:
    if "=" not in raw_value:
        raise ValueError(f"Invalid --api value: {raw_value}")
    name, path = raw_value.split("=", 1)
    return InterfaceTarget(name=name.strip(), path=path.strip())


def _build_generation_tag() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


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


def _build_hybrid_orchestrator(
    planning_service,
    interface_trace_service,
    schema_service,
    sample_repository,
    local_field_rule_service,
    ai_chat_client,
    schema_repository=None,
    ai_scenario_service=None,
    ai_data_generation_service=None,
    ai_data_analysis_service=None,
) -> HybridAgentOrchestrator:
    """构建混合模式 Agent 编排器"""
    # 初始化技能（如果尚未初始化）
    if not SkillManager.is_initialized():
        SkillManager.initialize(
            sample_repository=sample_repository,
            schema_repository=schema_repository,
            interface_trace_service=interface_trace_service,
            schema_service=schema_service,
            ai_scenario_service=ai_scenario_service,
            ai_data_generation_service=ai_data_generation_service,
            ai_data_analysis_service=ai_data_analysis_service,
            local_field_rule_service=local_field_rule_service,
        )

    # 创建 ReAct 执行器
    react_executor = ReActExecutor(llm_client=ai_chat_client)

    # 创建混合编排器
    return HybridAgentOrchestrator(
        planning_service=planning_service,
        interface_trace_service=interface_trace_service,
        schema_service=schema_service,
        sample_repository=sample_repository,
        local_field_rule_service=local_field_rule_service,
        ai_chat_client=ai_chat_client,
        react_executor=react_executor,
    )


def _require_ai_config(ai_chat_client: AiChatClient) -> None:
    if not ai_chat_client.is_configured():
        raise ValueError(
            "AI mode requested but AI settings are incomplete. Configure API_DATA_GEN_AI_PROVIDER and its required settings."
        )


if __name__ == "__main__":
    main()
