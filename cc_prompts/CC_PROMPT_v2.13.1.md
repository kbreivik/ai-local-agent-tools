# CC PROMPT — v2.13.1 — Skill system: skill_execute dispatcher + three-layer validation

## What this does

Currently each dynamic skill is registered as its own MCP tool.
With 20+ skills, the LLM sees all of them in every request — context bloat.

This replaces N individual skill tools with ONE `skill_execute` dispatcher.
Skills are discovered via `skill_search`, then called via `skill_execute`.

Also adds three-layer validation: deterministic + live probe + optional LLM critic.

Version bump: 2.13.0 → 2.13.1 (skill dispatch model change, x.x.1)

---

## Change 1 — api/tool_registry.py — replace per-skill registration with dispatcher

Find where dynamic skills are loaded into the tool registry. Currently each skill
gets its own entry in the tools spec. Change this so only `skill_execute` is
registered as a tool, with a description that explains to call `skill_search` first:

```python
# BEFORE: register each skill as its own tool
for skill in list_skills(enabled_only=True):
    tools_spec.append({
        "function": {
            "name": skill["name"],
            "description": skill["description"],
            "parameters": skill["parameters"],
        }
    })

# AFTER: register ONE dispatcher tool
SKILL_EXECUTE_SPEC = {
    "type": "function",
    "function": {
        "name": "skill_execute",
        "description": (
            "Execute a dynamic skill by name. "
            "Call skill_search(query=...) first to find available skills and their parameters. "
            "Then call skill_execute(name=..., **params) to run the skill. "
            "Do not guess skill names — always search first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact skill name from skill_search results",
                },
                "params": {
                    "type": "object",
                    "description": "Parameters to pass to the skill (see skill_search for schema)",
                    "additionalProperties": True,
                },
            },
            "required": ["name"],
        },
    },
}
```

Add `SKILL_EXECUTE_SPEC` to the tools spec instead of individual skills.

---

## Change 2 — mcp_server/tools/meta_tools.py — implement skill_execute

```python
def skill_execute(name: str, params: dict = None) -> dict:
    """Execute a dynamic skill by name with given parameters.

    Always call skill_search() first to verify the skill exists and
    check its parameter schema before calling this tool.

    Args:
        name:   Exact skill name (from skill_search results)
        params: Dict of parameters matching the skill's parameter schema
    """
    from mcp_server.tools.skills.registry import get_skill
    from mcp_server.tools.skills.loader import load_skill_module

    skill = get_skill(name)
    if not skill:
        return {
            "status": "error",
            "message": f"Skill {name!r} not found. Call skill_search() to find available skills.",
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    if not skill.get("enabled"):
        return {
            "status": "error",
            "message": f"Skill {name!r} is disabled.",
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    try:
        module = load_skill_module(skill)
        result = module.execute(**(params or {}))
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Skill {name!r} execution error: {e}",
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
```

---

## Change 3 — Three-layer validation in validate_skill_live tool

Update the existing `validate_skill_live` tool (or create it) with full three layers:

```python
def validate_skill_live(name: str) -> dict:
    """Test a skill against its live service. Three validation layers:

    Layer 1 (deterministic): syntax, banned imports, SKILL_META contract, response shape
    Layer 2 (live probe):    call actual endpoints, verify response fields
    Layer 3 (critic):        optional LLM review of code vs spec (requires LM Studio)

    Use after skill_create, after service upgrades, or when a skill starts failing.
    """
    from mcp_server.tools.skills.registry import get_skill
    from mcp_server.tools.skills.validator import validate_skill_code
    from mcp_server.tools.skills.loader import load_skill_module

    skill = get_skill(name)
    if not skill:
        return {"status": "error", "message": f"Skill {name!r} not found"}

    results = {"name": name, "layers": {}}

    # ── Layer 1: Deterministic ────────────────────────────────────────────────
    layer1 = validate_skill_code(skill.get("code", ""))
    results["layers"]["deterministic"] = layer1

    if not layer1.get("valid"):
        results["valid"] = False
        results["message"] = f"Layer 1 failed: {layer1.get('errors', [])}"
        return {"status": "error", "data": results,
                "message": results["message"],
                "timestamp": datetime.now(timezone.utc).isoformat()}

    # ── Layer 2: Live probe ───────────────────────────────────────────────────
    try:
        module = load_skill_module(skill)
        spec = getattr(module, "SKILL_META", {})
        service = spec.get("compat", {}).get("service", "")

        from api.connections import get_connection_for_platform
        conn = get_connection_for_platform(service) if service else None

        if conn:
            # Execute with minimal/default params to test connectivity
            import inspect
            sig = inspect.signature(module.execute)
            default_params = {
                k: v.default for k, v in sig.parameters.items()
                if v.default is not inspect.Parameter.empty
            }
            try:
                result = module.execute(**default_params)
                layer2_valid = isinstance(result, dict) and "status" in result
                layer2 = {
                    "valid": layer2_valid,
                    "result_status": result.get("status") if isinstance(result, dict) else "invalid",
                    "message": result.get("message", "") if isinstance(result, dict) else str(result)[:100],
                }
            except Exception as e2:
                layer2 = {"valid": False, "error": str(e2)[:200]}
        else:
            layer2 = {"valid": True, "skipped": True,
                      "reason": f"No {service!r} connection configured — skipping live probe"}

        results["layers"]["live_probe"] = layer2
    except Exception as e:
        results["layers"]["live_probe"] = {"valid": False, "error": str(e)[:200]}

    # ── Layer 3: LLM critic (optional, best-effort) ───────────────────────────
    try:
        import os
        from openai import OpenAI
        lm_base = os.environ.get("LM_STUDIO_BASE_URL", "")
        if lm_base and results["layers"]["live_probe"].get("valid"):
            client = OpenAI(base_url=lm_base,
                            api_key=os.environ.get("LM_STUDIO_API_KEY", "lm-studio"))
            code = skill.get("code", "")[:2000]
            critic_prompt = (
                f"Review this Python skill code. List any issues as JSON array.\n"
                f"Check: correct response shape {{status, data, message, timestamp}}, "
                f"error handling, no hardcoded secrets, sensible defaults.\n"
                f"Output ONLY JSON array of {{issue, severity: error|warning, fix}} objects. "
                f"Empty array if no issues.\n\nCode:\n{code}\n/no_think"
            )
            resp = client.chat.completions.create(
                model=os.environ.get("LM_STUDIO_MODEL", ""),
                messages=[{"role": "user", "content": critic_prompt}],
                tools=None, temperature=0.1, max_tokens=400,
            )
            text = resp.choices[0].message.content or "[]"
            text = text.strip().strip("```json").strip("```").strip()
            import json
            issues = json.loads(text) if text.startswith("[") else []
            errors = [i for i in issues if i.get("severity") == "error"]
            layer3 = {
                "valid": len(errors) == 0,
                "issues": issues,
                "error_count": len(errors),
                "warning_count": len([i for i in issues if i.get("severity") == "warning"]),
            }
        else:
            layer3 = {"valid": True, "skipped": True, "reason": "LM Studio not available or live probe failed"}
        results["layers"]["critic"] = layer3
    except Exception as e:
        results["layers"]["critic"] = {"valid": True, "skipped": True, "error": str(e)[:100]}

    # ── Overall result ────────────────────────────────────────────────────────
    all_valid = all(
        layer.get("valid", True)
        for layer in results["layers"].values()
        if not layer.get("skipped")
    )
    results["valid"] = all_valid
    results["message"] = "All validation layers passed" if all_valid else \
        "Validation failed — check layers for details"

    return {
        "status": "ok" if all_valid else "error",
        "data": results,
        "message": results["message"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

---

## Change 4 — api/agents/router.py — update allowlists

- Remove individual skill names from allowlists (they're no longer registered as tools)
- Ensure `skill_execute` is in OBSERVE, INVESTIGATE, EXECUTE_GENERAL, BUILD allowlists
- `skill_search` remains essential — it's how the agent discovers available skills

Add to STATUS_PROMPT:

```
DYNAMIC SKILLS:
Dynamic skills are not listed in the tool manifest individually.
To use a skill: first call skill_search(query=...) to find it,
then call skill_execute(name=..., params={...}) to run it.
Never guess skill names — always search first.
```

---

## Version bump

Update VERSION: `2.13.0` → `2.13.1`

---

## Commit

```bash
git add -A
git commit -m "feat(skills): v2.13.1 skill_execute dispatcher + three-layer validation

- Single skill_execute dispatcher replaces N individual skill tools
- LLM sees 1 dispatcher tool instead of 20+ skill tools (context reduction)
- validate_skill_live: Layer 1 deterministic + Layer 2 live probe + Layer 3 LLM critic
- Layer 3 blocks only on severity=error, warnings logged but non-blocking
- STATUS_PROMPT: DYNAMIC SKILLS section instructs search-then-execute pattern"
git push origin main
```
