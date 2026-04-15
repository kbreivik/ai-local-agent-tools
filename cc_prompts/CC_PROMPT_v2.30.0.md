# CC PROMPT — v2.30.0 — fix(proxmox): multi-connection support in Proxmox action paths

## What this does
Two files. `_do_proxmox_action()` in `api/routers/dashboard.py` currently calls
`get_connection_for_platform("proxmox")` — always the first connection — when executing
VM start/stop/reboot actions from the dashboard. In a multi-cluster setup this silently
uses the wrong Proxmox host. Fix: load the `proxmox_vms` snapshot, find which cluster's
VM list contains the target `node`, and use that cluster's `connection_id` to look up the
correct connection. Fall back to first connection if the node isn't found in the snapshot.

`proxmox_vm_power()` in `mcp_server/tools/vm.py` has the same issue. Fix: iterate all
Proxmox connections via `get_all_connections_for_platform("proxmox")`, try each one until
the VM matching `vm_label` is found.
Version bump: v2.29.5 → v2.30.0

---

## Change 1 — api/routers/dashboard.py — `_do_proxmox_action`

Replace the existing `_do_proxmox_action` function with the version below. The logic
change is in the credential resolution block — everything else (action execution, error
handling) stays identical.

```python
def _do_proxmox_action(pve_type: str, node: str, vmid: int, action: str) -> dict:
    """Execute a Proxmox VM/LXC action (start/stop/reboot/shutdown) via proxmoxer.

    pve_type: 'qemu' for VMs, 'lxc' for containers.
    Reads Proxmox credentials from the connections DB — matches the cluster that owns
    the target node. Falls back to first proxmox connection or env vars if needed.
    """
    try:
        from proxmoxer import ProxmoxAPI
        from api.connections import get_connection, get_all_connections_for_platform
    except ImportError as e:
        return {"ok": False, "error": f"proxmoxer not available: {e}"}

    # Resolve credentials — find the connection whose cluster contains the target node.
    conn = None
    try:
        all_conns = get_all_connections_for_platform("proxmox")
        if len(all_conns) == 1:
            conn = all_conns[0]
        elif len(all_conns) > 1:
            # Use the proxmox_vms snapshot to match node → connection_id
            try:
                import asyncio as _asyncio
                import json as _json
                from api.db.base import get_sync_engine
                from sqlalchemy import text as _text
                with get_sync_engine().connect() as _sc:
                    row = _sc.execute(
                        _text("SELECT state FROM status_snapshots WHERE component = 'proxmox_vms' ORDER BY timestamp DESC LIMIT 1")
                    ).fetchone()
                if row:
                    state = row[0]
                    if isinstance(state, str):
                        state = _json.loads(state)
                    for cluster in state.get("clusters", []):
                        all_vms = cluster.get("vms", []) + cluster.get("lxc", [])
                        if any(v.get("node_api") == node or v.get("node") == node for v in all_vms):
                            cid = cluster.get("connection_id")
                            if cid:
                                conn = get_connection(str(cid))
                            break
            except Exception as _e:
                log.debug("_do_proxmox_action: snapshot node-match failed: %s", _e)
            # Fall back to first connection if snapshot match failed
            if not conn:
                conn = all_conns[0]
    except Exception:
        pass

    if conn:
        creds = conn.get("credentials", {}) or {}
        host = conn.get("host", "")
        port = conn.get("port") or 8006
        pve_user = creds.get("user", "")
        token_name = creds.get("token_name", "")
        token_secret = creds.get("secret", "")
    else:
        host = os.environ.get("PROXMOX_HOST", "")
        port = int(os.environ.get("PROXMOX_PORT", "8006"))
        pve_user = os.environ.get("PROXMOX_USER", "")
        token_id_raw = os.environ.get("PROXMOX_TOKEN_ID", "")
        if "!" in token_id_raw:
            pve_user, token_name = token_id_raw.split("!", 1)
        else:
            token_name = token_id_raw
        token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")

    if not host:
        return {"ok": False, "error": "No Proxmox host configured. Add a proxmox connection in Settings → Connections."}

    try:
        prox = ProxmoxAPI(
            host, port=port,
            user=pve_user, token_name=token_name, token_value=token_secret,
            verify_ssl=False, timeout=10,
        )
        endpoint = getattr(prox.nodes(node), pve_type)(vmid).status
        if action == "start":
            task = endpoint.start.post()
        elif action == "stop":
            task = endpoint.stop.post()
        elif action == "reboot":
            task = endpoint.reboot.post()
        elif action == "shutdown":
            task = endpoint.shutdown.post()
        else:
            return {"ok": False, "error": f"Unknown action: {action!r}"}

        log.info("Proxmox %s: %s %s/%s vmid=%d task=%s", action, node, pve_type, action, vmid, task)
        return {"ok": True, "task_id": str(task), "node": node, "vmid": vmid, "action": action}
    except Exception as e:
        log.error("_do_proxmox_action failed: %s", e)
        return {"ok": False, "error": str(e)}
```

---

## Change 2 — mcp_server/tools/vm.py — `proxmox_vm_power`

Replace the credential resolution block inside `proxmox_vm_power` — specifically the
section from the `try:` that imports `get_connection_for_platform` through the `if not conn:`
guard. Replace with `get_all_connections_for_platform` and iterate connections until the
VM is found.

Find this exact block:

```python
    try:
        from api.connections import get_connection_for_platform
        from proxmoxer import ProxmoxAPI

        conn = get_connection_for_platform("proxmox")
        if not conn:
            return {"status": "error",
                    "message": "No Proxmox connection configured.",
                    "data": None, "timestamp": _ts()}

        creds = conn.get("credentials", {})
        pve = ProxmoxAPI(
            conn["host"],
            port=conn.get("port", 8006),
            user=creds.get("user"),
            token_name=creds.get("token_name"),
            token_value=creds.get("secret"),
            verify_ssl=False,
        )

        # Find VM across all nodes by name
        found = None
        for node_info in pve.nodes.get():
            node = node_info["node"]
            for vm in pve.nodes(node).qemu.get():
                name = vm.get("name", "")
                if (vm_label.lower() in name.lower() or
                        name.lower() in vm_label.lower()):
                    found = {"node": node, "vmid": vm["vmid"], "name": name,
                             "status": vm.get("status")}
                    break
            if found:
                break
```

Replace with:

```python
    try:
        from api.connections import get_all_connections_for_platform
        from proxmoxer import ProxmoxAPI

        all_conns = get_all_connections_for_platform("proxmox")
        if not all_conns:
            return {"status": "error",
                    "message": "No Proxmox connection configured.",
                    "data": None, "timestamp": _ts()}

        # Search all Proxmox connections until VM is found
        found = None
        conn = None
        for candidate in all_conns:
            creds = candidate.get("credentials", {})
            try:
                pve = ProxmoxAPI(
                    candidate["host"],
                    port=candidate.get("port", 8006),
                    user=creds.get("user"),
                    token_name=creds.get("token_name"),
                    token_value=creds.get("secret"),
                    verify_ssl=False,
                )
                for node_info in pve.nodes.get():
                    node = node_info["node"]
                    for vm in pve.nodes(node).qemu.get():
                        name = vm.get("name", "")
                        if (vm_label.lower() in name.lower() or
                                name.lower() in vm_label.lower()):
                            found = {"node": node, "vmid": vm["vmid"], "name": name,
                                     "status": vm.get("status")}
                            conn = candidate
                            break
                    if found:
                        break
            except Exception:
                continue
            if found:
                break
```

Also update the `ProxmoxAPI` call that follows the search block — it currently references
`conn["host"]` etc. which still works since `conn` is now set to the matching candidate.
No change needed there.

---

## Version bump
Update `VERSION` in `api/constants.py`: `v2.29.5` → `v2.30.0`

## Commit
```
git add -A
git commit -m "fix(proxmox): v2.30.0 multi-connection support in Proxmox action paths"
git push origin main
```
