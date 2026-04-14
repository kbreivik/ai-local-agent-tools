# CC PROMPT — v2.23.0 — Fix VM host reboot + Proxmox action credential bugs

## What this does
Two silent failures fixed: (1) `_vm_ssh_exec` in dashboard.py ignores credential profiles,
so reboot/update actions on vm_host connections that use shared credential profiles fail
silently — fixed by using `_resolve_credentials` from the vm_hosts collector.
(2) `_do_proxmox_action` imports a `NODES` constant that does not exist in proxmox_vms.py,
causing an ImportError on every Proxmox VM power action — fixed by removing the NODES check
and rewriting to use proxmoxer + the connection DB directly.
Version bump: 2.22.6 → 2.23.0

---

## Change 1 — api/routers/dashboard.py: Fix `_vm_ssh_exec`

Find and replace the entire `_vm_ssh_exec` function:

```python
def _vm_ssh_exec(conn, command):
    """Execute a command on a VM via SSH.

    Uses the full credential resolution chain (own creds → profile → shared fallback)
    and jump host routing, identical to the collector. This ensures vm_host connections
    that use credential profiles work correctly for reboot/update actions.
    """
    from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
    from api.connections import get_all_connections_for_platform

    try:
        all_conns = get_all_connections_for_platform("vm_host")
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"ok": False, "error": f"Credential resolution failed: {e}"}

    host = conn.get("host", "")
    port = conn.get("port") or 22
    try:
        out = _ssh_run(
            host, port, username, password, private_key, command,
            jump_host=jump_host,
            _log_meta={
                "connection_id": str(conn.get("id", "")),
                "resolved_label": conn.get("label", host),
                "triggered_by": "vm_action",
            },
        )
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

---

## Change 2 — api/routers/dashboard.py: Fix `_do_proxmox_action`

Find and replace the entire `_do_proxmox_action` function. The current version imports
a non-existent `NODES` constant and reads raw env vars. Replace with proxmoxer + connection DB:

```python
def _do_proxmox_action(pve_type: str, node: str, vmid: int, action: str) -> dict:
    """Execute a Proxmox VM/LXC action (start/stop/reboot/shutdown) via proxmoxer.

    pve_type: 'qemu' for VMs, 'lxc' for containers.
    Reads Proxmox credentials from the connections DB (first proxmox connection).
    Falls back to env vars if no DB connection configured.
    """
    try:
        from proxmoxer import ProxmoxAPI
        from api.connections import get_connection_for_platform
    except ImportError as e:
        return {"ok": False, "error": f"proxmoxer not available: {e}"}

    # Resolve credentials — DB first, env var fallback
    conn = None
    try:
        conn = get_connection_for_platform("proxmox")
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
        # Support both PROXMOX_TOKEN_ID (user@pve!token) and separate vars
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

Also remove the now-unused import line if it exists:
```python
from api.collectors.proxmox_vms import NODES
```
This line should be deleted anywhere it appears in the file (it was inside the old function body).

---

## Change 3 — gui/src/components/VMHostsSection.jsx: Show error feedback on reboot

The `act` function in `VMCard` currently shows `r.output || r.message || 'Done'`.
The reboot route returns `{ok, message, action_id}` with no `output` field, but also
fires a WS event. However if SSH fails, the error is returned in the async task and
never shown. Add explicit error display.

Find the `act` function in VMCard:
```javascript
  const act = async (key, path, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setLoading(l => ({ ...l, [key]: true }))
    setOutput(null)
    try {
      const r = await dashboardAction(path)
      setOutput(r.output || r.message || 'Done')
      if (onAction) setTimeout(onAction, 2000)
    } catch (e) {
      setOutput('Error: ' + String(e))
    }
    setLoading(l => ({ ...l, [key]: false }))
  }
```

Replace with:
```javascript
  const act = async (key, path, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setLoading(l => ({ ...l, [key]: true }))
    setOutput(null)
    try {
      const r = await dashboardAction(path)
      if (r && r.ok === false) {
        setOutput('Error: ' + (r.error || r.message || 'Action failed'))
      } else {
        setOutput(r.output || r.message || 'Done')
        if (onAction) setTimeout(onAction, 2000)
      }
    } catch (e) {
      setOutput('Error: ' + String(e))
    }
    setLoading(l => ({ ...l, [key]: false }))
  }
```

---

## Version bump

Update `VERSION`: `2.22.6` → `2.23.0`

---

## Commit

```
git add -A
git commit -m "fix(vm-actions): credential profile resolution + Proxmox action ImportError"
git push origin main
```
