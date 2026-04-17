"""Unit tests for v2.33.9 drift detection.

Covers the pure-Python config_hash computation and the task template
registry. DB-backed paths (record_snapshot, drift_events view) are exercised
by integration tests because they require a live Postgres.
"""


def test_compute_config_hash_ignores_volatile():
    from api.db.entity_history import compute_config_hash
    h1 = compute_config_hash({"image": "nginx:1.24", "uptime": "3d"})
    h2 = compute_config_hash({"image": "nginx:1.24", "uptime": "5d"})
    assert h1 == h2   # uptime is volatile — must not affect the hash


def test_compute_config_hash_detects_image_change():
    from api.db.entity_history import compute_config_hash
    h1 = compute_config_hash({"image": "nginx:1.24"})
    h2 = compute_config_hash({"image": "nginx:1.25"})
    assert h1 != h2


def test_compute_config_hash_empty_returns_empty_string():
    from api.db.entity_history import compute_config_hash
    assert compute_config_hash({}) == ""
    assert compute_config_hash(None) == ""


def test_compute_config_hash_stable_across_key_order():
    from api.db.entity_history import compute_config_hash
    a = compute_config_hash({"image": "nginx:1.24", "replicas": 3})
    b = compute_config_hash({"replicas": 3, "image": "nginx:1.24"})
    assert a == b


def test_investigate_drift_template_exists():
    from api.agents.task_templates import TASK_TEMPLATES
    assert any(t["name"] == "investigate_drift" for t in TASK_TEMPLATES)


def test_investigate_drift_template_shape():
    from api.agents.task_templates import TEMPLATES
    t = TEMPLATES["investigate_drift"]
    assert t["agent_type"] == "investigate"
    assert t["destructive"] is False
    assert t["blast_radius"] == "none"
    assert any(i["name"] == "entity_id" for i in t["inputs"])
    # Template must include the structured output shape so downstream
    # consumers can parse DRIFT_KEYS / LIKELY_SOURCE reliably.
    assert "DRIFT_KEYS:" in t["prompt_template"]
    assert "LIKELY_SOURCE:" in t["prompt_template"]
