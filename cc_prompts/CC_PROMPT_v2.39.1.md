# CC PROMPT — v2.39.1 — feat(facts): UniFi + FortiGate fact extractors

## What this does

Adds fact extractors for UniFi and FortiGate — the two most commonly
queried network platforms in agent tasks. Neither writes to known_facts today.
After this, preflight and external AI can ground network queries with
real device reachability, client counts, and interface status.

Two-part change per platform:
1. Add extractor functions to `api/facts/extractors.py`
2. Wire into respective collectors

Version bump: 2.39.0 → 2.39.1.

---

## Change 1 — `api/facts/extractors.py` — add UniFi + FortiGate extractors

Append after `extract_facts_from_vm_hosts_snapshot`:

```python
def extract_facts_from_unifi_snapshot(snapshot: dict,
                                       connection_label: str = "") -> list[dict]:
    """UniFi collector snapshot → fact list.

    Snapshot shape varies by collector version — look for common fields:
    devices: [{mac, name, model, state, ip, ap_count}]
    clients: count or list
    health: str
    Key format: prod.unifi.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    label = connection_label or "default"
    fkey_base = f"prod.unifi.{label}"
    md = {"connection": label}

    # Overall health
    _add(facts, f"{fkey_base}.health", "unifi_collector",
         snapshot.get("health", snapshot.get("status")), md)

    # Client count (may be int or len of list)
    clients = snapshot.get("clients") or snapshot.get("client_count")
    if isinstance(clients, list):
        _add(facts, f"{fkey_base}.client_count", "unifi_collector", len(clients), md)
    elif isinstance(clients, int):
        _add(facts, f"{fkey_base}.client_count", "unifi_collector", clients, md)

    # Device states
    devices = snapshot.get("devices") or []
    total = len(devices)
    connected = sum(1 for d in devices
                    if isinstance(d, dict) and d.get("state") in (1, "connected", "online"))
    if total:
        _add(facts, f"{fkey_base}.device_count", "unifi_collector", total, md)
        _add(facts, f"{fkey_base}.devices_connected", "unifi_collector", connected, md)

    # Per-device facts (APs and switches by MAC)
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        mac = (dev.get("mac") or "").replace(":", "").lower()
        dname = dev.get("name") or mac
        if not mac and not dname:
            continue
        key = mac or dname.replace(" ", "_").lower()
        dfkey = f"prod.unifi.device.{key}"
        dmd = {"name": dname, "model": dev.get("model"), "connection": label}
        state_raw = dev.get("state")
        state_str = "connected" if state_raw in (1, "connected", "online") else "disconnected"
        _add(facts, f"{dfkey}.state", "unifi_collector", state_str, dmd)
        if dev.get("ip"):
            _add(facts, f"{dfkey}.ip", "unifi_collector", dev["ip"], dmd)
        if dev.get("model"):
            _add(facts, f"{dfkey}.model", "unifi_collector", dev["model"], dmd)

    return facts


def extract_facts_from_fortigate_snapshot(snapshot: dict,
                                           connection_label: str = "") -> list[dict]:
    """FortiGate collector snapshot → fact list.

    Snapshot shape: {health, hostname, version, interfaces: [{name, status,
    ip, speed, rx_errors, tx_errors}], policies_count, vpn_tunnels, ...}
    Key format: prod.fortigate.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    label = connection_label or snapshot.get("hostname") or "default"
    fkey_base = f"prod.fortigate.{label}"
    md = {"connection": label}

    _add(facts, f"{fkey_base}.health", "fortigate_collector",
         snapshot.get("health", snapshot.get("status")), md)
    if snapshot.get("hostname"):
        _add(facts, f"{fkey_base}.hostname", "fortigate_collector",
             snapshot["hostname"], md)
    if snapshot.get("version"):
        _add(facts, f"{fkey_base}.version", "fortigate_collector",
             snapshot["version"], md)
    if snapshot.get("serial"):
        _add(facts, f"{fkey_base}.serial", "fortigate_collector",
             snapshot["serial"], md)

    # Interface status — most useful for agent network tasks
    for iface in snapshot.get("interfaces") or []:
        if not isinstance(iface, dict):
            continue
        iname = iface.get("name")
        if not iname:
            continue
        ifkey = f"prod.fortigate.{label}.iface.{iname}"
        imd = {"connection": label}
        _add(facts, f"{ifkey}.status", "fortigate_collector",
             iface.get("status") or iface.get("link"), imd)
        if iface.get("ip"):
            _add(facts, f"{ifkey}.ip", "fortigate_collector", iface["ip"], imd)
        rx_err = iface.get("rx_errors") or iface.get("rx_error")
        if rx_err is not None:
            _add(facts, f"{ifkey}.rx_errors", "fortigate_collector", rx_err, imd)

    # VPN tunnel count
    vpn = snapshot.get("vpn_tunnels")
    if isinstance(vpn, list):
        _add(facts, f"{fkey_base}.vpn_tunnel_count", "fortigate_collector",
             len(vpn), md)
    elif isinstance(vpn, int):
        _add(facts, f"{fkey_base}.vpn_tunnel_count", "fortigate_collector",
             vpn, md)

    return facts
```

---

## Change 2 — wire UniFi extractor

Find the UniFi collector file. It is likely at `api/collectors/unifi.py`.
CC: grep for `def poll` or `def _collect_sync` and find where it returns
the snapshot dict. Wrap the return the same way as the kafka pattern:

```python
        # v2.39.1: best-effort fact extraction
        try:
            from api.facts.extractors import extract_facts_from_unifi_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            _conn_label = getattr(self, "_connection_label", "") or ""
            facts = extract_facts_from_unifi_snapshot(snapshot, _conn_label)
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="unifi_collector", action=action
                    ).inc(count)
        except Exception as _fe:
            log.warning("Fact extraction failed for unifi: %s", _fe)
```

If the UniFi collector does not have a single snapshot return point (it may
produce per-connection results), wire it after each individual connection
result is assembled, passing the connection label.

If there is no dedicated `api/collectors/unifi.py` (UniFi may be probed via
external_services), skip this change — external_services extractor (v2.39.0)
already handles unifi reachability. Note this in the commit message.

---

## Change 3 — wire FortiGate extractor

Find the FortiGate collector file (`api/collectors/fortigate.py`).
Apply the same pattern as Change 2, substituting
`extract_facts_from_fortigate_snapshot` and `source="fortigate_collector"`.

If there is no dedicated FortiGate collector (FortiGate may be probed via
external_services only), skip and note in commit message.

---

## Version bump

Update `VERSION` file: `2.39.0` → `2.39.1`

---

## Commit

```
git add -A
git commit -m "feat(facts): v2.39.1 UniFi + FortiGate fact extractors"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
