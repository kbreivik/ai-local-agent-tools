"""v2.35.19 — get_all_connections_for_platform loud errors + retry."""
import logging
from unittest.mock import patch, MagicMock


def test_returns_rows_on_first_success():
    """Happy path — no retry, no warning."""
    from api import connections
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.description = [("id",), ("platform",), ("host",), ("enabled",),
                            ("credentials",), ("config",)]
    fake_cur.fetchall.return_value = [
        ("uuid-1", "vm_host", "h1.example", True, "", "{}"),
    ]
    fake_conn.cursor.return_value = fake_cur
    with patch("api.connections._get_conn", return_value=fake_conn), \
         patch("api.connections._decode_creds", side_effect=lambda r: r):
        result = connections.get_all_connections_for_platform("vm_host")
    assert len(result) == 1
    assert result[0]["host"] == "h1.example"


def test_retries_once_on_transient_failure():
    """Exception on attempt 1, success on attempt 2."""
    from api import connections
    call_count = {"n": 0}

    def _maybe_failing_conn():
        call_count["n"] += 1
        c = MagicMock()
        if call_count["n"] == 1:
            c.cursor.return_value.execute.side_effect = RuntimeError("pool timeout")
        else:
            cur = MagicMock()
            cur.description = [("id",), ("host",)]
            cur.fetchall.return_value = [("uuid-1", "h1")]
            c.cursor.return_value = cur
        return c

    with patch("api.connections._get_conn", side_effect=_maybe_failing_conn), \
         patch("api.connections._decode_creds", side_effect=lambda r: r):
        connections.get_all_connections_for_platform("vm_host")
    assert call_count["n"] == 2  # Retried


def test_logs_warning_on_exhausted_retry(caplog):
    """Both attempts fail → WARNING logged (not silently swallowed)."""
    from api import connections
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = RuntimeError("DB broken")
    with patch("api.connections._get_conn", return_value=fake_conn), \
         patch("api.connections._get_sa_conn", return_value=None), \
         caplog.at_level(logging.WARNING, logger="api.connections"):
        result = connections.get_all_connections_for_platform("vm_host")
    assert result == []
    warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("attempt 2" in m for m in warning_msgs), (
        "Expected a WARNING mentioning attempt 2 — got: " + str(warning_msgs)
    )


def test_get_connection_for_platform_retries_once_on_transient_failure():
    """Symmetric retry test for get_connection_for_platform (singular)."""
    from api import connections
    call_count = {"n": 0}

    def _maybe_failing_conn():
        call_count["n"] += 1
        c = MagicMock()
        if call_count["n"] == 1:
            c.cursor.return_value.execute.side_effect = RuntimeError("pool timeout")
        else:
            cur = MagicMock()
            cur.description = [("id",), ("host",), ("config",)]
            cur.fetchone.return_value = ("uuid-1", "h1", "{}")
            c.cursor.return_value = cur
        return c

    with patch("api.connections._get_conn", side_effect=_maybe_failing_conn), \
         patch("api.connections._decode_creds", side_effect=lambda r: r):
        connections.get_connection_for_platform("vm_host")
    assert call_count["n"] == 2
