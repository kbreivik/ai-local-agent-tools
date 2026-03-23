"""Test skill persistence to data/skill_modules/ volume."""
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_load_all_skills_scans_generated_dir(tmp_path, monkeypatch):
    """Skills in data/skill_modules/ are loaded alongside modules/."""
    from mcp_server.tools.skills import loader

    gen_dir = tmp_path / "data" / "skill_modules"
    gen_dir.mkdir(parents=True)

    skill_code = textwrap.dedent("""\
        from datetime import datetime, timezone
        SKILL_META = {
            "name": "test_generated_skill",
            "description": "test",
            "category": "general",
            "version": "1.0.0",
            "annotations": {},
            "parameters": {},
            "auth_type": "none",
            "config_keys": [],
            "compat": {},
        }
        def _ts(): return datetime.now(timezone.utc).isoformat()
        def _ok(d, m="OK"): return {"status":"ok","data":d,"timestamp":_ts(),"message":m}
        def _err(m, d=None): return {"status":"error","data":d,"timestamp":_ts(),"message":m}
        def execute(**kwargs): return _ok({"test": True})
    """)
    (gen_dir / "test_generated_skill.py").write_text(skill_code)

    monkeypatch.setattr(loader, "GENERATED_DIR", str(gen_dir))

    result = loader.load_all_skills(None)
    assert "test_generated_skill" in result["loaded"]
