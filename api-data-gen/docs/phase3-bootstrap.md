# Phase 3 Data Generation

Phase 3 consumes the `draft` output from Phase 2 and turns it into executable artifacts:

- row candidates per table
- scenario-scoped generated rows
- deterministic local fallback values
- rendered `INSERT` SQL

The default path is still fully local. AI-assisted scenario expansion and AI-assisted non-local field completion are now optional CLI features and are only used when the corresponding flags are enabled.

## Scope

Phase 3 includes:

- Materializing `table_plans` into scenario-scoped row candidates
- Preserving separate generated rows per scenario instead of flattening all scenarios into one table-level result
- Reusing fixed SQL conditions as stable field values
- Accepting explicit `fixed_value` and `depend_fixed_value` hints from the CLI
- Reusing dictionary and sampled values where available
- Auto-discovering and persisting `field_match_relations` when direct table samples are missing
- Generating primary keys and required business fallback values locally
- Avoiding reuse of sampled primary-key values even when samples exist
- Locally generating Java-compatible business fields such as `cust_id`, `transactionkey`, and `model_seq`
- Validating cross-table consistency for shared condition-driven fields
- Applying `field_match_relations` to align cross-name fields from source tables
- Validating and truncating generated records against table schema before SQL rendering
- Rendering MySQL `INSERT` SQL
- Supporting generation tags so repeated apply runs can avoid deterministic primary-key collisions
- Optionally calling AI to generate scenarios and fill non-local fields per scenario

Phase 3 does not include:

- Strategy routing or agent orchestration
- Automatic selection between local and AI strategies beyond explicit CLI flags

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
- when a `generation_tag` is provided, generated primary keys include a tag-derived token
  so separate apply batches do not reuse the same deterministic key values

Explicit field-match relations are also supported:

- when `field_match_relations` contains `target_table.target_field <- source_table.source_field`
- and both tables are in the current generation scope
- `generate` aligns target values from the generated source rows
- condition-derived target fields are not overwritten, but conflicts are reported in validation

When a target table has no direct samples and no existing relations:

- `generate` falls back to automatic field-match discovery
- candidate source tables are ranked by row count
- matching prefers identical column names, then identical comments, with compatible types only
- discovered relations are persisted back to `rrs_test_dev.field_match_relations`

Local business field rules are also applied before any AI data:

- dictionary-backed fields are generated locally first
- customer-id-like fields use deterministic 18-digit values
- `transactionkey` uses the Java-compatible `6008CYYYYMMDD...99996` pattern
- `model_seq` is emitted as an empty string
- fixed values override those local generators when field names match

When `--use-ai-data` is enabled:

- sampled rows are masked for locally generated fields before being sent to AI
- optional sample analysis runs first and feeds per-table hints into generation
- AI only fills non-local fields; local rules, fixed conditions, and primary-key generation still win

For required columns without a concrete source:

- numeric types use `0`
- `datetime`/`timestamp` use `1970-01-01 00:00:00`
- `date` uses `1970-01-01`
- text-like fields use `column_name_N`

## CLI Usage

Run Phase 3 from the same requirement file and interface mapping used in Phase 2:

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

Generate AI scenarios from the same requirement and interface chain:

```powershell
api-data-gen draft `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --fixed-value cust_id=962020122711000002 `
  --depend-fixed-value "transactionkey depends on alert_date" `
  --use-ai-scenarios
```

Use AI to fill non-local fields during Phase 3 generation:

```powershell
api-data-gen generate `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord `
  --fixed-value cust_id=962020122711000002 `
  --depend-fixed-value "transactionkey depends on alert_date" `
  --strategy-mode direct `
  --use-ai-scenarios `
  --use-ai-data
```

Notes:

- `--generation-tag` is optional for plain preview generation
- when `--apply-sql` is used without an explicit tag, the CLI auto-generates one from the current timestamp
- the generated report and exported SQL script both include the final `generation_tag`
- AI features require `API_DATA_GEN_AI_BASE_URL` and `API_DATA_GEN_AI_MODEL_NAME`; `API_DATA_GEN_AI_API_KEY` is optional for compatible gateways
- `API_DATA_GEN_AI_PROVIDER` defaults to `auto`; use `anthropic` when the gateway speaks Anthropic Messages API instead of OpenAI Chat Completions
- when the credential is Claude Code-only, set `API_DATA_GEN_AI_PROVIDER=claude_code`; this uses the local `claude` CLI instead of direct HTTP calls
- for internal HTTPS endpoints with self-signed or private CA certificates, set `API_DATA_GEN_AI_VERIFY_SSL=false` or provide `API_DATA_GEN_AI_CA_FILE`
- `--strategy-mode agent` is now the default; in this mode the project only输出 `agent_bundle`，不直接在项目内部调用模型
- `--strategy-mode direct` keeps the old explicit `--use-ai-scenarios` / `--use-ai-data` behavior
- `--sql-output-file` and `--apply-sql` are only meaningful in `local` or `direct` mode

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
- `validation_checks`: cross-table consistency checks for shared condition columns
  relation-driven field mapping checks, and record-level normalization/truncation checks
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

Phase 3 is considered complete for the local-only slice when:

- at least one table can be materialized from a real `draft`
- the output contains executable `INSERT` SQL
- the full unit test suite passes against the local implementation

For Java parity, the Phase 3 implementation now also covers:

- scenario-scoped generation and SQL output
- automatic field-match discovery and persistence
- fixed-value and dependent-fixed-value inputs
- local business field generators used before AI completion
- record-level schema validation and truncation
