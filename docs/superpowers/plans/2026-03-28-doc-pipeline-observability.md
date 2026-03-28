# Doc Pipeline Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `skill_generation_log` table, two read-only API endpoints, and a Docs GUI tab so the doc→skill pipeline is fully observable.

**Architecture:** The generation log lives in `skills.db` (the sync skills storage backend), written by `generator.py` after every `generate_skill()` call. Two new read-only endpoints in `api/routers/skills.py` expose it. A new `DocsTab.jsx` GUI component shows doc coverage and the generation trace.

**Tech Stack:** Python 3.13, SQLite (sqlite3), psycopg2 (Postgres), FastAPI, React/JSX, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-doc-pipeline-observability-design.md`

---

## File Map

| File | Change |
|------|--------|
| `mcp_server/tools/skills/storage/interface.py` | Add `write_generation_log` + `get_generation_log` abstract methods |
| `mcp_server/tools/skills/storage/sqlite_backend.py` | Add `skill_generation_log` table to `init()`, implement both methods |
| `mcp_server/tools/skills/storage/postgres_backend.py` | Add `skill_generation_log` table to `init()`, implement both methods |
| `mcp_server/tools/skills/generator.py` | Refactor `_fetch_relevant_docs()` return type; add `triggered_by` param + `_write_generation_log()` to `generate_skill()` |
| `mcp_server/tools/skills/meta_tools.py` | Thread `triggered_by` through `skill_create()` and `skill_regenerate()` |
| `api/routers/skills.py` | Add `GET /generation-log` and `GET /{name}/generation-log` before `GET /{skill_name}` |
| `gui/src/components/DocsTab.jsx` | New component: doc coverage + generation log |
| `gui/src/App.jsx` | Import `DocsTab`, add `'Docs'` to `TOOLS_TABS`, add render case |
| `tests/test_generation_log.py` | New: storage + API + generator integration tests |
| `tests/test_doc_retrieval.py` | New: unit tests for `extract_keywords`, retrieval fallbacks |
| `tests/test_prompt_builder.py` | New: unit tests for prompt structure |
| `tests/test_docs_coverage.py` | New: API endpoint tests for doc coverage |

---

## Task 1: Storage Layer — skill_generation_log table

**Files:**
- Modify: `mcp_server/tools/skills/storage/interface.py`
- Modify: `mcp_server/tools/skills/storage/sqlite_backend.py`
- Modify: `mcp_server/tools/skills/storage/postgres_backend.py`
- Create: `tests/test_generation_log.py` (storage tests only for now)

- [ ] **Step 1: Write the failing storage tests**

Create `tests/test_generation_log.py`:

```python
"""Tests for skill_generation_log storage, API endpoints, and generator integration."""
import json
import time
import uuid
import pytest
from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend


@pytest.fixture
def backend(tmp_path):
    b = SqliteBackend(db_path=str(tmp_path / "test_skills.db"))
    b.init()
    return b


def _sample_row(**overrides) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "skill_name": "fortigate_system_status",
        "triggered_by": "skill_create",
        "backend": "local",
        "description": "FortiGate system status",
        "category": "networking",
        "api_base": "https://fg1.local",
        "keywords": json.dumps({"services": ["fortigate"], "tech": ["api"]}),
        "docs_retrieved": json.dumps([{"concept": "fg_api", "doc_type": "api_reference", "tags": ["api"], "tokens": 300}]),
        "total_tokens": 300,
        "sources_used": json.dumps(["muninndb"]),
        "spec_used": 1,
        "spec_warnings": json.dumps([]),
        "outcome": "success",
        "error_message": "",
        "created_at": time.time(),
    }
    row.update(overrides)
    return row


def test_write_and_retrieve_log_row(backend):
    row = _sample_row()
    backend.write_generation_log(row)
    rows = backend.get_generation_log()
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "fortigate_system_status"
    assert rows[0]["outcome"] == "success"


def test_get_generation_log_parses_json_fields(backend):
    backend.write_generation_log(_sample_row())
    rows = backend.get_generation_log()
    assert isinstance(rows[0]["keywords"], dict)
    assert isinstance(rows[0]["docs_retrieved"], list)
    assert isinstance(rows[0]["sources_used"], list)
    assert isinstance(rows[0]["spec_warnings"], list)


def test_get_generation_log_filter_by_skill_name(backend):
    backend.write_generation_log(_sample_row(skill_name="skill_a"))
    backend.write_generation_log(_sample_row(skill_name="skill_b"))
    rows = backend.get_generation_log(skill_name="skill_a")
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "skill_a"


def test_get_generation_log_filter_by_outcome(backend):
    backend.write_generation_log(_sample_row(outcome="success"))
    backend.write_generation_log(_sample_row(outcome="error", error_message="LLM timeout"))
    rows = backend.get_generation_log(outcome="error")
    assert len(rows) == 1
    assert rows[0]["error_message"] == "LLM timeout"


def test_get_generation_log_descending_order(backend):
    backend.write_generation_log(_sample_row(created_at=time.time() - 100))
    backend.write_generation_log(_sample_row(created_at=time.time()))
    rows = backend.get_generation_log()
    assert rows[0]["created_at"] > rows[1]["created_at"]


def test_get_generation_log_limit(backend):
    for _ in range(10):
        backend.write_generation_log(_sample_row())
    rows = backend.get_generation_log(limit=3)
    assert len(rows) == 3


def test_zero_docs_retrieved_stored_correctly(backend):
    row = _sample_row(docs_retrieved=json.dumps([]), total_tokens=0, sources_used=json.dumps([]))
    backend.write_generation_log(row)
    rows = backend.get_generation_log()
    assert rows[0]["total_tokens"] == 0
    assert rows[0]["docs_retrieved"] == []
    assert rows[0]["sources_used"] == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_generation_log.py -v 2>&1 | head -30
```
Expected: `AttributeError: 'SqliteBackend' object has no attribute 'write_generation_log'`

- [ ] **Step 3: Add abstract methods to interface.py**

In `mcp_server/tools/skills/storage/interface.py`, append to the end of the class (after the `# ── Settings` section):

```python
    # ── Generation Log ───────────────────────────────────────────────────────

    @abstractmethod
    def write_generation_log(self, row: dict) -> None:
        """Write one generation trace row. row must have all skill_generation_log columns."""

    @abstractmethod
    def get_generation_log(self, skill_name: str = "", outcome: str = "", limit: int = 50) -> list[dict]:
        """Return log rows, JSON fields pre-parsed to dicts/lists. Ordered by created_at DESC."""
```

- [ ] **Step 4: Add table + methods to sqlite_backend.py**

In `mcp_server/tools/skills/storage/sqlite_backend.py`, in `init()` — add to the end of the `executescript` block, just before the final `""")`:

```sql
            CREATE TABLE IF NOT EXISTS skill_generation_log (
                id              TEXT PRIMARY KEY,
                skill_name      TEXT NOT NULL,
                triggered_by    TEXT DEFAULT '',
                backend         TEXT DEFAULT '',
                description     TEXT DEFAULT '',
                category        TEXT DEFAULT '',
                api_base        TEXT DEFAULT '',
                keywords        TEXT DEFAULT '{}',
                docs_retrieved  TEXT DEFAULT '[]',
                total_tokens    INTEGER DEFAULT 0,
                sources_used    TEXT DEFAULT '[]',
                spec_used       INTEGER DEFAULT 0,
                spec_warnings   TEXT DEFAULT '[]',
                outcome         TEXT NOT NULL,
                error_message   TEXT DEFAULT '',
                created_at      REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_genlog_skill    ON skill_generation_log(skill_name);
            CREATE INDEX IF NOT EXISTS idx_genlog_outcome  ON skill_generation_log(outcome);
            CREATE INDEX IF NOT EXISTS idx_genlog_ts       ON skill_generation_log(created_at);
```

Then add the two methods to `SqliteBackend` after `health_check()`:

```python
    # ── Generation Log ───────────────────────────────────────────────────────

    def write_generation_log(self, row: dict) -> None:
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO skill_generation_log (
                id, skill_name, triggered_by, backend, description, category,
                api_base, keywords, docs_retrieved, total_tokens, sources_used,
                spec_used, spec_warnings, outcome, error_message, created_at
            ) VALUES (
                :id, :skill_name, :triggered_by, :backend, :description, :category,
                :api_base, :keywords, :docs_retrieved, :total_tokens, :sources_used,
                :spec_used, :spec_warnings, :outcome, :error_message, :created_at
            )
        """, row)
        conn.commit()

    def get_generation_log(self, skill_name: str = "", outcome: str = "", limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        sql = "SELECT * FROM skill_generation_log WHERE 1=1"
        params: list = []
        if skill_name:
            sql += " AND skill_name = ?"
            params.append(skill_name)
        if outcome:
            sql += " AND outcome = ?"
            params.append(outcome)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(limit, 200))
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("keywords", "docs_retrieved", "sources_used", "spec_warnings"):
                empty = "{}" if field == "keywords" else "[]"
                try:
                    d[field] = json.loads(d.get(field) or empty)
                except Exception:
                    d[field] = json.loads(empty)
            result.append(d)
        return result
```

- [ ] **Step 5: Add table + methods to postgres_backend.py**

In `mcp_server/tools/skills/storage/postgres_backend.py`, in `init()` — append to the CREATE TABLE block:

```sql
            CREATE TABLE IF NOT EXISTS skill_generation_log (
                id              TEXT PRIMARY KEY,
                skill_name      TEXT NOT NULL,
                triggered_by    TEXT DEFAULT '',
                backend         TEXT DEFAULT '',
                description     TEXT DEFAULT '',
                category        TEXT DEFAULT '',
                api_base        TEXT DEFAULT '',
                keywords        JSONB DEFAULT '{}',
                docs_retrieved  JSONB DEFAULT '[]',
                total_tokens    INTEGER DEFAULT 0,
                sources_used    JSONB DEFAULT '[]',
                spec_used       BOOLEAN DEFAULT FALSE,
                spec_warnings   JSONB DEFAULT '[]',
                outcome         TEXT NOT NULL,
                error_message   TEXT DEFAULT '',
                created_at      DOUBLE PRECISION NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_genlog_skill    ON skill_generation_log(skill_name);
            CREATE INDEX IF NOT EXISTS idx_genlog_outcome  ON skill_generation_log(outcome);
            CREATE INDEX IF NOT EXISTS idx_genlog_ts       ON skill_generation_log(created_at);
```

Add the two methods to `PostgresBackend`. Use positional `%s` placeholders — psycopg2's `_execute` takes a `params: tuple`:

```python
    def write_generation_log(self, row: dict) -> None:
        # Parse JSON strings to Python objects for JSONB columns
        pg_row = dict(row)
        for field in ("keywords", "docs_retrieved", "sources_used", "spec_warnings"):
            v = pg_row.get(field)
            if isinstance(v, str):
                try:
                    pg_row[field] = json.loads(v)
                except Exception:
                    pg_row[field] = {} if field == "keywords" else []
        self._execute("""
            INSERT INTO skill_generation_log (
                id, skill_name, triggered_by, backend, description, category,
                api_base, keywords, docs_retrieved, total_tokens, sources_used,
                spec_used, spec_warnings, outcome, error_message, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            pg_row["id"], pg_row["skill_name"], pg_row["triggered_by"], pg_row["backend"],
            pg_row["description"], pg_row["category"], pg_row["api_base"],
            json.dumps(pg_row["keywords"]), json.dumps(pg_row["docs_retrieved"]),
            pg_row["total_tokens"], json.dumps(pg_row["sources_used"]),
            bool(pg_row["spec_used"]), json.dumps(pg_row["spec_warnings"]),
            pg_row["outcome"], pg_row["error_message"], pg_row["created_at"],
        ))

    def get_generation_log(self, skill_name: str = "", outcome: str = "", limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM skill_generation_log WHERE TRUE"
        params: list = []
        if skill_name:
            sql += " AND skill_name = %s"
            params.append(skill_name)
        if outcome:
            sql += " AND outcome = %s"
            params.append(outcome)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(min(limit, 200))
        rows = self._execute(sql, tuple(params), fetch="all") or []
        return [self._row(r) for r in rows]
```

**Note on Postgres JSONB:** psycopg2 does not auto-serialize Python dicts to JSONB. Pass them as `json.dumps(...)` strings and psycopg2 will handle the cast.

- [ ] **Step 6: Verify syntax**

```bash
python -m py_compile mcp_server/tools/skills/storage/interface.py
python -m py_compile mcp_server/tools/skills/storage/sqlite_backend.py
python -m py_compile mcp_server/tools/skills/storage/postgres_backend.py
```
Expected: no output.

- [ ] **Step 7: Run storage tests**

```bash
python -m pytest tests/test_generation_log.py -v 2>&1 | head -40
```
Expected: all 7 tests pass.

- [ ] **Step 8: Commit**

```bash
git add mcp_server/tools/skills/storage/interface.py \
        mcp_server/tools/skills/storage/sqlite_backend.py \
        mcp_server/tools/skills/storage/postgres_backend.py \
        tests/test_generation_log.py
git commit -m "feat(storage): add skill_generation_log table and read/write methods"
```

---

## Task 2: generator.py — retrieval data exposure + log writing

**Files:**
- Modify: `mcp_server/tools/skills/generator.py`
- Modify: `tests/test_generation_log.py` (add generator integration tests)

- [ ] **Step 1: Add generator integration tests to test_generation_log.py**

Append to `tests/test_generation_log.py`:

```python
# ── Generator integration tests ────────────────────────────────────────────────

from unittest.mock import patch, MagicMock
import importlib


def _make_fake_code(name="test_skill"):
    return f'''
SKILL_META = {{"name": "{name}", "description": "test", "category": "general",
              "parameters": {{}}, "compat": {{}}}}
def execute(**kwargs):
    return {{"status": "ok", "data": {{}}, "timestamp": "t", "message": "ok"}}
'''


def test_generate_skill_writes_success_log(tmp_path):
    """After a successful generate_skill(), one 'success' row appears in the log."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend

    test_db = str(tmp_path / "gen_test.db")
    test_backend = SqliteBackend(db_path=test_db)
    test_backend.init()

    with patch("mcp_server.tools.skills.storage.get_backend", return_value=test_backend), \
         patch("mcp_server.tools.skills.generator._generate_local", return_value=_make_fake_code()), \
         patch("mcp_server.tools.skills.generator._fetch_relevant_docs",
               return_value=([], {"keywords": {}, "context_docs": [], "sources_used": [], "total_tokens": 0})):
        import mcp_server.tools.skills.generator as gen
        importlib.reload(gen)
        result = gen.generate_skill("test skill", category="general", skip_spec=True)

    assert result["status"] == "ok"
    rows = test_backend.get_generation_log()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    assert rows[0]["triggered_by"] == "skill_create"


def test_generate_skill_writes_error_log_on_llm_failure(tmp_path):
    """When LLM call raises, an 'error' row is still written to the log."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend

    test_db = str(tmp_path / "gen_err_test.db")
    test_backend = SqliteBackend(db_path=test_db)
    test_backend.init()

    with patch("mcp_server.tools.skills.storage.get_backend", return_value=test_backend), \
         patch("mcp_server.tools.skills.generator._generate_local", side_effect=RuntimeError("LLM timeout")), \
         patch("mcp_server.tools.skills.generator._fetch_relevant_docs",
               return_value=([], {"keywords": {}, "context_docs": [], "sources_used": [], "total_tokens": 0})):
        import mcp_server.tools.skills.generator as gen
        importlib.reload(gen)
        result = gen.generate_skill("test skill", category="general", skip_spec=True)

    assert result["status"] == "error"
    rows = test_backend.get_generation_log()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "error"
    assert "LLM timeout" in rows[0]["error_message"]


def test_generate_skill_writes_error_log_on_validation_failure(tmp_path):
    """When generated code fails AST validation, an 'error' row is written."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend

    test_db = str(tmp_path / "val_err_test.db")
    test_backend = SqliteBackend(db_path=test_db)
    test_backend.init()

    bad_code = "import subprocess\nSKILL_META = {}\ndef execute(**kwargs): pass"

    with patch("mcp_server.tools.skills.storage.get_backend", return_value=test_backend), \
         patch("mcp_server.tools.skills.generator._generate_local", return_value=bad_code), \
         patch("mcp_server.tools.skills.generator._fetch_relevant_docs",
               return_value=([], {})):
        import mcp_server.tools.skills.generator as gen
        importlib.reload(gen)
        result = gen.generate_skill("test skill", category="general", skip_spec=True)

    assert result["status"] == "error"
    rows = test_backend.get_generation_log()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "error"


def test_log_write_failure_does_not_block_generation(tmp_path):
    """If write_generation_log raises, generate_skill still returns its result."""
    broken_backend = MagicMock()
    broken_backend.write_generation_log.side_effect = Exception("DB exploded")

    with patch("mcp_server.tools.skills.storage.get_backend", return_value=broken_backend), \
         patch("mcp_server.tools.skills.generator._generate_local", return_value=_make_fake_code()), \
         patch("mcp_server.tools.skills.generator._fetch_relevant_docs",
               return_value=([], {})):
        import mcp_server.tools.skills.generator as gen
        importlib.reload(gen)
        result = gen.generate_skill("test skill", category="general", skip_spec=True)

    assert result["status"] == "ok"


def test_triggered_by_regenerate_is_recorded(tmp_path):
    """triggered_by='skill_regenerate' is stored when passed explicitly."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend

    test_db = str(tmp_path / "regen_test.db")
    test_backend = SqliteBackend(db_path=test_db)
    test_backend.init()

    with patch("mcp_server.tools.skills.storage.get_backend", return_value=test_backend), \
         patch("mcp_server.tools.skills.generator._generate_local", return_value=_make_fake_code()), \
         patch("mcp_server.tools.skills.generator._fetch_relevant_docs",
               return_value=([], {})):
        import mcp_server.tools.skills.generator as gen
        importlib.reload(gen)
        gen.generate_skill("test skill", triggered_by="skill_regenerate", skip_spec=True)

    rows = test_backend.get_generation_log()
    assert rows[0]["triggered_by"] == "skill_regenerate"
```

**Note on patch target:** The correct target for `get_backend` is `mcp_server.tools.skills.storage.get_backend` — this is where `_write_generation_log()` imports it from. Do NOT patch `mcp_server.tools.skills.storage.auto_detect.get_backend`.

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
python -m pytest tests/test_generation_log.py::test_generate_skill_writes_success_log -v 2>&1 | head -20
```
Expected: `TypeError: generate_skill() got an unexpected keyword argument 'triggered_by'`

- [ ] **Step 3: Refactor `_fetch_relevant_docs` in generator.py**

Replace the current `_fetch_relevant_docs` function (lines 76–88) with:

```python
def _fetch_relevant_docs(
    description: str, category: str = "general", api_base: str = ""
) -> tuple[list, dict]:
    """
    Fetch documentation context for skill generation.

    Returns:
        (context_docs_list, raw_retrieval_data)
        context_docs_list: list[str] for build_generation_prompt(context_docs=)
        raw_retrieval_data: dict with keys: keywords, context_docs, sources_used,
                            total_tokens. Empty dict on failure.
    """
    try:
        result = fetch_relevant_docs(description, category=category, api_base=api_base, token_budget=3000)
        formatted = format_docs_for_prompt(result)
        raw = result.get("data", {})
        return ([formatted] if formatted else []), raw
    except Exception as e:
        log.debug("doc_retrieval failed: %s", e)
        return [], {}
```

- [ ] **Step 4: Add `triggered_by` param + `_retrieval_data` capture in `generate_skill()`**

**Edit 1** — add `triggered_by` to the function signature (line 192):

```python
# OLD:
def generate_skill(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    backend: str = "",
    skip_spec: bool = False,
) -> dict:

# NEW:
def generate_skill(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    backend: str = "",
    skip_spec: bool = False,
    triggered_by: str = "skill_create",
) -> dict:
```

**Edit 2** — capture `_retrieval_data` (around line 222):

```python
# OLD:
    # Fetch context docs — must be a list for build_generation_prompt
    if context_docs is None:
        context_docs = _fetch_relevant_docs(description, category=category, api_base=api_base)
    elif isinstance(context_docs, str):
        context_docs = [context_docs] if context_docs else []

# NEW:
    # Fetch context docs — must be a list for build_generation_prompt
    _retrieval_data: dict = {}
    if context_docs is None:
        context_docs, _retrieval_data = _fetch_relevant_docs(description, category=category, api_base=api_base)
    elif isinstance(context_docs, str):
        context_docs = [context_docs] if context_docs else []
```

- [ ] **Step 5: Add `_write_generation_log()` helper to generator.py**

Add this function after `_generate_export()` (around line 190), before `generate_skill()`:

```python
def _write_generation_log(
    skill_name: str,
    triggered_by: str,
    backend: str,
    description: str,
    category: str,
    api_base: str,
    retrieval_data: dict,
    spec_used: bool,
    spec_warnings: list,
    outcome: str,
    error_message: str = "",
) -> None:
    """Write one generation trace row to skill_generation_log. Failures are swallowed."""
    try:
        import uuid as _uuid
        import time as _time
        from mcp_server.tools.skills.storage import get_backend

        context_docs = retrieval_data.get("context_docs", [])
        # Strip content field — keep only metadata to avoid blob storage
        docs_for_log = [
            {k: v for k, v in d.items() if k != "content"}
            for d in context_docs
        ]

        row = {
            "id": str(_uuid.uuid4()),
            "skill_name": skill_name or "unknown",
            "triggered_by": triggered_by,
            "backend": backend,
            "description": description,
            "category": category,
            "api_base": api_base or "",
            "keywords": json.dumps(retrieval_data.get("keywords", {})),
            "docs_retrieved": json.dumps(docs_for_log),
            "total_tokens": retrieval_data.get("total_tokens", 0),
            "sources_used": json.dumps(retrieval_data.get("sources_used", [])),
            "spec_used": 1 if spec_used else 0,
            "spec_warnings": json.dumps(spec_warnings),
            "outcome": outcome,
            "error_message": error_message,
            "created_at": _time.time(),
        }
        get_backend().write_generation_log(row)
    except Exception as _e:
        log.warning("Failed to write generation log: %s", _e)
```

- [ ] **Step 6: Add `_write_generation_log()` calls at all exit paths of `generate_skill()`**

There are four exit paths to cover. Add log calls as follows:

**Path 1 — spec validation failure** (around line 248–258). Before the `return _err(...)`:

```python
                _write_generation_log(
                    skill_name="unknown", triggered_by=triggered_by, backend=backend,
                    description=description, category=category, api_base=api_base,
                    retrieval_data=_retrieval_data, spec_used=False, spec_warnings=[],
                    outcome="error",
                    error_message=f"Spec validation failed: {probe_data.get('errors', [])}",
                )
                return _err(...)  # keep the existing _err() call unchanged
```

**Path 2 — export path** (line 264–274). Replace `return _generate_export(doc, description)` with:

```python
        export_result = _generate_export(doc, description)
        _write_generation_log(
            skill_name="export", triggered_by=triggered_by, backend="export",
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="export",
        )
        return export_result
```

**Path 3 — LLM call failure** (the `except Exception` block around line 294). Replace:

```python
    except Exception as e:
        return _err(f"Generation failed ({backend}): {e}")
```
with:
```python
    except Exception as e:
        _write_generation_log(
            skill_name="unknown", triggered_by=triggered_by, backend=backend,
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="error",
            error_message=f"Generation failed ({backend}): {e}",
        )
        return _err(f"Generation failed ({backend}): {e}")
```

**Path 4 — AST validation failure** (around line 299–300). Replace:

```python
    if not result["valid"]:
        return _err(f"Generated code failed validation: {result['error']}", data={"code": code})
```
with:
```python
    if not result["valid"]:
        _write_generation_log(
            skill_name="unknown", triggered_by=triggered_by, backend=backend_used,
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="error",
            error_message=f"Generated code failed validation: {result['error']}",
        )
        return _err(f"Generated code failed validation: {result['error']}", data={"code": code})
```

**Path 5 — success** (the final `return _ok(...)` block). Add before it:

```python
    _write_generation_log(
        skill_name=result["name"], triggered_by=triggered_by, backend=backend_used,
        description=description, category=category, api_base=api_base,
        retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
        spec_warnings=spec_warnings, outcome="success",
    )
    return _ok({...})  # keep the existing _ok() call unchanged
```

- [ ] **Step 7: Verify syntax**

```bash
python -m py_compile mcp_server/tools/skills/generator.py
```
Expected: no output.

- [ ] **Step 8: Run all generation log tests**

```bash
python -m pytest tests/test_generation_log.py -v 2>&1 | head -50
```
Expected: all tests pass (storage + generator integration).

- [ ] **Step 9: Commit**

```bash
git add mcp_server/tools/skills/generator.py tests/test_generation_log.py
git commit -m "feat(generator): expose retrieval data and write generation log on every generate_skill() call"
```

---

## Task 3: meta_tools.py — thread triggered_by

**Files:**
- Modify: `mcp_server/tools/skills/meta_tools.py`

- [ ] **Step 1: Add `triggered_by` to `skill_create()`**

`skill_create()` is at line 45. Add the new parameter and pass it through:

```python
# OLD signature:
def skill_create(
    mcp_server,
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:

# NEW signature:
def skill_create(
    mcp_server,
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
    triggered_by: str = "skill_create",
) -> dict:
```

Update the `generator.generate_skill()` call at line 54:

```python
# OLD:
    result = generator.generate_skill(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        backend=backend,
    )

# NEW:
    result = generator.generate_skill(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        backend=backend,
        triggered_by=triggered_by,
    )
```

- [ ] **Step 2: Update `skill_regenerate()` to pass triggered_by**

`skill_regenerate()` calls `skill_create()` at line 327:

```python
# OLD:
    result = skill_create(mcp_server, description, category, "", auth_type, backend)

# NEW:
    result = skill_create(mcp_server, description, category, "", auth_type, backend,
                          triggered_by="skill_regenerate")
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile mcp_server/tools/skills/meta_tools.py
```

- [ ] **Step 4: Commit**

```bash
git add mcp_server/tools/skills/meta_tools.py
git commit -m "feat(meta_tools): pass triggered_by through skill_create and skill_regenerate"
```

---

## Task 4: API endpoints in skills.py

**Files:**
- Modify: `api/routers/skills.py`
- Modify: `tests/test_generation_log.py` (add API tests)

- [ ] **Step 1: Add API tests to test_generation_log.py**

Append to `tests/test_generation_log.py`:

```python
# ── API endpoint tests ──────────────────────────────────────────────────────────

from fastapi.testclient import TestClient
from api.main import app

_client = TestClient(app)
_AUTH_CACHE: dict = {}


def _auth_headers() -> dict:
    if "admin" not in _AUTH_CACHE:
        r = _client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
        if r.status_code != 200:
            pytest.skip("Auth not available")
        _AUTH_CACHE["admin"] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _AUTH_CACHE["admin"]


def test_generation_log_endpoint_returns_list():
    r = _client.get("/api/skills/generation-log", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "log" in data
    assert "count" in data
    assert isinstance(data["log"], list)


def test_generation_log_endpoint_requires_auth():
    r = _client.get("/api/skills/generation-log")
    assert r.status_code == 401


def test_skill_generation_log_endpoint_filters_by_name():
    r = _client.get("/api/skills/proxmox_vm_status/generation-log", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "log" in data
    for row in data["log"]:
        assert row["skill_name"] == "proxmox_vm_status"


def test_generation_log_not_matched_as_skill_name():
    """GET /api/skills/generation-log must not be routed to GET /api/skills/{skill_name}."""
    r = _client.get("/api/skills/generation-log", headers=_auth_headers())
    # Would return {"skills": ...} if wrongly matched as skill_info("generation-log")
    assert "log" in r.json()
    assert "skills" not in r.json()
```

- [ ] **Step 2: Run new API tests to confirm they fail**

```bash
python -m pytest tests/test_generation_log.py::test_generation_log_endpoint_returns_list -v 2>&1 | head -20
```
Expected: `AssertionError` on status code (likely 404).

- [ ] **Step 3: Add import + endpoints to skills.py**

Add to the imports at the top of `api/routers/skills.py`:

```python
from mcp_server.tools.skills.storage import get_backend
```

Insert the two new endpoints **immediately before** `@router.get("/{skill_name}")` (currently at line 56). The final order in the file must be:

1. `GET ""` (existing list endpoint)
2. `POST /{skill_name}/execute` (existing)
3. `GET /generation-log` ← NEW, must be here
4. `GET /{skill_name}/generation-log` ← NEW, must be here
5. `GET /{skill_name}` ← existing, must stay after both new routes

```python
@router.get("/generation-log")
def list_generation_log(
    skill_name: str = Query("", description="Filter by skill name"),
    outcome: str = Query("", description="Filter by outcome: success | error | export"),
    limit: int = Query(50, ge=1, le=200, description="Max rows to return"),
    _: str = Depends(get_current_user),
):
    """Return skill generation trace log, newest first."""
    try:
        rows = get_backend().get_generation_log(skill_name=skill_name, outcome=outcome, limit=limit)
        return {"log": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{skill_name}/generation-log")
def get_skill_generation_log(
    skill_name: str,
    _: str = Depends(get_current_user),
):
    """Return generation trace log for a specific skill, newest first."""
    try:
        rows = get_backend().get_generation_log(skill_name=skill_name, limit=50)
        return {"log": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))
```

- [ ] **Step 4: Verify syntax**

```bash
python -m py_compile api/routers/skills.py
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_generation_log.py -v 2>&1 | head -60
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/routers/skills.py tests/test_generation_log.py
git commit -m "feat(api): add GET /api/skills/generation-log and /api/skills/{name}/generation-log"
```

---

## Task 5: Unit tests for doc_retrieval and prompt_builder

**Files:**
- Create: `tests/test_doc_retrieval.py`
- Create: `tests/test_prompt_builder.py`
- Create: `tests/test_docs_coverage.py`

- [ ] **Step 1: Write test_doc_retrieval.py**

Create `tests/test_doc_retrieval.py`:

```python
"""Unit tests for doc_retrieval.py — keyword extraction and retrieval fallbacks."""
import pytest
from unittest.mock import patch
from mcp_server.tools.skills.doc_retrieval import extract_keywords, fetch_relevant_docs


def test_extract_keywords_finds_known_service():
    result = extract_keywords("fortigate system status health check")
    assert "fortigate" in result["services"]


def test_extract_keywords_finds_tech_terms():
    result = extract_keywords("check fortigate via rest api over https")
    assert "api" in result["tech"] or "rest" in result["tech"]


def test_extract_keywords_extracts_api_path():
    result = extract_keywords("poll /api/v2/monitor/system/status endpoint")
    assert any("/api/" in ep for ep in result["endpoints"])


def test_extract_keywords_extracts_version():
    result = extract_keywords("fortigate 7.4 health monitoring")
    assert "7.4" in result["versions"]


def test_extract_keywords_unknown_service_ignored():
    result = extract_keywords("completely unknown product health check")
    assert result["services"] == []


def test_extract_keywords_multiple_services():
    result = extract_keywords("fortigate and proxmox integration health")
    assert "fortigate" in result["services"]
    assert "proxmox" in result["services"]


def test_fetch_relevant_docs_no_muninndb_engrams_uses_service_catalog():
    """When MuninnDB returns no engrams, muninndb is absent from sources_used."""
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=[]):
        result = fetch_relevant_docs("fortigate system status", category="networking")
    assert result["status"] == "ok"
    assert "muninndb" not in result["data"]["sources_used"]


def test_fetch_relevant_docs_returns_ok_on_full_failure():
    """When everything fails, status is still ok with empty context_docs."""
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi",
               side_effect=Exception("conn refused")), \
         patch("mcp_server.tools.skills.doc_retrieval._scan_local_docs", return_value=[]):
        result = fetch_relevant_docs("fortigate system status")
    assert result["status"] == "ok"
    assert result["data"]["context_docs"] == []
    assert result["data"]["total_tokens"] == 0


def test_fetch_relevant_docs_total_tokens_matches_sum():
    """total_tokens equals sum of tokens across context_docs."""
    fake_engrams = [
        {"concept": "fg_api", "content": "x" * 200, "tags": [], "_type_priority": 1,
         "_doc_type": "api_reference", "_activation": 0.9},
    ]
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=fake_engrams):
        result = fetch_relevant_docs("fortigate api status")
    data = result["data"]
    expected_total = sum(d["tokens"] for d in data["context_docs"])
    assert data["total_tokens"] == expected_total


def test_fetch_relevant_docs_muninndb_in_sources_when_engrams_returned():
    fake_engrams = [
        {"concept": "fg_api", "content": "FortiGate REST API reference content",
         "tags": [], "_type_priority": 1, "_doc_type": "api_reference", "_activation": 0.8},
    ]
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=fake_engrams):
        result = fetch_relevant_docs("fortigate health")
    assert "muninndb" in result["data"]["sources_used"]
```

- [ ] **Step 2: Write test_prompt_builder.py**

Create `tests/test_prompt_builder.py`:

```python
"""Unit tests for prompt_builder.py."""
from mcp_server.tools.skills import prompt_builder


def test_build_generation_prompt_contains_description():
    prompt = prompt_builder.build_generation_prompt(
        description="FortiGate system status",
        category="networking",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert "FortiGate system status" in prompt


def test_build_generation_prompt_contains_hard_constraints():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    # Hard constraints block dangerous imports
    lower = prompt.lower()
    assert "subprocess" in lower or "dangerous" in lower or "banned" in lower or "import" in lower


def test_build_generation_prompt_includes_context_docs():
    docs = ["## Reference\n\nSome API documentation here."]
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=docs,
        existing_skills=[],
        spec=None,
    )
    assert "Some API documentation here" in prompt


def test_build_generation_prompt_empty_docs_no_crash():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_build_generation_prompt_existing_skills_mentioned():
    prompt = prompt_builder.build_generation_prompt(
        description="another proxmox skill",
        category="compute",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=["proxmox_vm_status", "proxmox_node_health"],
        spec=None,
    )
    assert "proxmox_vm_status" in prompt or "proxmox_node_health" in prompt
```

- [ ] **Step 3: Write test_docs_coverage.py**

Create `tests/test_docs_coverage.py`:

```python
"""Tests for the doc coverage and generation-log API endpoints."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
_AUTH_CACHE: dict = {}


def auth_headers() -> dict:
    if "admin" not in _AUTH_CACHE:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
        if r.status_code != 200:
            pytest.skip("Auth not available")
        _AUTH_CACHE["admin"] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _AUTH_CACHE["admin"]


def test_ingest_docs_endpoint_returns_list():
    """GET /api/memory/ingest/docs returns {"docs": [...]}."""
    r = client.get("/api/memory/ingest/docs", headers=auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "docs" in data
    assert isinstance(data["docs"], list)


def test_ingest_docs_endpoint_requires_auth():
    r = client.get("/api/memory/ingest/docs")
    assert r.status_code == 401


def test_ingest_docs_entries_have_expected_fields():
    """Each doc entry has source_key, source_label, chunk_count, stored_at."""
    r = client.get("/api/memory/ingest/docs", headers=auth_headers())
    for doc in r.json().get("docs", []):
        assert "source_key" in doc
        assert "chunk_count" in doc


def test_generation_log_outcome_filter():
    """GET /api/skills/generation-log?outcome=success returns only success rows."""
    r = client.get("/api/skills/generation-log?outcome=success", headers=auth_headers())
    assert r.status_code == 200
    for row in r.json().get("log", []):
        assert row["outcome"] == "success"


def test_generation_log_limit_param():
    """limit query param is respected."""
    r = client.get("/api/skills/generation-log?limit=1", headers=auth_headers())
    assert r.status_code == 200
    assert len(r.json().get("log", [])) <= 1
```

- [ ] **Step 4: Run all three test files**

```bash
python -m pytest tests/test_doc_retrieval.py tests/test_prompt_builder.py tests/test_docs_coverage.py -v 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_doc_retrieval.py tests/test_prompt_builder.py tests/test_docs_coverage.py
git commit -m "test: add unit tests for doc_retrieval, prompt_builder, and docs coverage endpoints"
```

---

## Task 6: GUI — DocsTab + App.jsx

**Files:**
- Create: `gui/src/components/DocsTab.jsx`
- Modify: `gui/src/App.jsx`

**Note on endpoint:** The "Ingested Documents" section fetches `GET /api/memory/ingest/docs` (the ingest router, returns `{"docs": [...]}` with user-ingested PDFs/URLs). This is the correct endpoint for user-ingested content. The `/api/memory/docs` endpoint at the memory router returns MuninnDB ingestion status and is a different thing.

- [ ] **Step 1: Create DocsTab.jsx**

Create `gui/src/components/DocsTab.jsx`:

```jsx
import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'

const API = import.meta.env.VITE_API_BASE || ''

function Badge({ children, color = 'gray' }) {
  const colors = {
    gray:   'bg-gray-100 text-gray-600',
    red:    'bg-red-100 text-red-700',
    green:  'bg-green-100 text-green-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    blue:   'bg-blue-100 text-blue-700',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${colors[color] || colors.gray}`}>
      {children}
    </span>
  )
}

function Section({ title, error, children }) {
  return (
    <div className="mb-6">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 px-4">{title}</h3>
      {error
        ? <div className="px-4 text-xs text-red-600">Failed to load: {error}</div>
        : children}
    </div>
  )
}

export default function DocsTab() {
  const { token } = useAuth()
  const [docs,      setDocs]      = useState([])
  const [logRows,   setLogRows]   = useState([])
  const [docsError, setDocsError] = useState(null)
  const [logError,  setLogError]  = useState(null)
  const [expanded,  setExpanded]  = useState(null)
  const [filterSkill,   setFilterSkill]   = useState('')
  const [filterOutcome, setFilterOutcome] = useState('')

  useEffect(() => {
    if (!token) return
    const headers = { Authorization: `Bearer ${token}` }

    // Fetch user-ingested docs (PDFs / URLs via the ingest router)
    fetch(`${API}/api/memory/ingest/docs`, { headers })
      .then(r => r.json())
      .then(d => setDocs(d.docs || []))
      .catch(e => setDocsError(e.message))

    // Fetch generation log
    fetch(`${API}/api/skills/generation-log?limit=100`, { headers })
      .then(r => r.json())
      .then(d => setLogRows(d.log || []))
      .catch(e => setLogError(e.message))
  }, [token])

  const filteredLog = logRows.filter(row => {
    if (filterSkill   && !row.skill_name.includes(filterSkill)) return false
    if (filterOutcome && row.outcome !== filterOutcome)          return false
    return true
  })

  const toggleExpand = (id) => setExpanded(expanded === id ? null : id)

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-white text-sm">
      <div className="px-4 py-3 border-b border-gray-200">
        <span className="font-semibold text-gray-700">Doc Pipeline</span>
        <span className="ml-2 text-xs text-gray-400">Ingested docs and skill generation traces</span>
      </div>

      {/* ── Ingested Documents ───────────────────────────────────────────── */}
      <Section title="Ingested Documents" error={docsError}>
        {docs.length === 0
          ? <div className="px-4 text-xs text-gray-400">No documents ingested yet. Use the Ingest tool to add API docs.</div>
          : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-left px-4 py-1 font-normal">Label</th>
                  <th className="text-left px-4 py-1 font-normal">Chunks</th>
                  <th className="text-left px-4 py-1 font-normal">Stored At</th>
                </tr>
              </thead>
              <tbody>
                {docs.map(d => (
                  <tr key={d.source_key} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-4 py-1.5 font-mono">{d.source_label || d.source_key}</td>
                    <td className="px-4 py-1.5">{d.chunk_count}</td>
                    <td className="px-4 py-1.5 text-gray-400">{d.stored_at ? d.stored_at.slice(0, 10) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Section>

      {/* ── Generation Log ───────────────────────────────────────────────── */}
      <Section title="Generation Log" error={logError}>
        <div className="px-4 mb-2 flex gap-2">
          <input
            value={filterSkill}
            onChange={e => setFilterSkill(e.target.value)}
            placeholder="Filter by skill name…"
            className="text-xs border border-gray-200 rounded px-2 py-1 w-48 focus:outline-none focus:border-blue-400"
          />
          <select
            value={filterOutcome}
            onChange={e => setFilterOutcome(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:border-blue-400"
          >
            <option value="">All outcomes</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="export">export</option>
          </select>
        </div>

        {filteredLog.length === 0
          ? <div className="px-4 text-xs text-gray-400">No generation log entries.</div>
          : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-left px-4 py-1 font-normal">Skill</th>
                  <th className="text-left px-4 py-1 font-normal">Triggered By</th>
                  <th className="text-left px-4 py-1 font-normal">Backend</th>
                  <th className="text-left px-4 py-1 font-normal">Docs</th>
                  <th className="text-left px-4 py-1 font-normal">Tokens</th>
                  <th className="text-left px-4 py-1 font-normal">Outcome</th>
                  <th className="text-left px-4 py-1 font-normal">Date</th>
                </tr>
              </thead>
              <tbody>
                {filteredLog.map(row => (
                  <React.Fragment key={row.id}>
                    <tr
                      className={`border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${expanded === row.id ? 'bg-blue-50' : ''}`}
                      onClick={() => toggleExpand(row.id)}
                    >
                      <td className="px-4 py-1.5 font-mono">{row.skill_name}</td>
                      <td className="px-4 py-1.5 text-gray-500">{row.triggered_by}</td>
                      <td className="px-4 py-1.5 text-gray-500">{row.backend}</td>
                      <td className="px-4 py-1.5">{(row.docs_retrieved || []).length}</td>
                      <td className="px-4 py-1.5">
                        {row.total_tokens === 0
                          ? <Badge color="yellow">0 — no docs</Badge>
                          : row.total_tokens}
                      </td>
                      <td className="px-4 py-1.5">
                        <Badge color={row.outcome === 'success' ? 'green' : row.outcome === 'error' ? 'red' : 'blue'}>
                          {row.outcome}
                        </Badge>
                      </td>
                      <td className="px-4 py-1.5 text-gray-400">
                        {row.created_at ? new Date(row.created_at * 1000).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                    {expanded === row.id && (
                      <tr>
                        <td colSpan={7} className="px-6 py-3 bg-gray-50 text-xs text-gray-700">
                          {row.error_message && (
                            <div className="mb-2 text-red-600"><b>Error:</b> {row.error_message}</div>
                          )}
                          <div className="mb-1"><b>Keywords:</b> {JSON.stringify(row.keywords)}</div>
                          <div className="mb-1"><b>Sources:</b> {(row.sources_used || []).join(', ') || 'none'}</div>
                          <div className="mb-1"><b>Spec used:</b> {row.spec_used ? 'yes' : 'no'}</div>
                          {(row.spec_warnings || []).length > 0 && (
                            <div className="mb-1"><b>Spec warnings:</b> {row.spec_warnings.join('; ')}</div>
                          )}
                          {(row.docs_retrieved || []).length > 0 && (
                            <div>
                              <b>Docs injected:</b>
                              <ul className="mt-1 ml-3 space-y-0.5">
                                {row.docs_retrieved.map((d, i) => (
                                  <li key={i}>
                                    <span className="font-mono">{d.concept}</span>
                                    {' '}<Badge>{d.doc_type}</Badge>
                                    {' '}{d.tokens} tokens
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
      </Section>
    </div>
  )
}
```

- [ ] **Step 2: Update App.jsx**

**Edit 1** — add import after the `IngestPanel` import (line 23):
```javascript
import DocsTab from './components/DocsTab'
```

**Edit 2** — add `'Docs'` to `TOOLS_TABS` (line 56):
```javascript
// OLD:
const TOOLS_TABS = ['Tests', 'Ingest']
// NEW:
const TOOLS_TABS = ['Tests', 'Ingest', 'Docs']
```

**Edit 3** — add render case after the `{activeTab === 'Ingest' && ...}` block (after line 776):
```javascript
          {activeTab === 'Docs' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 bg-white overflow-hidden">
                <DocsTab />
              </div>
            </div>
          )}
```

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/DocsTab.jsx gui/src/App.jsx
git commit -m "feat(gui): add Docs tab with ingested doc coverage and generation log"
```

---

## Task 7: Full test run + push

- [ ] **Step 1: Syntax-check all changed Python files**

```bash
python -m py_compile mcp_server/tools/skills/storage/interface.py && \
python -m py_compile mcp_server/tools/skills/storage/sqlite_backend.py && \
python -m py_compile mcp_server/tools/skills/storage/postgres_backend.py && \
python -m py_compile mcp_server/tools/skills/generator.py && \
python -m py_compile mcp_server/tools/skills/meta_tools.py && \
python -m py_compile api/routers/skills.py
```
Expected: no output for any file.

- [ ] **Step 2: Run full new test suite**

```bash
python -m pytest tests/test_generation_log.py tests/test_doc_retrieval.py tests/test_prompt_builder.py tests/test_docs_coverage.py -v 2>&1 | tail -20
```
Expected: all ~30 tests pass.

- [ ] **Step 3: Run existing skills router tests to confirm no regressions**

```bash
python -m pytest tests/test_skills_router.py -v 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 4: Push**

```bash
git push
```
