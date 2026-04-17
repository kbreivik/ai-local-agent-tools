"""Tests for log_timeline — v2.33.19.

The project is sync-only (see .claude/rules/python.md), so these tests are
plain sync functions. They verify bounds handling, source filtering, and
output shape against whatever the local DB happens to have (empty is fine).
"""
from mcp_server.tools.log_timeline import log_timeline


def test_returns_standard_envelope():
    r = log_timeline("nonexistent:entity:9999", window_minutes=1)
    assert r["status"] == "ok"
    assert "data" in r
    assert "timestamp" in r
    data = r["data"]
    assert data["entity_id"] == "nonexistent:entity:9999"
    assert data["window_minutes"] == 1
    assert isinstance(data["events"], list)
    assert data["total"] == len(data["events"])


def test_sources_filter_respected():
    r = log_timeline("proxmox:worker-03:9203", sources=["entity_history"])
    assert r["status"] == "ok"
    assert r["data"]["sources_queried"] == ["entity_history"]
    for e in r["data"]["events"]:
        assert e["source"] == "entity_history"


def test_events_sorted_desc():
    r = log_timeline("proxmox:worker-03:9203")
    assert r["status"] == "ok"
    ts = [e.get("ts") or "" for e in r["data"]["events"]]
    assert ts == sorted(ts, reverse=True)


def test_window_capped_at_24h():
    r = log_timeline("any", window_minutes=99999)
    assert r["status"] == "ok"
    assert r["data"]["window_minutes"] == 1440


def test_window_floor():
    r = log_timeline("any", window_minutes=0)
    assert r["status"] == "ok"
    assert r["data"]["window_minutes"] == 1


def test_invalid_sources_filtered():
    r = log_timeline("any", sources=["bogus", "entity_history"])
    assert r["status"] == "ok"
    assert r["data"]["sources_queried"] == ["entity_history"]


def test_event_shape():
    r = log_timeline("proxmox:worker-03:9203")
    for e in r["data"]["events"]:
        assert {"ts", "source", "kind", "actor", "summary", "detail"} <= set(e.keys())
        assert e["source"] in {"operation_log", "agent_action", "entity_history", "elastic"}
