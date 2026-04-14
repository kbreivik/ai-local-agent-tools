# CC PROMPT — v2.26.5 — EntityDrawer Ask: token limit + richer entity-aware suggestions

## What this does
Two improvements to the EntityDrawer Ask feature (/api/agent/ask and /api/agent/ask/suggestions):
1. Increase max_tokens from 300 → 600 — current limit truncates most real answers
2. Richer suggestions: entity metadata-aware questions instead of generic status/section ones
   (e.g. for a stopped VM: "What would cause this VM to stop?", for Kafka: "Is this broker in ISR?")
Version bump: v2.26.4 → v2.26.5

---

## Change 1 — api/routers/agent.py

### 1a — Increase max_tokens in /api/agent/ask endpoint

FIND (exact):
```
            stream = client.chat.completions.create(
                model=_lm_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                max_tokens=300,
                temperature=0.3,
            )
```

REPLACE WITH:
```
            stream = client.chat.completions.create(
                model=_lm_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                max_tokens=600,
                temperature=0.3,
            )
```

### 1b — Richer entity-aware ask/suggestions endpoint

FIND (exact — the entire ask_suggestions function body):
```
@router.get("/ask/suggestions")
async def ask_suggestions(status: str = "", section: str = "", _: str = Depends(get_current_user)):
    """Return suggested questions based on entity status and section."""
    suggestions = ["What does this component do?", "Is this status expected?"]

    if status == "error":
        suggestions = [
            "Why might this be failing?",
            "What are common causes for this error?",
            "What should I check first?",
        ]
    elif status == "degraded":
        suggestions = [
            "What could cause this degradation?",
            "Is this a warning or something serious?",
            "What thresholds trigger degraded status?",
        ]
    elif status == "healthy":
        suggestions = [
            "What does this component do?",
            "What would cause this to degrade?",
        ]

    if section == "STORAGE":
        suggestions.append("What happens when storage is full?")
    elif section == "COMPUTE":
        suggestions.append("How does this affect other services?")
    elif section == "NETWORK":
        suggestions.append("What services depend on this?")
    elif section == "SECURITY":
        suggestions.append("What alerts should I watch for?")

    return {"suggestions": suggestions[:4]}
```

REPLACE WITH:
```
@router.get("/ask/suggestions")
async def ask_suggestions(
    status: str = "",
    section: str = "",
    platform: str = "",
    entity_id: str = "",
    _: str = Depends(get_current_user),
):
    """Return suggested questions based on entity status, section, platform, and entity_id."""

    # Platform-specific suggestions take priority
    platform_suggestions: dict[str, list[str]] = {
        "proxmox": {
            "error": [
                "What would cause this VM or container to stop?",
                "Is there a snapshot I can restore from?",
                "How do I check if the host node is healthy?",
                "What Proxmox logs would show the stop reason?",
            ],
            "degraded": [
                "What thresholds trigger a degraded VM status?",
                "Is disk usage causing this?",
                "How do I check memory pressure on the host?",
            ],
            "healthy": [
                "What resources does this VM consume?",
                "When was the last snapshot taken?",
                "What services run inside this VM?",
            ],
        },
        "docker": {
            "error": [
                "What exit code did this container have?",
                "Is there an OOM kill in dmesg?",
                "What does the container log show on last exit?",
                "Is this a dependency failing at startup?",
            ],
            "degraded": [
                "Is the health check endpoint responding?",
                "Is this container on the latest image?",
                "What are the restart conditions?",
            ],
            "healthy": [
                "What image version is running?",
                "What volumes does this container use?",
                "What ports are exposed?",
            ],
        },
        "kafka": {
            "error": [
                "Is this broker missing from the ISR?",
                "Which Swarm worker node is this broker on?",
                "What does the broker log show on last crash?",
            ],
            "degraded": [
                "Which partitions are under-replicated?",
                "What is the current consumer lag?",
                "Is the broker registered in the cluster?",
            ],
            "healthy": [
                "How many partitions does this broker lead?",
                "What is the current replication factor?",
                "Is consumer lag within normal range?",
            ],
        },
        "unifi": {
            "error": [
                "When did this device disconnect?",
                "How many clients lost connectivity?",
                "Is the controller reachable from the device?",
            ],
            "degraded": [
                "How many clients are on this device?",
                "Is the firmware up to date?",
                "Are there interference or error rates?",
            ],
            "healthy": [
                "How many clients is this device serving?",
                "What firmware version is running?",
                "What is the uplink port/speed?",
            ],
        },
        "truenas": {
            "error": [
                "Which drive failed in this pool?",
                "Can the pool be repaired with a spare?",
                "Is there a recent scrub result?",
            ],
            "degraded": [
                "What is the current usage percentage?",
                "Are there any failed drives?",
                "When was the last scrub completed?",
            ],
            "healthy": [
                "How much free space remains?",
                "When is the next scrub scheduled?",
                "What datasets use this pool?",
            ],
        },
        "pbs": {
            "error": [
                "Which backup jobs are failing?",
                "Is the datastore full?",
                "What does the task log show?",
            ],
            "degraded": [
                "What percentage of space is used?",
                "Are there any failed backup tasks?",
                "When was garbage collection last run?",
            ],
            "healthy": [
                "How many snapshots are stored?",
                "When was the last successful backup?",
                "What is the retention policy?",
            ],
        },
        "fortigate": {
            "error": [
                "Which interface is down?",
                "Is this the WAN or LAN interface?",
                "Are there error counters on the port?",
            ],
            "degraded": [
                "How many errors are on this interface?",
                "Is this affecting routing?",
                "Is HA failover active?",
            ],
            "healthy": [
                "What traffic is passing through this interface?",
                "What VLANs are on this interface?",
                "Is this interface in an HA pair?",
            ],
        },
    }

    # Section-level fallbacks when no platform match
    section_suggestions: dict[str, dict[str, list[str]]] = {
        "STORAGE": {
            "error": ["Is this affecting backup jobs?", "What happens when storage is full?"],
            "degraded": ["What is the usage threshold for this storage?", "Is data at risk?"],
            "healthy": ["What services depend on this storage?", "What is the retention policy?"],
        },
        "COMPUTE": {
            "error": ["What services depend on this component?", "Is there a failover option?"],
            "degraded": ["Is resource exhaustion causing this?", "How does this affect other services?"],
            "healthy": ["What is the normal resource usage?", "When was this last restarted?"],
        },
        "NETWORK": {
            "error": ["What services are affected by this?", "Is there a redundant path?"],
            "degraded": ["What traffic is impacted?", "What services depend on this?"],
            "healthy": ["What services use this network path?", "What is the expected latency?"],
        },
        "SECURITY": {
            "error": ["Are there active threats detected?", "What logs should I check?"],
            "degraded": ["What alert thresholds are configured?", "Is monitoring coverage reduced?"],
            "healthy": ["What events are being monitored?", "What alert rules are active?"],
        },
        "PLATFORM": {
            "error": ["Is this blocking other services?", "What depends on this platform component?"],
            "degraded": ["Is response latency acceptable?", "What would cause further degradation?"],
            "healthy": ["What does this component do?", "What would cause this to degrade?"],
        },
    }

    # Pick suggestions: platform-specific → section fallback → generic
    plat = platform.lower() if platform else ""
    stat = status.lower() if status else "healthy"

    if plat in platform_suggestions and stat in platform_suggestions[plat]:
        suggestions = platform_suggestions[plat][stat]
    elif section in section_suggestions and stat in section_suggestions[section]:
        suggestions = section_suggestions[section][stat]
    elif stat == "error":
        suggestions = ["What caused this failure?", "What should I check first?", "Is there a recovery procedure?"]
    elif stat == "degraded":
        suggestions = ["What is causing this degradation?", "How serious is this?", "What are the fix steps?"]
    elif stat == "maintenance":
        suggestions = ["Why is this in maintenance?", "What work is being done?", "When will it be restored?"]
    else:
        suggestions = ["What does this component do?", "What would cause this to degrade?"]

    return {"suggestions": suggestions[:4]}
```

---

## Version bump
Update VERSION: 2.26.4 → 2.26.5

## Commit
```bash
git add -A
git commit -m "feat(drawer): v2.26.5 Ask token limit 300→600, platform-aware suggestions"
git push origin main
```
