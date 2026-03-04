# Phase 3 Data Generation

Phase 3 consumes the `draft` output from Phase 2 and turns it into executable artifacts:

- row candidates per table
- scenario-scoped generated rows
- deterministic local fallback values
- rendered `INSERT` SQL

The current primary path is `--strategy-mode agent_auto`:

- AI generates scenarios inside the project
- `generate` may ask AI for table-level field generation strategies
- final row generation, validation, and SQL rendering remain local

Fallback modes are:

- `--strategy-mode local`
- `--strategy-mode agent`

`direct` mode and the old `--use-ai-scenarios` / `--use-ai-data` CLI flags are no longer part of the public interface.

## Scope

Phase 3 includes:

- materializing `table_plans` into scenario-scoped row candidates
- preserving separate generated rows per scenario instead of flattening all scenarios into one table-level result
- reusing fixed SQL conditions as stable field values
- accepting explicit `fixed_value` and `depend_fixed_value` hints from the CLI
- reusing dictionary and sampled values where available
- auto-discovering and persisting `field_match_relations` when direct table samples are missing
- generating primary keys and required business fallback values locally
- avoiding reuse of sampled primary-key values even when samples exist
- locally generating Java-compatible business fields such as `cust_id`, `transactionkey`, and `model_seq`
- validating cross-table consistency for shared condition-driven fields
- applying `reusable_relation_strategies` to align explicit cross-table consistency rules
- validating and truncating generated records against table schema before SQL rendering
- rendering MySQL `INSERT` SQL
- supporting generation tags so repeated apply runs can avoid deterministic primary-key collisions
- optionally reusing imported field-generation strategies from `strategy_*.json`

Phase 3 does not include:

- general ReAct orchestration inside the CLI
- arbitrary external tool loops
- direct public CLI flags for forcing legacy AI branches

## Value Source Rules

`generate` applies the current `column_plans` with a deterministic priority:

- `condition`: use the fixed SQL value
- `dictionary`: cycle through dictionary candidates
- `sample`: cycle through sampled values
- `generated`: create deterministic primary-key style values
- `default`: materialize a concrete local fallback instead of leaving abstract placeholders
- `optional`: emit `NULL`

Primary keys are special-cased:

- non-auto primary keys always use generated values unless SQL conditions fix them explicitly
- auto primary keys render as `DEFAULT`
- sampled primary-key values are not reused
- when a `generation_tag` is provided, generated primary keys include a tag-derived token so separate apply batches do not reuse the same deterministic key values

Reusable relation strategies are also supported:

- when `reusable_relation_strategies` contains `target_table.target_field <- source_table.source_field`
- and both tables are in the current generation scope
- `generate` aligns target values from the generated source rows
- condition-derived target fields are not overwritten, but conflicts are reported in validation

When a target table has no direct samples and no existing sample fallback mappings:

- `generate` falls back to automatic field-match discovery
- candidate source tables are ranked by row count
- matching prefers identical column names, then identical comments, with compatible types only
- discovered relations are persisted back to `rrs_test_dev.field_match_relations` for future sample fallback only

Local business field rules are also applied before final rendering:

- dictionary-backed fields are generated locally first
- customer-id-like fields use deterministic 18-digit values
- `transactionkey` uses the Java-compatible `6008CYYYYMMDD...99996` pattern
- `model_seq` is emitted as an empty string
- fixed values override those local generators when field names match

For required columns without a concrete source:

- numeric types use `0`
- `datetime`/`timestamp` use `1970-01-01 00:00:00`
- `date` uses `1970-01-01`
- text-like fields use `column_name_N`

## CLI Usage

Run Phase 3 with the current default mode:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --strategy-mode agent_auto
```

Reuse an exported strategy file while still generating scenarios with AI:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --strategy-mode agent_auto `
  --strategy-file output/strategy_20260304_094815_agent_auto.json
```

Force fully local fallback behavior:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --strategy-mode local
```

Prepare an external-agent prompt bundle instead of generating rows inside the project:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --strategy-mode agent
```

Write a combined SQL script to disk:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --generation-tag RUN20260302 `
  --sql-output-file output/generated.sql
```

Apply generated inserts directly to the configured local MySQL schemas:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --apply-sql
```

Notes:

- `--strategy-mode agent_auto` is the default mode
- `--generation-tag` is optional for plain preview generation
- when `--apply-sql` is used without an explicit tag, the CLI auto-generates one from the current timestamp
- the generated report and exported SQL script both include the final `generation_tag`
- AI features require `API_DATA_GEN_AI_BASE_URL` and `API_DATA_GEN_AI_MODEL_NAME`; `API_DATA_GEN_AI_API_KEY` is optional for compatible gateways
- `API_DATA_GEN_AI_PROVIDER` defaults to `auto`; use `anthropic` when the gateway speaks Anthropic Messages API instead of OpenAI Chat Completions
- when the credential is Claude Code-only, set `API_DATA_GEN_AI_PROVIDER=claude_code`; this uses the local `claude` CLI instead of direct HTTP calls
- for internal HTTPS endpoints with self-signed or private CA certificates, set `API_DATA_GEN_AI_VERIFY_SSL=false` or provide `API_DATA_GEN_AI_CA_FILE`
- `--strategy-mode agent` only outputs `agent_bundle` / `agent_run` and does not render SQL
- `--sql-output-file` and `--apply-sql` are only meaningful in `local` or `agent_auto` mode

Without installing the package:

```powershell
$env:PYTHONPATH="src"
python3 -m api_data_gen.cli.main generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord
```

## Output Structure

The `generate` command returns:

- `requirement`: parsed requirement summary
- `scenarios`: local or AI-generated scenario drafts
- `table_plans`: the source planning used for generation
- `generated_tables`: scenario-scoped row candidates plus rendered `INSERT` SQL
- `scenario_generations`: grouped generated tables and validation checks per scenario
- `validation_checks`: cross-table consistency checks for shared condition columns, relation-driven field mapping checks, and record-level normalization/truncation checks
- `generation_tag`: the normalized batch tag used for generated values, if any
- `agent_run`: the local preparation trace when agent mode is used
- `agent_bundle`: prompt specs, tool specs, samples, table plans, and local context for an external model

Each generated table contains:

- `table_name`
- `row_count`
- `rows`
- `insert_sql`
- `scenario_id`
- `scenario_title`

When `--sql-output-file` is provided, the CLI also writes a single SQL script that:

- adds validation comments
- adds scenario headers
- groups inserts by schema with `USE schema`
- wraps the output in `START TRANSACTION` / `COMMIT`

When `--apply-sql` is provided:

- generated inserts are executed directly against the configured MySQL schemas
- apply is blocked if any validation check fails
- `--force-apply` can override that guardrail
- repeated apply runs should use different generation tags; the CLI does this automatically when applying

## Exit Criteria

Phase 3 is considered complete for the current local-rendering slice when:

- at least one table can be materialized from a real `draft`
- the output contains executable `INSERT` SQL
- the relevant unit tests pass against the implementation
