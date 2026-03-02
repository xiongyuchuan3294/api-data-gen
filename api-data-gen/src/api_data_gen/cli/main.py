from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from api_data_gen.config import load_settings
from api_data_gen.domain.models import InterfaceTarget
from api_data_gen.infra.db.dict_repository import DictRepository
from api_data_gen.infra.db.mysql_client import MysqlClient
from api_data_gen.infra.db.sample_repository import SampleRepository
from api_data_gen.infra.db.schema_repository import SchemaRepository
from api_data_gen.infra.db.trace_repository import TraceRepository
from api_data_gen.services.dict_rule_resolver import DictRuleResolver
from api_data_gen.services.interface_trace_service import InterfaceTraceService
from api_data_gen.services.phase1_validation_service import Phase1ValidationService
from api_data_gen.services.planning_service import PlanningService
from api_data_gen.services.requirement_parser import RequirementParser
from api_data_gen.services.schema_service import SchemaService
from api_data_gen.services.sql_parser import SqlParser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 1 local MySQL helpers")
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = load_settings(args.env_file)
    client = MysqlClient(settings)
    trace_repository = TraceRepository(client, settings)
    schema_repository = SchemaRepository(client)
    sample_repository = SampleRepository(client, settings.trace_schema, schema_repository)
    dict_repository = DictRepository(client, settings)
    schema_service = SchemaService(schema_repository)

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
        resolver = DictRuleResolver(dict_repository)
        result = resolver.resolve_code_values(args.column, args.comment)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "validate":
        interface_service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        resolver = DictRuleResolver(dict_repository)
        validation_service = Phase1ValidationService(
            interface_service,
            schema_repository,
            sample_repository,
            resolver,
        )
        result = validation_service.validate(args.sample_limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "draft":
        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
        interface_service = InterfaceTraceService(trace_repository, SqlParser(), settings)
        resolver = DictRuleResolver(dict_repository)
        planning_service = PlanningService(
            settings=settings,
            trace_repository=trace_repository,
            interface_trace_service=interface_service,
            schema_service=schema_service,
            sample_repository=sample_repository,
            dict_rule_resolver=resolver,
            requirement_parser=RequirementParser(),
        )
        interfaces = [_parse_interface_target(raw_value) for raw_value in args.api]
        result = planning_service.build_draft(requirement_text, interfaces, args.sample_limit)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return


def _parse_interface_target(raw_value: str) -> InterfaceTarget:
    if "=" not in raw_value:
        raise ValueError(f"Invalid --api value: {raw_value}")
    name, path = raw_value.split("=", 1)
    return InterfaceTarget(name=name.strip(), path=path.strip())
