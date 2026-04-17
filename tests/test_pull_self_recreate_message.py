def test_self_recreate_message_contains_refresh_instructions():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("hp1_agent", None)
    d._update_pull_job(
        jid, status="done", phase="done",
        message="Agent recreation triggered. Wait ~30s, then "
                "hard-refresh this page (Ctrl+Shift+R) and log in again.",
        is_self_recreate=True,
        completed_at=123.0, percent=100,
    )
    job = d._PULL_JOBS[jid]
    assert job["percent"] == 100
    assert job["is_self_recreate"] is True
    assert "Ctrl+Shift+R" in job["message"]
    assert "log in" in job["message"].lower()


def test_non_self_recreate_has_no_flag():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("kafka_broker-1", None)
    d._update_pull_job(
        jid, status="done", phase="done",
        message="Pull + restart complete",
        completed_at=123.0, percent=100,
    )
    assert d._PULL_JOBS[jid].get("is_self_recreate") in (None, False)
