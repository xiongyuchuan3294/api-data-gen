# Phase 2 Draft Planning

Phase 2 builds on the Phase 1 MySQL mock and repository layer. The goal of this stage is not to generate final SQL inserts yet. It produces a deterministic draft that turns:

- a requirement description
- one or more interface mappings
- the captured SQL behavior from `t_request_info` and `t_database_operation`

into:

- requirement summary
- scenario drafts
- table-level data generation drafts

## Scope

Phase 2 includes:

- Requirement parsing
- Interface-to-table aggregation
- Fixed request input extraction from captured traces
- Table schema loading
- Business sample aggregation
- Dictionary-aware column planning
- Scenario draft generation

Phase 2 does not include:

- LLM-based scenario generation
- Local rule row generation
- Insert SQL rendering
- Agent routing or strategy selection

## Public Output

The `draft` command returns three top-level sections:

- `requirement`
  Captured summary, constraints, and keywords from the requirement text.
- `scenarios`
  Deterministic scenario drafts per interface, including:
  - baseline replay
  - pagination stability when paging params exist
  - dictionary consistency when dictionary-backed fields are present
- `table_plans`
  Per-table column planning with value source classification:
  - `condition`
  - `dictionary`
  - `sample`
  - `generated`
  - `default`
  - `optional`

## CLI Usage

Install once:

```powershell
pip install -e .
```

Run a Phase 2 draft from the current requirement file:

```powershell
api-data-gen draft `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord
```

Use a different env file if needed:

```powershell
api-data-gen --env-file .env.local draft `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord
```

Without installing the package:

```powershell
$env:PYTHONPATH="src"
python -m api_data_gen.cli.main draft `
  --requirement-file 需求描述 `
  --api custTransInfo=/wst/custTransInfo `
  --api custDrftRecord=/wst/custDrftRecord
```

## Expected Use

Use this stage to answer:

- Which tables are really in scope for each interface
- Which filter values are fixed by the captured SQL
- Which columns can already be sourced from samples or dictionaries
- Which columns still need local rules or LLM completion in later phases

## Next Phase

Phase 3 should consume `table_plans` and start producing actual row candidates with local generators and validation rules, before moving to LLM augmentation.
