"""v2.35.20 — infra_lookup tool contract: not-found is status=ok,
not status=error. Semantic fix — 'no match' is not a tool failure."""
from unittest.mock import patch


def test_found_returns_ok_and_found_true():
    from mcp_server.tools.vm import infra_lookup
    fake_entry = {
        "connection_id": "abc",
        "platform": "vm_host",
        "label": "worker-01",
        "hostname": "ds-docker-worker-01",
        "ips": ["192.168.199.31"],
        "aliases": [],
        "meta": {},
    }
    with patch("api.db.infra_inventory.resolve_host", return_value=fake_entry):
        r = infra_lookup(query="worker-01")
    assert r["status"] == "ok"
    # For a found result, data is the entry itself (no 'found' key needed)
    assert r["data"]["label"] == "worker-01"


def test_not_found_returns_ok_with_found_false():
    """v2.35.20: critical regression — NOT an error."""
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host", return_value=None):
        r = infra_lookup(query="aa:bb:cc:dd:ee:ff")
    assert r["status"] == "ok", (
        f"Expected status=ok for not-found, got {r['status']}: {r['message']!r}"
    )
    assert r["data"]["found"] is False
    assert r["data"]["query"] == "aa:bb:cc:dd:ee:ff"
    assert "aa:bb:cc:dd:ee:ff" in r["message"]


def test_not_found_with_platform_filter_preserves_filter():
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host", return_value=None):
        r = infra_lookup(query="unknown-thing", platform="vm_host")
    assert r["status"] == "ok"
    assert r["data"]["found"] is False
    assert r["data"]["platform_filter"] == "vm_host"


def test_list_inventory_branch_unchanged():
    """Regression: the empty-query branch was already returning ok.
    Don't accidentally break it."""
    from mcp_server.tools.vm import infra_lookup
    fake_entries = [
        {"label": "worker-01", "hostname": "h1", "ips": ["10.0.0.1"],
         "platform": "vm_host", "meta": {}},
    ]
    with patch("api.db.infra_inventory.list_inventory", return_value=fake_entries):
        r = infra_lookup(query="", platform="vm_host")
    assert r["status"] == "ok"
    assert "entities" in r["data"]
    assert len(r["data"]["entities"]) == 1


def test_db_exception_still_returns_error():
    """Only genuine exec failures (DB error, exception) are status=error.
    'Not found' is not an exec failure."""
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host",
               side_effect=RuntimeError("DB connection lost")):
        r = infra_lookup(query="worker-01")
    assert r["status"] == "error"
    assert "DB connection lost" in r["message"] or "error" in r["message"].lower()
