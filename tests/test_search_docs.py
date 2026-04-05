"""Tests for search_docs tool registration and return format."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_search_docs_tool_registry():
    """search_docs appears in tool_registry with correct params."""
    from api.tool_registry import get_registry
    reg = get_registry(refresh=True)
    tool = next((t for t in reg if t["name"] == "search_docs"), None)
    assert tool is not None, "search_docs not found in tool_registry"
    props = tool["schema"].get("properties", {})
    assert "query" in props
    assert "platform" in props
    assert "doc_type" in props


def test_search_docs_returns_ok_format():
    """search_docs returns project-standard response format."""
    from mcp_server.tools.skill_meta_tools import search_docs
    # With no DATABASE_URL, search returns empty results gracefully
    result = search_docs(query="test query")
    assert result["status"] == "ok"
    assert "data" in result
    assert "chunks" in result["data"]
    assert "count" in result["data"]
    assert isinstance(result["data"]["chunks"], list)
    assert "timestamp" in result
    assert "message" in result


def test_search_docs_empty_without_postgres():
    """Without DATABASE_URL, search_docs returns 0 results (not an error)."""
    old = os.environ.pop("DATABASE_URL", None)
    try:
        from mcp_server.tools.skill_meta_tools import search_docs
        result = search_docs(query="proxmox vm")
        assert result["data"]["count"] == 0
        assert result["data"]["chunks"] == []
    finally:
        if old is not None:
            os.environ["DATABASE_URL"] = old
