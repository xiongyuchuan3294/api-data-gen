# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **API Test Data Generation Tool** that generates test data for API testing by analyzing interface traces, table schemas, and generating SQL INSERT statements. It combines local database analysis with optional AI capabilities.

## Common Commands

### Installation
```bash
pip install -e .
```

### Configuration
Copy `.env.example` to `.env` and configure:
- MySQL connection (host, port, user, password, charset)
- Database schemas (trace_schema, business_schema)
- AI provider settings (optional: OpenAI, Anthropic, Claude Code)
- System settings (base URL, sys_id)

### Database Setup
```bash
mysql --default-character-set=utf8mb4 -u root -p < sql/mysql/phase1_seed.sql
```

### Running the CLI
```bash
# Extract SQL/table info from interface traces
api-data-gen interface --api-path /api/customer/query --api-name queryCustomer

# Read table schema
api-data-gen schema --table t_customer

# Sample rows from a table
api-data-gen sample --table t_customer --limit 3

# Build scenario drafts (Phase 2)
api-data-gen draft --requirement-file req.txt --api "query=/api/query"

# Generate test data (Phase 3)
api-data-gen generate --requirement-file req.txt --api "query=/api/query"
```

### Execution Strategies
- `agent` (default) - Prepares prompts for external AI with local context
- `agent_auto` - Hybrid mode: AI planning + local execution via ReAct agent
- `local` - Pure local rule-based execution
- `direct` - Direct AI calls without agent orchestration

### Running Tests
```bash
pytest tests/                          # All tests
pytest tests/test_skills_decorator.py  # Specific test file
```

### MCP Server (for external AI integration)
```bash
python -m api_data_gen.agents.mcp.server --port 8000 --init-skills
```

## Architecture

### Layer Structure

```
cli/main.py          # Entry point, argument parsing, service orchestration
       ↓
agents/              # AI agent orchestration
  ├── orchestrator_service.py      # Main agent orchestration
  ├── hybrid_orchestrator.py      # Hybrid AI + local execution (agent_auto mode)
  ├── executor/                   # ReAct execution engine
  │   ├── react_executor.py       # Tool-calling agent implementation
  │   └── base.py                 # Execution result types
  ├── skills/                     # Skill definitions (decorator-based)
  │   ├── data_sampling.py       # Table sampling skills
  │   ├── scenario_skills.py      # Scenario generation skills
  │   ├── data_generation.py     # Data generation skills
  │   └── interface_skills.py    # Interface/SQL extraction skills
  └── mcp/                        # MCP protocol integration
       └── server.py               # HTTP server for tool calling
       ↓
services/            # Core business logic
  ├── planning_service.py          # Phase 2: Draft planning
  ├── data_generation_service.py   # Phase 3: SQL generation
  ├── ai_scenario_service.py      # AI scenario generation
  ├── ai_data_generation_service.py
  ├── ai_chat_client.py           # Multi-provider AI client
  ├── local_field_rule_service.py # Business field rules
  ├── field_match_*.py           # Cross-table alignment
  ├── sql_apply_service.py        # Apply SQL to database
  └── sql_script_export_service.py
       ↓
infra/db/            # Database access
  ├── mysql_client.py             # MySQL connection
  ├── schema_repository.py        # Table schema access
  ├── sample_repository.py        # Data sampling
  ├── trace_repository.py         # Interface trace access
  └── field_match_repository.py  # Cross-table field mapping
       ↓
domain/models.py     # Data classes (TraceRequest, TableSchema, etc.)
```

### Data Flow

1. **Phase 1** - Bootstrap: Create mock MySQL databases with trace and business tables
2. **Phase 2** - Draft: Analyze requirements + interfaces → create scenario/data drafts
3. **Phase 3** - Generate: Generate SQL INSERT statements from drafts

### Key Design Patterns

- **Dependency Injection**: Services receive dependencies via constructor
- **Strategy Pattern**: Multiple AI providers (OpenAI, Anthropic, Claude Code)
- **Orchestration Pattern**: AgentOrchestratorService coordinates multi-stage execution
- **Skill System**: `@skill` decorator registers functions as callable tools for agents
- **Hybrid Execution**: Supports both fixed-flow and AI-autonomous modes

## Data Generation Logic (Phase 3)

### Value Source Rules

Data generation applies column plans with deterministic priority:

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | `condition` | Use fixed SQL filter values from interface traces |
| 2 | `dictionary` | Cycle through dictionary/code mapping values |
| 3 | `sample` | Cycle through sampled business data |
| 4 | `generated` | Create deterministic primary-key style values |
| 5 | `default` | Materialize concrete local fallback values |
| 6 | `optional` | Emit `NULL` for nullable columns |

### Primary Key Handling

- Non-auto primary keys always use generated values unless conditions fix them
- Auto primary keys render as `DEFAULT`
- Sampled primary-key values are NOT reused
- When `generation_tag` is provided, generated PKs include tag-derived token to avoid collisions

### Cross-Table Field Alignment

When `field_match_relations` contains `target_table.target_field <- source_table.source_field`:
- Values are aligned from generated source rows
- Condition-derived fields are not overwritten (conflicts reported in validation)

When a target table has no samples and no relations:
- Automatic field-match discovery is triggered
- Candidate source tables ranked by row count
- Matching prefers identical column names, then identical comments
- Discovered relations are persisted to `rrs_test_dev.field_match_relations`

### Local Business Field Rules

Applied before any AI data generation:

- `cust_id`-like fields: deterministic 18-digit values (e.g., `962020122711000002`)
- `transactionkey`: Java-compatible pattern `6008CYYYYMMDD...99996`
- `model_seq`: empty string
- Dictionary-backed fields: generated locally first

### AI Data Filling (--use-ai-data)

When enabled:
- Sampled rows are masked for locally generated fields
- Optional sample analysis runs first, feeds per-table hints
- AI only fills non-local fields; local rules still win

### Required Column Fallbacks

For required columns without concrete source:
- Numeric types: `0`
- Datetime/timestamp: `1970-01-01 00:00:00`
- Date: `1970-01-01`
- Text-like: `column_name_N`

### Generation Tag

The `generation_tag` ensures deterministic primary keys don't collide across batches:
- Format: `RUN20260302` or timestamp-based
- Appended to generated PKs for differentiation
- Required when using `--apply-sql` multiple times

## Important Files

- `src/api_data_gen/cli/main.py` - CLI entry point
- `src/api_data_gen/agents/hybrid_orchestrator.py` - Hybrid execution mode
- `src/api_data_gen/agents/executor/react_executor.py` - ReAct agent implementation
- `src/api_data_gen/agents/skills/decorator.py` - Skill registration decorator
- `src/api_data_gen/services/planning_service.py` - Core planning logic
- `src/api_data_gen/services/data_generation_service.py` - Core generation logic
- `src/api_data_gen/services/local_field_rule_service.py` - Business field rules
- `src/api_data_gen/domain/models.py` - All domain data classes

## Working with the Agent System

### Defining a New Skill
```python
from api_data_gen.agents.skills import skill

@skill(name="my_skill", description="What this skill does")
def my_skill(param1: str, param2: int = 5) -> dict:
    """Skill implementation"""
    return {"result": param1}
```

### Using Agent Auto Mode
```python
from api_data_gen.agents import HybridAgentOrchestrator, ExecutionMode, ExecutionConfig

config = ExecutionConfig(mode=ExecutionMode.AGENT_AUTO, max_agent_turns=15)
orchestrator = HybridAgentOrchestrator(..., react_executor=ReActExecutor(llm_client))
report = orchestrator.generate(requirement, interfaces, config=config)
```

## Environment Variables

Key settings in `.env`:
- `API_DATA_GEN_MYSQL_HOST`, `API_DATA_GEN_MYSQL_PORT`, etc.
- `API_DATA_GEN_TRACE_SCHEMA` - Trace database name
- `API_DATA_GEN_BUSINESS_SCHEMA` - Business database name
- `API_DATA_GEN_AI_PROVIDER` - openai/anthropic/claude_code
- `API_DATA_GEN_AI_API_KEY`, `API_DATA_GEN_AI_BASE_URL`
- `API_DATA_GEN_AGENT_MODE` - local/direct/agent_prompt/agent_auto
