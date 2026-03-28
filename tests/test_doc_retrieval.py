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


def test_extract_keywords_has_all_expected_keys():
    result = extract_keywords("fortigate system status")
    assert "services" in result
    assert "tech" in result
    assert "endpoints" in result
    assert "versions" in result
    assert "raw_terms" in result


def test_fetch_relevant_docs_no_muninndb_engrams_uses_service_catalog():
    """When MuninnDB returns no engrams, muninndb is absent from sources_used."""
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=[]):
        result = fetch_relevant_docs("fortigate system status", category="networking")
    assert result["status"] == "ok"
    assert "muninndb" not in result["data"]["sources_used"]


def test_fetch_relevant_docs_returns_ok_on_full_failure():
    """When MuninnDB and local scan both return nothing, status is still ok with empty context_docs."""
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=[]), \
         patch("mcp_server.tools.skills.doc_retrieval._scan_local_docs", return_value=[]):
        result = fetch_relevant_docs("fortigate system status")
    assert result["status"] == "ok"
    assert result["data"]["context_docs"] == []
    assert result["data"]["total_tokens"] == 0


def test_fetch_relevant_docs_total_tokens_matches_sum():
    """total_tokens equals sum of tokens across context_docs."""
    # Raw engrams returned by _query_muninndb_multi — no _type_priority/_doc_type yet
    fake_engrams = [
        {"concept": "fg_api", "content": "x" * 200, "tags": [], "activation": 0.9},
    ]
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=fake_engrams):
        result = fetch_relevant_docs("fortigate api status")
    data = result["data"]
    expected_total = sum(d["tokens"] for d in data["context_docs"])
    assert data["total_tokens"] == expected_total


def test_fetch_relevant_docs_muninndb_in_sources_when_engrams_returned():
    fake_engrams = [
        {"concept": "fg_api", "content": "FortiGate REST API reference content",
         "tags": [], "activation": 0.8},
    ]
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=fake_engrams):
        result = fetch_relevant_docs("fortigate health")
    assert "muninndb" in result["data"]["sources_used"]


def test_fetch_relevant_docs_has_expected_data_keys():
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=[]):
        result = fetch_relevant_docs("test skill")
    data = result["data"]
    assert "context_docs" in data
    assert "sources_used" in data
    assert "total_tokens" in data
    assert "keywords" in data


def test_fetch_relevant_docs_context_docs_have_expected_fields():
    fake_engrams = [
        {"concept": "fg_api", "content": "FortiGate API docs here", "tags": ["api"], "activation": 0.9},
    ]
    with patch("mcp_server.tools.skills.doc_retrieval._query_muninndb_multi", return_value=fake_engrams):
        result = fetch_relevant_docs("fortigate api status")
    for doc in result["data"]["context_docs"]:
        assert "concept" in doc
        assert "content" in doc
        assert "tokens" in doc
