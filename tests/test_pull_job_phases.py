def test_percent_monotonic_across_updates():
    """Regression: phase-weighted percent never decreases within a job."""
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("c1", None)

    # Simulate: downloading phase, one layer partial
    d._PULL_JOBS[jid]["layers"]["L1"] = {"status": "Downloading", "current": 50, "total": 100}
    d._update_pull_job(jid, status="downloading")
    p1 = d._PULL_JOBS[jid]["percent"]

    # Simulate: new layer discovered mid-stream, much larger
    d._PULL_JOBS[jid]["layers"]["L2"] = {"status": "Downloading", "current": 10, "total": 10_000}
    d._update_pull_job(jid, status="downloading")
    p2 = d._PULL_JOBS[jid]["percent"]

    assert p2 >= p1, f"percent went backward: {p1} -> {p2} (new layer discovery)"


def test_phase_boundaries():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("c2", None)

    d._update_pull_job(jid, status="starting")
    assert d._PULL_JOBS[jid]["percent"] == 2

    # Downloading with no bytes known yet
    d._update_pull_job(jid, status="downloading")
    assert 5 <= d._PULL_JOBS[jid]["percent"] < 70

    # Extracting with half the layers pulled
    d._PULL_JOBS[jid]["layers"] = {
        "L1": {"status": "Pull complete", "current": 100, "total": 100},
        "L2": {"status": "Extracting",    "current": 30,  "total": 100},
    }
    d._update_pull_job(jid, status="extracting")
    pct = d._PULL_JOBS[jid]["percent"]
    assert 70 <= pct <= 92

    d._update_pull_job(jid, status="recreating")
    assert d._PULL_JOBS[jid]["percent"] >= 92

    d._update_pull_job(jid, status="done", percent=100)
    assert d._PULL_JOBS[jid]["percent"] == 100


def test_error_freezes_bar():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("c3", None)

    d._PULL_JOBS[jid]["layers"]["L1"] = {"status": "Downloading", "current": 400, "total": 1000}
    d._update_pull_job(jid, status="downloading")
    pct_before = d._PULL_JOBS[jid]["percent"]

    d._update_pull_job(jid, status="error", error="registry unauthorized")
    pct_after = d._PULL_JOBS[jid]["percent"]

    # Error should freeze at the downloading percent, not drop to 0
    assert pct_after == pct_before


def test_done_always_100():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("c4", None)
    d._update_pull_job(jid, status="done", percent=100)
    assert d._PULL_JOBS[jid]["percent"] == 100


def test_explicit_percent_only_raises():
    """Explicit percent should not be able to drag the bar backwards."""
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("c5", None)
    d._PULL_JOBS[jid]["percent"] = 40
    d._update_pull_job(jid, status="downloading", percent=10)
    # Monotonic rule wins over explicit lower value
    assert d._PULL_JOBS[jid]["percent"] >= 40
