# mcp_server/tools/skills/promoter.py
"""Skill lifecycle operations: promote, demote, scrap, restore.

All functions return {"status": "ok"|"error", "message": str, "data": dict|None}.
File operations use data/skill_modules_scrapped/ as a holding area for scrapped skills
so they can be restored without re-generating.
"""
import os
import shutil
from datetime import datetime, timezone

from mcp_server.tools.skills import registry
from mcp_server.tools.skills.loader import GENERATED_DIR, _MODULES_DIR
from mcp_server.tools import orchestration


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data=None, msg="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": msg}

def _err(msg, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": msg}

_SCRAPPED_DIR = os.path.join(os.path.dirname(GENERATED_DIR), "skill_modules_scrapped")


def promote_skill(name: str, domain: str) -> dict:
    """Mark skill as promoted and assign it to an agent domain.

    Args:
        name: Skill name (must exist in DB).
        domain: Agent domain — kafka | swarm | proxmox | general.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    valid_domains = {"kafka", "swarm", "proxmox", "general"}
    if domain not in valid_domains:
        return _err(f"Invalid domain '{domain}'. Must be one of: {', '.join(valid_domains)}")

    if skill.get("lifecycle_state") == "scrapped":
        return _err(f"Skill '{name}' is scrapped. Restore it before promoting.")

    registry._db().update_skill(name, lifecycle_state="promoted", agent_domain=domain)
    orchestration.audit_log("skill_promote", {"name": name, "domain": domain})
    return _ok({"name": name, "domain": domain},
               f"Skill '{name}' promoted to {domain} agent. Restart to activate as @mcp.tool().")


def demote_skill(name: str) -> dict:
    """Remove skill from promoted state, back to auto_generated.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    if skill.get("lifecycle_state") not in ("promoted", "auto_generated"):
        return _err(f"Skill '{name}' is in state '{skill.get('lifecycle_state')}' and cannot be demoted directly.")
    if skill.get("lifecycle_state") == "auto_generated":
        return _ok({"name": name}, f"Skill '{name}' is already auto_generated.")

    registry._db().update_skill(name, lifecycle_state="auto_generated", agent_domain="")
    orchestration.audit_log("skill_demote", {"name": name})
    return _ok({"name": name}, f"Skill '{name}' demoted. Will be removed from @mcp.tool() on next restart.")


def scrap_skill(name: str) -> dict:
    """Disable skill and move its file to the scrapped holding area.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    file_path = skill.get("file_path", "")

    # Block scrapping of starter skills (files live in image-baked modules/ dir)
    if file_path and os.path.commonpath([os.path.abspath(file_path), _MODULES_DIR]) == _MODULES_DIR:
        return _err(f"Skill '{name}' is a starter skill in modules/ and cannot be scrapped.")

    os.makedirs(_SCRAPPED_DIR, exist_ok=True)

    # Update DB first; if file move fails, we can roll back DB state
    registry._db().update_skill(name, enabled=0, lifecycle_state="scrapped", agent_domain="")

    if file_path and os.path.exists(file_path):
        dest = os.path.join(_SCRAPPED_DIR, os.path.basename(file_path))
        try:
            shutil.move(file_path, dest)
        except Exception as e:
            # Roll back DB state
            registry._db().update_skill(name, enabled=1,
                                         lifecycle_state=skill.get("lifecycle_state", "auto_generated"),
                                         agent_domain=skill.get("agent_domain", ""))
            return _err(f"Failed to move skill file: {e}")

    orchestration.audit_log("skill_scrap", {"name": name})
    return _ok({"name": name}, f"Skill '{name}' scrapped. Use restore to recover.")


def restore_skill(name: str) -> dict:
    """Move scrapped skill file back and re-enable it.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    if skill.get("lifecycle_state") != "scrapped":
        return _err(f"Skill '{name}' is not scrapped (state: {skill.get('lifecycle_state')}).")

    # Find the file in scrapped dir
    fname = f"{name}.py"
    scrapped_path = os.path.join(_SCRAPPED_DIR, fname)
    if not os.path.exists(scrapped_path):
        return _err(f"Scrapped file not found at {scrapped_path}. Cannot restore.")

    os.makedirs(GENERATED_DIR, exist_ok=True)
    dest = os.path.join(GENERATED_DIR, fname)
    shutil.move(scrapped_path, dest)

    registry._db().update_skill(name, enabled=1, lifecycle_state="auto_generated",
                                 file_path=dest)
    orchestration.audit_log("skill_restore", {"name": name})
    return _ok({"name": name}, f"Skill '{name}' restored. Reload skills to activate.")
