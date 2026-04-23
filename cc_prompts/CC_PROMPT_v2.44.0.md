# CC PROMPT — v2.44.0 — fix(settings): add memoryEnabled + memoryBackend to SETTINGS_KEYS

## What this does

v2.43.8 added `memoryEnabled` and `memoryBackend` to `settings_manager.py`
CATEGORIES and to `memory/client.py` get_client() check, but forgot to add
them to `SETTINGS_KEYS` in `api/routers/settings.py`.

`update_settings()` rejects any key not in SETTINGS_KEYS with a silent skip
(Updated 0 setting(s)), so the toggle cannot be saved via API.

One-file fix: add both keys to SETTINGS_KEYS.

Version bump: 2.43.9 → 2.44.0.

---

## Change — `api/routers/settings.py`

Locate the `renderToolPromptEnabled` block:

```python
    "renderToolPromptEnabled": {
        "env": None, "sens": False, "default": False, "type": "bool",
        "group": "Agent Budgets",
    },
```

Add immediately after it:

```python
    # --- Memory backend (v2.43.8/v2.43.9) ---
    "memoryEnabled": {
        "env": None, "sens": False, "default": True, "type": "bool",
        "group": "Agent Budgets",
        "description": (
            "When false, all MuninnDB/memory calls return empty results (NullMuninnClient). "
            "Useful for A/B testing agent quality without memory context."
        ),
    },
    "memoryBackend": {
        "env": None, "sens": False, "default": "muninndb", "type": "str",
        "group": "Agent Budgets",
        "description": (
            "Memory storage backend. 'muninndb' uses MuninnDB REST API. "
            "'postgres' uses pg_engrams table (tsvector + Hebbian access_count). "
            "Ignored when memoryEnabled=false."
        ),
    },
```

---

## Verification

```bash
# Disable memory
curl -X POST http://192.168.199.10:8000/api/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"memoryEnabled": false}'
# Expected: {"message": "Updated 1 setting(s)", "data": {"updated": {"memoryEnabled": false}}}

# Re-enable
curl -X POST http://192.168.199.10:8000/api/settings \
  -d '{"memoryEnabled": true}'
```

---

## Version bump

Update `VERSION`: `2.43.9` → `2.44.0`

---

## Commit

```
git add -A
git commit -m "fix(settings): v2.44.0 add memoryEnabled + memoryBackend to SETTINGS_KEYS"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
