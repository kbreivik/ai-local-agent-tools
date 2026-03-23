# api/agents/gate_rules.py
"""Service-aware gate rules for the step orchestrator.

Each rule is a pure function: (facts: dict) -> tuple[str, str]
where str is verdict ("GO" | "ASK" | "HALT") and str is a human-readable message.

Facts are structured data extracted from observe-step results, not LLM prose.
"""


def kafka_rolling_restart(facts: dict) -> tuple[str, str]:
    """Gate rule for Kafka rolling broker restart."""
    brokers_up    = facts.get("brokers_up", 0)
    brokers_total = facts.get("brokers_total", 0)
    min_isr       = facts.get("min_isr", 0)
    rf            = facts.get("replication_factor", 3)

    if brokers_total == 0:
        return "ASK", "Could not determine broker count. Proceed with caution?"

    if brokers_up < brokers_total:
        offline = brokers_total - brokers_up
        return "HALT", (
            f"{offline}/{brokers_total} broker(s) offline. "
            "Rolling restart requires all brokers up. Fix offline brokers first."
        )

    if min_isr < rf - 1:
        return "HALT", (
            f"Min ISR ({min_isr}) is below RF-1 ({rf - 1}). "
            "Topics are already under-replicated. A restart would worsen replication."
        )

    return "GO", f"All {brokers_total} brokers up, ISR healthy. Safe to restart one at a time."


def swarm_service_upgrade(facts: dict) -> tuple[str, str]:
    """Gate rule for Docker Swarm service upgrade."""
    managers_up    = facts.get("managers_up", 0)
    managers_total = facts.get("managers_total", 0)

    if managers_total == 0:
        return "ASK", "Could not determine swarm manager count. Proceed?"

    quorum = (managers_total // 2) + 1
    if managers_up < quorum:
        return "HALT", (
            f"Only {managers_up}/{managers_total} managers up. "
            f"Swarm needs {quorum} for quorum. "
            "Service upgrade would disrupt orchestration."
        )

    return "GO", f"Swarm quorum maintained ({managers_up}/{managers_total} managers)."


def changelog_check(facts: dict) -> tuple[str, str]:
    """Gate rule for version upgrades — checks ingested changelogs."""
    ingested      = facts.get("changelog_ingested", False)
    from_ver      = facts.get("from_version", "unknown")
    to_ver        = facts.get("to_version", "unknown")
    breaking      = facts.get("breaking_changes", [])

    if not ingested:
        return "ASK", (
            f"No changelog ingested for {to_ver} (upgrading from {from_ver}). "
            "Breaking changes unknown."
        )

    if breaking:
        preview = "; ".join(breaking[:2])
        return "ASK", f"{len(breaking)} breaking change(s) in {to_ver}: {preview}"

    return "GO", f"Changelog for {to_ver} ingested — no breaking changes found."


# ── Rule registry ─────────────────────────────────────────────────────────────

_RULES: dict = {
    "kafka_rolling_restart": kafka_rolling_restart,
    "swarm_service_upgrade": swarm_service_upgrade,
    "changelog_check":       changelog_check,
}


def evaluate(rule_name: str, facts: dict) -> dict:
    """Evaluate a gate rule by name. Returns {"verdict": str, "message": str}."""
    fn = _RULES.get(rule_name)
    if not fn:
        return {"verdict": "GO", "message": f"No gate rule defined for '{rule_name}'."}
    verdict, message = fn(facts)
    return {"verdict": verdict, "message": message}


def list_rules() -> list[str]:
    """Return names of all registered gate rules."""
    return list(_RULES.keys())
