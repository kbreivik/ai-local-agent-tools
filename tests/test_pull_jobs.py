def test_new_and_update_pull_job():
    from api.routers import dashboard as d
    job = d._new_pull_job("abc123", "v1.2.3")
    assert job in d._PULL_JOBS
    d._update_pull_job(job, status="downloading", layers={"L1": {"current": 50, "total": 100}})
    # layers are mutated via setdefault inside the streaming loop — simulate here
    d._PULL_JOBS[job]["layers"]["L1"] = {"status": "Downloading", "current": 50, "total": 100}
    d._update_pull_job(job, _recompute=True)
    assert d._PULL_JOBS[job]["bytes_done"] == 50
    assert d._PULL_JOBS[job]["bytes_total"] == 100
    assert d._PULL_JOBS[job]["percent"] == 50

def test_prune_keeps_max():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    for i in range(d._PULL_JOBS_MAX + 10):
        jid = d._new_pull_job(f"c{i}", None)
        d._PULL_JOBS[jid]["status"] = "done"
    assert len(d._PULL_JOBS) <= d._PULL_JOBS_MAX
