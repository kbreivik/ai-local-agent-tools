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
