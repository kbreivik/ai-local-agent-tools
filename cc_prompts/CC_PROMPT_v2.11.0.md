# CC PROMPT — v2.11.0 — Multi-connection collector support

## What this does

`external_services.py` currently calls `get_connection_for_platform()` (LIMIT 1)
for each platform in its poll loop — so if you add two UniFi connections or two
FortiGate connections, only the first one ever gets probed.

`get_all_connections_for_platform()` already exists and works correctly.
This change makes `external_services.py` use it, so every registered connection
of every platform gets probed and gets its own card.

Also fixes the same issue in `truenas.py`, `pbs.py`, and `unifi.py` collectors
if they exist as standalone collectors (check and fix if present).

Version bump: 2.10.1 → 2.11.0 (architectural change affects all collectors, x.1.x)

---

## Change 1 — api/collectors/external_services.py

In `_collect_sync()`, find the loop:

```python
for platform, health_cfg in PLATFORM_HEALTH.items():
    conn = get_connection_for_platform(platform)
    if not conn:
        continue
    cards.append(self._probe_connection(conn, health_cfg))
```

Replace with:

```python
for platform, health_cfg in PLATFORM_HEALTH.items():
    conns = get_all_connections_for_platform(platform)
    if not conns:
        continue
    for conn in conns:
        cards.append(self._probe_connection(conn, health_cfg))
```

Also update the import at the top of the method:

```python
from api.connections import get_all_connections_for_platform
```

Remove the `get_connection_for_platform` import from this method if it's only
used for the loop above.

---

## Change 2 — Verify and fix any standalone collectors using LIMIT 1

Check these files and fix if they use `get_connection_for_platform()` in a poll loop
where multiple connections of that type should each get their own card:

- `api/collectors/truenas.py` — if it exists, check poll loop
- `api/collectors/pbs.py` — if it exists, check poll loop  
- `api/collectors/unifi.py` — already multi-connection aware (check)

For any that use `get_connection_for_platform()` in a loop:
Replace with `get_all_connections_for_platform()` and iterate.

The pattern is always:
```python
# BEFORE (wrong — only gets first)
conn = get_connection_for_platform("truenas")
if conn:
    # poll conn

# AFTER (correct — gets all)
for conn in get_all_connections_for_platform("truenas"):
    # poll conn
```

---

## Change 3 — api/collectors/external_services.py — label deduplication

When multiple connections exist for the same platform, the card labels need to be
distinct. The `label` field on each connection already handles this (user sets it
in Settings → Connections). Verify that `_probe_connection()` uses `conn.get("label")`
as the card name — it already does. No change needed here if so.

If two connections have the same label (shouldn't happen due to UNIQUE constraint),
append the host to disambiguate:

```python
label = conn.get("label") or f"{platform} ({host})"
# If label collides with another card from same platform, append host
```

---

## Change 4 — Collector trigger map verification

In `api/routers/connections.py`, the trigger map fires collectors after
a connection is saved/deleted. Verify the trigger fires `external_services`
for all platforms so new connections immediately appear without waiting
for the next poll cycle. The existing trigger map already does this —
just confirm it covers all PLATFORM_HEALTH keys.

---

## Version bump

Update VERSION: `2.11.0` → `2.11.0`

---

## Commit

```bash
git add -A
git commit -m "feat(collectors): v2.11.0 multi-connection support in external_services

- external_services.py: use get_all_connections_for_platform() instead of LIMIT 1
- Each registered connection of each platform now gets its own probed card
- Fix same issue in any standalone collectors (truenas, pbs, unifi) if present
- Supports multiple FortiGate, UniFi, TrueNAS, PBS connections simultaneously"
git push origin main
```
