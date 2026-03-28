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


# ── Generator integration tests ────────────────────────────────────────────────

from unittest.mock import patch, MagicMock
import mcp_server.tools.skills.generator as _gen_module


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
        result = _gen_module.generate_skill("test skill", category="general", skip_spec=True)

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
        result = _gen_module.generate_skill("test skill", category="general", skip_spec=True)

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
        result = _gen_module.generate_skill("test skill", category="general", skip_spec=True)

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
        result = _gen_module.generate_skill("test skill", category="general", skip_spec=True)

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
        _gen_module.generate_skill("test skill", triggered_by="skill_regenerate", skip_spec=True)

    rows = test_backend.get_generation_log()
    assert rows[0]["triggered_by"] == "skill_regenerate"
