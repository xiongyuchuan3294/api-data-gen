# CLAUDE.md

## Current Boundary (2026-03-04)

- Default CLI mode is `agent_auto`. `local` and `agent` remain supported fallback modes.
- `field_match_relations` is only for sample fallback and auto-discovered sample-borrow mappings. It must not drive generation-time value alignment.
- `reusable_relation_strategies` is the generation-time cross-table consistency rule store. Rules may be inferred from scenarios, but once persisted they are reusable global rules.
- Generation-time cross-table alignment and validation are owned by explicit `reusable_relation_strategies`.
- There is no legacy `CrossTableAlignmentService` fallback anymore.

## Project Purpose

This repository generates API test data from:

- requirement text
- one or more interface mappings in `name=path` form
- MySQL trace, schema, sample, dictionary, and reusable-strategy data
- optional AI configuration

Main outputs include:

- scenario drafts
- table data plans
- generated JSON results
- reusable strategy JSON
- generator candidate JSON
- insert SQL

Primary CLI entry:

- `src/api_data_gen/cli/main.py`

## Execution Modes

### `agent_auto`

This is the default and recommended mode.

- `draft`: AI generates scenarios
- `generate`: AI generates scenarios, then local rules generate data
- `generate --strategy-file ...`: AI generates scenarios, imported strategy file is reused for field decisions, local rules generate data

Important:

- `agent_auto` is not a general ReAct loop
- it is an AI-planned, locally-executed generation path

### `agent`

This mode prepares prompt bundles and local context for an external agent/model.

- it does not directly run generation inside this project
- it does not consume `--strategy-file`
- it does not support `--apply-sql` or `--sql-output-file`

### `local`

Pure local fallback mode.

- no AI dependency
- scenarios and data come from local rules, traces, schemas, samples, and dictionaries

## Environment

Copy `.env.example` to `.env` and adjust values as needed.

Core settings are defined in:

- `src/api_data_gen/config.py`

Important variables:

```bash
API_DATA_GEN_MYSQL_HOST=127.0.0.1
API_DATA_GEN_MYSQL_PORT=3306
API_DATA_GEN_MYSQL_USER=root
API_DATA_GEN_MYSQL_PASSWORD=
API_DATA_GEN_MYSQL_CHARSET=utf8mb4

API_DATA_GEN_TRACE_SCHEMA=rrs_test_dev
API_DATA_GEN_BUSINESS_SCHEMA=aml_new3

API_DATA_GEN_SYSTEM_BASE_URL=http://172.21.8.178:9982/aml
API_DATA_GEN_SYS_ID=aml_web

API_DATA_GEN_AI_BASE_URL=
API_DATA_GEN_AI_API_KEY=
API_DATA_GEN_AI_PROVIDER=auto
API_DATA_GEN_AI_MODEL_NAME=
API_DATA_GEN_AI_TEMPERATURE=0.1
API_DATA_GEN_AI_RATE_LIMIT_MS=3000
API_DATA_GEN_AI_VERIFY_SSL=true
API_DATA_GEN_AI_CA_FILE=
API_DATA_GEN_AI_TIMEOUT_SEC=120
```

### Base URL Rule

The project concatenates:

- `API_DATA_GEN_SYSTEM_BASE_URL`
- `--api name=path`

directly.

Recommended pairing:

- `API_DATA_GEN_SYSTEM_BASE_URL=http://host:port/aml`
- `--api "custTransInfo=/wst/custTransInfo"`

Do not keep a trailing `/` in `API_DATA_GEN_SYSTEM_BASE_URL` when `--api` paths already start with `/`, otherwise trace lookup may miss due to `//` in the URL.

## Installation

```bash
pip install -e .
```

Or run directly:

```powershell
$env:PYTHONPATH="src"
python -m api_data_gen.cli.main --help
```

## Common Commands

### Exploration

```bash
api-data-gen interface --api-path /wst/custTransInfo --api-name custTransInfo
api-data-gen schema --table aml_f_tidb_model_result
api-data-gen sample --table aml_f_tidb_model_result --limit 3
api-data-gen dict --column model_key --comment "model code"
api-data-gen validate --sample-limit 2
```

### Draft

```bash
api-data-gen draft \
  --requirement-file ./requirements/test_wst_alert.txt \
  --api "custTransInfo=/wst/custTransInfo" \
  --api "custDrftRecord=/wst/custDrftRecord" \
  --strategy-mode agent_auto
```

### Generate

```bash
api-data-gen generate \
  --requirement-file ./requirements/test_wst_alert.txt \
  --api "custTransInfo=/wst/custTransInfo" \
  --api "custDrftRecord=/wst/custDrftRecord" \
  --strategy-mode agent_auto
```

Reuse a strategy file:

```bash
api-data-gen generate \
  --requirement-file ./requirements/test_wst_alert.txt \
  --api "custTransInfo=/wst/custTransInfo" \
  --api "custDrftRecord=/wst/custDrftRecord" \
  --strategy-mode agent_auto \
  --strategy-file ./output/strategy_*.json
```

## Output Contract

Generated files are written to:

- `output/`

### `draft`

Automatically writes:

- `result_{timestamp}_{mode}.json`

### `generate`

When `generated_tables` exists, it writes:

- `result_{timestamp}_{mode}.json`
- `strategy_{timestamp}_{mode}.json`
- `generator_candidates_{timestamp}_{mode}.json`

For `local` and `agent_auto`, it also writes:

- `insert_{timestamp}_{mode}.sql`

### Optional SQL Output

`generate --sql-output-file path.sql` writes an additional SQL file:

- creates the file if missing
- otherwise appends only missing scenarios through `append_missing_scenarios()`

### Applying SQL

`generate --apply-sql` applies generated inserts to MySQL.

- failed validation blocks apply by default
- `--force-apply` overrides that block

## Reusable Strategies

### Scenario Cache

AI scenario cache lives under:

- `output/ai_cache/scenarios/*.json`

### Exported Strategy Files

`generate` exports:

- `strategy_*.json`
- `generator_candidates_*.json`

### Reuse at Runtime

`agent_auto` and `local` support:

- `--strategy-file ./output/strategy_xxx.json`

### Persistent Reuse in MySQL

`DataGenerationService` persists reusable rules through:

- `reusable_field_strategies`
- `reusable_relation_strategies`

Current rule boundary:

- field-level reusable strategies are for generic local field generation
- relation-level reusable strategies are for explicit cross-table consistency during generation

## High-Level Flow

### Draft

1. Parse requirement text
2. Resolve interface trace and SQL chain
3. Load related schemas
4. Sample business rows
5. Build scenarios
6. Build `TableDataPlan` objects

### Generate

1. Build draft through `PlanningService`
2. Select scenarios
3. Generate or import field strategies
4. Generate local rows per table
5. Apply explicit relation-strategy alignment
6. Validate records and relation strategies
7. Render insert SQL
8. Export JSON, strategies, candidates, and SQL

## Key Data Structures

Defined in:

- `src/api_data_gen/domain/models.py`

Important models:

- `PlanningDraft`
- `GenerationReport`
- `GeneratedTable`
- `FieldGenerationStrategy`
- `RelationRule`
- `StoredRelationStrategy`

## Key Files

### CLI and Orchestration

- `src/api_data_gen/cli/main.py`
- `src/api_data_gen/agents/orchestrator_service.py`

### Core Services

- `src/api_data_gen/services/planning_service.py`
- `src/api_data_gen/services/data_generation_service.py`
- `src/api_data_gen/services/ai_scenario_service.py`
- `src/api_data_gen/services/ai_data_generation_service.py`
- `src/api_data_gen/services/relation_rule_derivation_service.py`
- `src/api_data_gen/services/relation_strategy_alignment_service.py`
- `src/api_data_gen/services/relation_strategy_validation_service.py`
- `src/api_data_gen/services/strategy_export_service.py`
- `src/api_data_gen/services/sql_script_export_service.py`

### Data Access

- `src/api_data_gen/infra/db/trace_repository.py`
- `src/api_data_gen/infra/db/schema_repository.py`
- `src/api_data_gen/infra/db/sample_repository.py`
- `src/api_data_gen/infra/db/field_match_repository.py`
- `src/api_data_gen/infra/db/reusable_strategy_repository.py`
- `src/api_data_gen/infra/db/dict_repository.py`

## Testing

Run all unit tests:

```bash
python -m unittest
```

Useful focused runs:

```bash
python -m unittest tests.test_data_generation_service
python -m unittest tests.test_planning_service
python -m unittest tests.test_reusable_strategy_repository
python -m unittest tests.test_reusable_strategy_service
```

Syntax check:

```bash
python -m py_compile src/api_data_gen/cli/main.py
```

## Change Rules

If you change any of these boundaries, update docs and tests together:

- real meaning of `--strategy-mode`
- generated output file contract
- responsibility split between `agent`, `agent_auto`, and `local`
- structure of `strategy_*.json` and `generator_candidates_*.json`
- generation-time relation-strategy behavior

Check these files first when changing behavior:

- `src/api_data_gen/cli/main.py`
- `src/api_data_gen/services/data_generation_service.py`
- `src/api_data_gen/services/strategy_export_service.py`
- `tests/test_data_generation_service.py`
- `tests/test_strategy_export_service.py`
- `tests/test_sql_script_export_service.py`

## Do Not Assume

The following are not true in the current implementation:

- `API_DATA_GEN_AGENT_MODE` controls CLI strategy mode
- `--agent-mode` is an active CLI argument
- `agent_auto` is wired into a general ReAct execution loop
- generation maintains a separate legacy cumulative SQL output file by default
- `field_match_relations` controls generation-time cross-table alignment

When code and older notes disagree, trust current implementation and this file.
