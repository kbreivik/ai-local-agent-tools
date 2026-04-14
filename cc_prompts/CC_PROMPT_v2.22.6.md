# CC PROMPT — v2.22.6 — Agent host IP setting + clickable container endpoints

## What this does
Adds an `agentHostIp` setting (Infrastructure tab → Docker/Swarm) so the LAN IP of
agent-01 can be configured via the UI rather than only via env var. The docker_agent01
collector reads this setting at poll time, so `ip_port` on container cards reflects the
real reachable IP (`192.168.199.10:8000`) instead of `127.0.0.1`. The container card
expanded view gains a clickable endpoint link built from `ip_port`, and the internal
Docker network IPs are demoted to a dimmer secondary "int.ips" row.
Version bump: 2.22.5 → 2.22.6

---

## Change 1 — api/routers/settings.py

In `SETTINGS_KEYS`, add `agentHostIp` after the `agentDockerHost` entry:

```python
    "agentDockerHost":       {"env": "AGENT01_DOCKER_HOST",    "sens": False, "default": ""},
    "agentHostIp":           {"env": "AGENT01_IP",             "sens": False, "default": ""},
```

---

## Change 2 — api/collectors/docker_agent01.py

Replace the module-level constant:
```python
VM_IP = os.environ.get("AGENT01_IP", "127.0.0.1")
```

With a function that checks the settings DB first, then env var, then falls back:
```python
def _get_agent01_ip() -> str:
    """Resolve the LAN IP of agent-01.

    Priority:
      1. Settings DB key 'agentHostIp' (set via UI Infrastructure tab)
      2. AGENT01_IP env var
      3. docker_host connection's host field (if it's a plain IP, not unix://)
      4. '127.0.0.1' fallback
    """
    # 1. Settings DB
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("agentHostIp")
        if val and str(val).strip() and str(val).strip() not in ("", "127.0.0.1"):
            return str(val).strip()
    except Exception:
        pass
    # 2. Env var
    env_val = os.environ.get("AGENT01_IP", "")
    if env_val and env_val not in ("", "127.0.0.1"):
        return env_val
    # 3. docker_host connection host
    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("docker_host")
        local = [c for c in conns
                 if (c.get("config") or {}).get("role") == "standalone"
                 or c.get("label", "").lower() in ("agent-01", "local", "self")]
        if local:
            h = local[0].get("host", "")
            # Only use if it looks like a plain IP (not unix://)
            if h and not h.startswith("unix://") and not h.startswith("/"):
                # Strip tcp:// prefix if present
                h = h.replace("tcp://", "").split(":")[0]
                if h and h != "127.0.0.1":
                    return h
    except Exception:
        pass
    # 4. Fallback
    return os.environ.get("AGENT01_IP", "127.0.0.1")
```

Then in `_collect_sync`, replace the single usage of `VM_IP`:
- Where `ip_port = f"{VM_IP}:{first_port}" if first_port else ""`
  → change to `vm_ip = _get_agent01_ip()` at the top of `_collect_sync` and use `vm_ip` everywhere `VM_IP` was used.

Also update the return dict to include `agent01_ip` from `vm_ip`:
```python
return {
    "health": overall,
    "containers": cards,
    "agent01_ip": vm_ip,
    ...
}
```

Remove the top-level `VM_IP = os.environ.get("AGENT01_IP", "127.0.0.1")` line entirely.

---

## Change 3 — gui/src/components/OptionsModal.jsx

In `InfrastructureTab`, in the Docker/Swarm section, add the `agentHostIp` field
**after** the existing `agentDockerHost` field:

```jsx
<Field label="Agent Host IP" hint="LAN IP of the agent-01 VM — used for clickable container endpoint links (e.g. 192.168.199.10)">
  <TextInput value={draft.agentHostIp} onChange={v => update('agentHostIp', v)} placeholder="192.168.199.10" />
</Field>
```

---

## Change 4 — gui/src/components/ServiceCards.jsx

In `ContainerCardExpanded`, update the network/IP display block.

Find the current block:
```jsx
      {/* Docker networks */}
      {c.networks?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">networks </span>
          {c.networks.join(' · ')}
        </div>
      )}
      {/* All IP addresses */}
      {c.ip_addresses?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">ips </span>
          {c.ip_addresses.join(' · ')}
        </div>
      )}
```

Replace with:
```jsx
      {/* Reachable endpoint — from ip_port (VM LAN IP + host port) */}
      {(() => {
        const ep = c.ip_port ? _displayIp(c.ip_port) : ''
        if (!ep) return null
        const href = ep.includes(':') ? `http://${ep}` : `http://${ep}`
        return (
          <div className="text-[10px] font-mono mb-1.5">
            <span className="text-[9px] text-gray-700">endpoint </span>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#00c8ee] hover:underline"
              onClick={e => e.stopPropagation()}
            >
              {ep}
            </a>
          </div>
        )
      })()}
      {/* Docker networks */}
      {c.networks?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">networks </span>
          {c.networks.join(' · ')}
        </div>
      )}
      {/* Internal Docker IPs — dimmed, secondary info */}
      {c.ip_addresses?.length > 0 && (
        <div className="text-[10px] text-gray-700 font-mono mb-1.5">
          <span className="text-[9px] text-gray-800">int.ips </span>
          {c.ip_addresses.join(' · ')}
        </div>
      )}
```

---

## Version bump

Update `VERSION`: `2.22.5` → `2.22.6`

---

## Commit

```
git add -A
git commit -m "feat(containers): agentHostIp setting + clickable endpoint on container cards"
git push origin main
```
