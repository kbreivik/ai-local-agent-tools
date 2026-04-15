# CC PROMPT — v2.26.8 — Docker container started_at + restart_count metadata

## What this does
Extracts `State.StartedAt` and `State.RestartCount` from Docker inspect attrs in
`docker_agent01.py` and surfaces both in entity metadata. Closes the gap where the
pre-baked "When was this container last restarted?" question had no data to answer from.
Version bump: 2.26.7 → 2.26.8

---

## Change 1 — api/collectors/docker_agent01.py

### Part A — _collect_sync: extract started_at and restart_count from attrs

Find the block that builds each card dict (after the `ip_addresses` lines, inside the
`for c in containers:` loop). The current card dict ends with:

```python
                cards.append({
                    "id": c.short_id,
                    "name": name,
                    "image": image,
                    "state": state_str,
                    "health": health_str,
                    "ip_port": ip_port,
                    "uptime": attrs.get("Status", ""),
                    "ports": ports,
                    "volumes": volumes,
                    "last_pull_at": last_pull_at,
                    "running_version": running_version,
                    "built_at": built_at,
                    "dot": dot,
                    "problem": problem,
                    "networks": network_names,
                    "ip_addresses": ip_addresses,
                    "entity_id": f"docker:{name}",
                })
```

Replace with:

```python
                state_obj = attrs.get("State") or {}
                started_at = state_obj.get("StartedAt") or None
                # Normalise Docker's zero value ("0001-01-01T00:00:00Z") → None
                if started_at and started_at.startswith("0001-"):
                    started_at = None
                restart_count = state_obj.get("RestartCount")  # int, may be 0

                cards.append({
                    "id": c.short_id,
                    "name": name,
                    "image": image,
                    "state": state_str,
                    "health": health_str,
                    "ip_port": ip_port,
                    "uptime": attrs.get("Status", ""),
                    "ports": ports,
                    "volumes": volumes,
                    "last_pull_at": last_pull_at,
                    "running_version": running_version,
                    "built_at": built_at,
                    "dot": dot,
                    "problem": problem,
                    "networks": network_names,
                    "ip_addresses": ip_addresses,
                    "entity_id": f"docker:{name}",
                    "started_at": started_at,
                    "restart_count": restart_count,
                })
```

### Part B — to_entities: add started_at and restart_count to metadata

Find the `to_entities` method. The current metadata dict is:

```python
                metadata={
                    "image": c.get("image", ""),
                    "state": c.get("state", ""),
                    "uptime": c.get("uptime", ""),
                    "ip_port": c.get("ip_port", ""),
                },
```

Replace with:

```python
                metadata={
                    "image": c.get("image", ""),
                    "state": c.get("state", ""),
                    "uptime": c.get("uptime", ""),
                    "ip_port": c.get("ip_port", ""),
                    "started_at": c.get("started_at"),
                    "restart_count": c.get("restart_count"),
                },
```

---

## Version bump
Update VERSION: 2.26.7 → 2.26.8

---

## Commit
```bash
git add -A
git commit -m "feat(collector): v2.26.8 docker started_at + restart_count in entity metadata"
git push origin main
```
