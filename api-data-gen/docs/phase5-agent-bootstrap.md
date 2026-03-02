# Phase 5 Agent Skill Bootstrap

Phase 5 no longer treats scenario generation and data generation as a fixed if/else chain in CLI.

The new default execution mode is `agent`, which means:

- local tools still collect trace, schema, sample, and local-rule context first
- the project only emits prompt specs, local methods, and local context
- scenario generation and test-data generation are delegated to the external model or agent runtime
- the local preparation workflow is recorded in the output as `agent_run`
- the prompt bundle is recorded in the output as `agent_bundle`

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

## Supported Strategies

In `agent` mode the project does not execute strategy choice itself. Instead it emits:

- a routing prompt asking the external model to choose `scenario_strategy`
- a scenario-generation prompt
- a data-generation prompt

The project still keeps executable local paths in:

- `--strategy-mode local`
- `--strategy-mode direct`

## CLI Modes

`draft` and `generate` now support:

- `--strategy-mode agent`
  - default mode
  - only prepares prompt specs and local context
  - does not call the model internally
- `--strategy-mode local`
  - force local-only behavior
- `--strategy-mode direct`
  - keep the previous explicit flag style
  - `--use-ai-scenarios` and `--use-ai-data` are only meaningful in this mode

## Output Contract

Both `draft` and `generate` now return `agent_run` and `agent_bundle` when executed in agent mode:

- `decision`
  - only records that strategy choice is delegated to the external model
- `executed_skills`
  - ordered local preparation trace with short summaries
- `agent_bundle`
  - `tool_specs`
  - `prompt_specs`
  - `table_plans`
  - `sample_rows_by_table`
  - `local_fields_by_table`
  - `local_reference_scenarios`

This makes the workflow inspectable and keeps model invocation outside the project runtime.

## Provider Notes

`direct` mode still reuses the optional in-project AI client abstraction:

- `openai`
- `anthropic`
- `claude_code`

When `API_DATA_GEN_AI_PROVIDER=claude_code`, direct mode goes through the local `claude -p` CLI instead of direct HTTP requests.

## Current Boundary

This bootstrap solves the architectural problem of hardcoded strategy selection inside the project.

It does not yet provide:

- standalone MCP tool registration per skill
- a general external planner that can loop or retry arbitrary skills
- automatic replay of external model outputs back into local merge/validate/render steps
- multi-agent delegation
