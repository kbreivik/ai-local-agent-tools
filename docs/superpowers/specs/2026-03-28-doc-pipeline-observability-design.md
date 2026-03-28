# Doc Pipeline Observability Design

**Date:** 2026-03-28
**Status:** Approved

## Problem

The doc→skill generation pipeline (ingest → MuninnDB → `doc_retrieval.py` → `prompt_builder.py` → LLM → skill code) has no observability. There is no way to verify whether ingested documents are being retrieved and injected into skill generation prompts, or to see which services lack doc coverage. Skills may be generated with zero context and there is currently no signal to indicate this.

## Goal

Add durable trace data, human-visible doc coverage, and automated verification so that the pipeline can be trusted and diagnosed.

## Architecture

Three additions with clear boundaries:

1. **`skill_generation_log` table** — written by `generator.py` via the skills storage backend after every generation attempt. Stores the full retrieval trace. One row per attempt, never mutated.
2. **Two new read-only endpoints** in `api/routers/skills.py` — expose log data for GUI consumption.
3. **New "Docs" tab in the GUI** — shows doc coverage by service and per-skill generation trace.

### Changes to `generator.py`
Two changes required (both in `generator.py`):

1. **Refactor `_fetch_relevant_docs()` wrapper** — currently calls `fetch_relevant_docs()` and discards the structured result, returning only a formatted string. Must be changed to also return the raw result dict (`keywords`, `docs_retrieved`, `sources_used`, `total_tokens`) so `generate_skill()` can log it.

2. **Add `_write_generation_log()`** — private helper called at the end of `generate_skill()`. Uses `get_backend()` (the sync skills storage backend) to write the log row. Wrapped in `try/except` so a log failure never blocks generation. Does NOT use the async `api/db/` SQLAlchemy layer — the generator runs in the MCP server process, not the FastAPI process.

No changes to `doc_retrieval.py`, `prompt_builder.py`, or `spec_generator.py`.

## Data Model

### New table: `skill_generation_log`

Added to `api/db/models.py` (SQLAlchemy model) and `api/db/migrations.py` (new migration entry). **Not** `migrate_sqlite.py` — that file is a one-time SQLite→Postgres data migration tool, not for schema changes.

```python
# Columns
id             TEXT PRIMARY KEY      # UUID, generated at write time
skill_name     TEXT NOT NULL         # e.g. "fortigate_system_status"
triggered_by   TEXT                  # "skill_create" | "skill_regenerate" | "export"
backend        TEXT                  # "local" | "cloud" | "export"
description    TEXT
category       TEXT
api_base       TEXT                  # nullable
keywords       TEXT                  # JSON: {services, tech, endpoints, versions}
                                     # from fetch_relevant_docs() result["data"]["keywords"]
docs_retrieved TEXT                  # JSON array of docs that were injected into the prompt:
                                     # [{concept, doc_type, tags, tokens}]
                                     # fields match _budget_content() output exactly
total_tokens   INTEGER               # sum of tokens across docs_retrieved
sources_used   TEXT                  # JSON: ["muninndb", "service_catalog", "local_files"]
                                     # from fetch_relevant_docs() result["data"]["sources_used"]
spec_used      INTEGER               # 0 or 1
spec_warnings  TEXT                  # JSON array, nullable
outcome        TEXT                  # "success" | "error" | "export"
error_message  TEXT                  # nullable
created_at     REAL                  # time.time()
```

**Note on `docs_retrieved` fields:** matches the actual `_budget_content()` output: `concept`, `doc_type`, `tags`, `tokens`. No `source` or `activation_score` fields — those are not in the retrieval pipeline output and are not added.

**Note on `triggered_by`:** `generate_skill()` must accept a new optional `triggered_by: str = "skill_create"` parameter. Callers in `meta_tools.py` pass `"skill_create"` or `"skill_regenerate"` explicitly. The export path passes `"export"`.

### Doc Coverage (no new table)

Coverage data is derived at query time:
- Services list: `SELECT * FROM service_catalog`
- Whether a service has ingested docs: check `api_docs_ingested` boolean field in `service_catalog` (already present). A service is considered "no docs" when `api_docs_ingested IS NULL OR api_docs_ingested = 0`.
- Doc count and last-ingested date: from `GET /api/memory/docs` (existing endpoint in `api/routers/memory.py`)

No new table required for coverage.

## Data Flow

```
skill_create() / skill_regenerate()  [meta_tools.py]
  └─→ generate_skill(triggered_by=...)  [generator.py]
        ├─→ _fetch_relevant_docs()  ← REFACTORED: returns (formatted_str, raw_result_dict)
        │     └─→ fetch_relevant_docs()  [doc_retrieval.py, unchanged]
        │           → raw_result["data"] contains: keywords, context_docs, sources_used, total_tokens
        ├─→ build_generation_prompt()  → prompt string (unchanged)
        ├─→ LLM call                   → raw code
        ├─→ validate_skill_code()      → AST checks (unchanged)
        └─→ _write_generation_log()    ← NEW
              uses: get_backend() (sync skills storage backend)
              fields populated from:
                - triggered_by: passed-in parameter
                - keywords: raw_result["data"]["keywords"]
                - docs_retrieved: raw_result["data"]["context_docs"]
                  (only {concept, doc_type, tags, tokens} per entry, content stripped)
                - total_tokens: raw_result["data"]["total_tokens"]
                - sources_used: raw_result["data"]["sources_used"]
                - spec_used, spec_warnings: from spec_generator result
                - outcome: "success" | "error" | "export"
                - error_message: exception message if outcome == "error"
```

## API Endpoints

Two new read-only endpoints in `api/routers/skills.py` (not `tools.py`). All existing endpoints in `skills.py` are sync `def` — these must be too (project rule: no async). Both require `Depends(get_current_user)` (same as every other endpoint in that router). Return format matches existing `skills.py` pattern: plain dicts, not `_ok()`/`_err()` wrapped.

```python
def get_generation_log(
    skill_name: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
    current_user = Depends(get_current_user)
) -> list[dict]:
    # GET /api/skills/generation-log
    # Filtered SELECT from skill_generation_log, ORDER BY created_at DESC

def get_skill_generation_log(
    name: str,
    current_user = Depends(get_current_user)
) -> list[dict]:
    # GET /api/skills/{name}/generation-log
    # SELECT WHERE skill_name = name, ORDER BY created_at DESC
```

## GUI: Docs Tab

New tab in main navigation alongside Commands / Skills / Agent.

On mount, two parallel fetches:
- `GET /api/skills/generation-log` (new endpoint above) → generation log data
- `GET /api/memory/docs` (existing endpoint in `api/routers/memory.py`) → doc list

**Top half — Doc Coverage:**
- One row per service in `service_catalog`
- Columns: Service, Doc Count, Last Ingested, Coverage Status
- "No docs" warning badge: `api_docs_ingested == false/null`
- Clicking a row navigates to Ingest panel

**Bottom half — Generation Log:**
- Paginated table: Skill Name, Triggered By, Backend, Outcome, Tokens, Created At
- Expandable row: keywords, per-doc breakdown (concept, type, tags, tokens), spec used, warnings, error message
- Warning badge on rows where `total_tokens == 0` ("Generated without doc context")
- Filter by skill name and outcome

## Error Handling

**Log write fails** — `_write_generation_log()` wrapped in `try/except`, logs a warning. Generation result returned unchanged.

**MuninnDB unreachable** — already handled by `doc_retrieval.py` fallback chain (service_catalog → local files → empty context). Now visible via `sources_used` field: absence of `"muninndb"` means MuninnDB was not reachable.

**Zero docs retrieved** — not an error. Log row shows `docs_retrieved: []`, `total_tokens: 0`. GUI highlights with "Generated without doc context" badge. Primary actionable signal for knowing which skills to regenerate after ingesting docs for their service.

**`_fetch_relevant_docs()` fails entirely** — catch exception, log it, call `_write_generation_log()` with `docs_retrieved: []`, `sources_used: []`, `outcome: "error"`. Still write the log row.

**GUI fetch fails** — coverage section and log section fail independently with inline error states. No full-page crash.

## Testing

### `tests/test_doc_retrieval.py` (~10 tests, MuninnDB mocked)
- `extract_keywords()` correctly parses service names, tech terms, endpoints
- `_classify_doc_type()` assigns correct priority (api_reference > changelog > tutorial)
- `_budget_content()` respects token limits, truncates at paragraph/sentence boundaries
- Fallback: empty MuninnDB result → service_catalog path used (`"service_catalog"` in `sources_used`)
- Fallback: MuninnDB raises → local files path used (`"local_files"` in `sources_used`)

### `tests/test_prompt_builder.py` (~5 tests)
- Prompt contains doc content when `context_docs` is non-empty
- Prompt contains hard constraints section
- Auth pattern injected for known services
- Empty `context_docs` produces valid prompt without crash

### `tests/test_generation_log.py` (~10 tests, in-memory SQLite via `get_backend()`)
- Successful generation writes one row with `outcome="success"`
- `docs_retrieved` entries contain only `{concept, doc_type, tags, tokens}` — no `content` field (stripped at log-write time to avoid bloat)
- `total_tokens` matches sum of per-doc token counts in `docs_retrieved`
- Failed generation writes row with `outcome="error"` and non-empty `error_message`
- Log write failure does not raise or block generation result
- `GET /api/skills/generation-log` returns rows in descending `created_at` order
- `GET /api/skills/generation-log?skill_name=x` filters correctly
- `GET /api/skills/generation-log?outcome=error` filters correctly
- `GET /api/skills/{name}/generation-log` returns only rows for that skill
- Both endpoints return 401 when called without auth token

### `tests/test_docs_coverage.py` (~5 tests)
- `GET /api/memory/docs` returns list of ingested docs
- Services with `api_docs_ingested=False` in service_catalog are identified as "no docs"
- Services with `api_docs_ingested=True` are identified as "has docs"
- Coverage query handles empty service_catalog gracefully
- Coverage query handles missing `data/docs/` directory gracefully (no crash)

**Total: ~30 new tests across 4 files**

## Files Touched

| File | Change |
|------|--------|
| `api/db/models.py` | Add `SkillGenerationLog` SQLAlchemy model |
| `api/db/migrations.py` | Add new migration entry for `skill_generation_log` table |
| `mcp_server/tools/skills/generator.py` | Refactor `_fetch_relevant_docs()` wrapper; add `triggered_by` param to `generate_skill()`; add `_write_generation_log()` using `get_backend()` |
| `api/routers/skills.py` | Add two read-only generation-log endpoints (sync `def`, `Depends(get_current_user)`) |
| `gui/src/components/DocsTab.jsx` | New component: coverage + log sections |
| `gui/src/App.jsx` (or main nav component) | Add "Docs" tab entry |
| `tests/test_doc_retrieval.py` | New test file |
| `tests/test_prompt_builder.py` | New test file |
| `tests/test_generation_log.py` | New test file |
| `tests/test_docs_coverage.py` | New test file |

## Out of Scope

- Changes to `doc_retrieval.py`, `prompt_builder.py`, `spec_generator.py` internals
- Retroactive log population for previously generated skills
- Real-time streaming of generation trace to GUI
- MuninnDB health monitoring (separate concern)
- `docs_manifest.json` — not used; coverage comes from `service_catalog.api_docs_ingested` field and `GET /api/memory/docs`
