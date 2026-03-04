# Phase 5 Agent Skill Bootstrap

Phase 5 no longer treats scenario generation and data generation as a fixed if/else chain in CLI.

The current default execution mode is `agent_auto`, which means:

- the project still collects trace, schema, sample, and local-rule context first
- AI is used inside the project to generate scenarios
- `generate` can also ask AI for table-level field generation decisions
- final row generation, merge, validation, and SQL rendering still run through local Python services

`agent_auto` is the primary runtime path. `local` and `agent` are retained as fallback modes.

## Skill Catalog

The current bootstrap exposes these skills to the routing agent:

- `extract_interface_sql`
- `load_table_schema`
- `resolve_local_generators`
- `generate_scenarios_local`
- `generate_scenarios_ai`
- `sample_table_data`
- `analyze_samples_ai`
- `generate_table_rows_local`
- `generate_table_rows_ai`
- `merge_and_validate_rows`
- `render_insert_sql`

These skills are not separate shell plugins yet. They are explicit local method nodes mapped onto the existing Python services.

## CLI Modes

`draft` and `generate` now support:

- `--strategy-mode agent_auto`
  - default mode
  - AI generates scenarios inside the project
  - `generate` may also request AI field strategy decisions
  - final data rows and SQL are still produced by local services
- `--strategy-mode local`
  - fallback mode
  - force local-only behavior
- `--strategy-mode agent`
  - fallback mode
  - only prepares prompt specs and local context
  - does not call the model internally

## Output Contract

When `agent` mode is used, both `draft` and `generate` return `agent_run` and `agent_bundle`:

- `decision`
  - records that strategy choice is delegated to the external model
- `executed_skills`
  - ordered local preparation trace with short summaries
- `agent_bundle`
  - `tool_specs`
  - `prompt_specs`
  - `table_plans`
  - `sample_rows_by_table`
  - `local_fields_by_table`
  - `local_reference_scenarios`

When `agent_auto` or `local` mode is used in `generate`, the project also renders SQL inside the runtime.

## Provider Notes

`agent_auto` reuses the optional in-project AI client abstraction:

- `openai`
- `anthropic`
- `claude_code`

When `API_DATA_GEN_AI_PROVIDER=claude_code`, `agent_auto` goes through the local `claude -p` CLI instead of direct HTTP requests.

## Current Boundary

This bootstrap removes hardcoded `direct` mode selection from the public CLI.

It does not yet provide:

- standalone MCP tool registration per skill
- a general external planner that can loop or retry arbitrary skills
- automatic replay of external model outputs back into local merge/validate/render steps
- multi-agent delegation
