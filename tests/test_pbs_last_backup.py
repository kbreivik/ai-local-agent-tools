"""Tests for pbs_last_backup tool + verify_backup_job template."""


def test_pbs_last_backup_shape():
    from mcp_server.tools.pbs import pbs_last_backup
    # Should return a dict with 'status' key regardless of DB state
    r = pbs_last_backup("nonexistent-99999")
    assert isinstance(r, dict)
    assert r["status"] in ("UNKNOWN", "FAIL")


def test_pbs_last_backup_normalises_prefixed_ids():
    from mcp_server.tools.pbs import pbs_last_backup
    r = pbs_last_backup("qemu/nope-12345")
    assert isinstance(r, dict)
    assert r["status"] in ("UNKNOWN", "FAIL")
    r2 = pbs_last_backup("lxc/nope-12345")
    assert isinstance(r2, dict)
    assert r2["status"] in ("UNKNOWN", "FAIL")


def test_verify_backup_template():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["name"] == "verify_backup_job")
    assert t["agent_type"] == "observe"
    assert "pbs_last_backup" in t["prompt_template"]
    assert t["blast_radius"] == "none"
    assert t["destructive"] is False


def test_verify_backup_template_registered():
    from api.agents.task_templates import get_template
    t = get_template("verify_backup_job")
    assert t is not None
    assert t["id"] == "verify_backup_job"
