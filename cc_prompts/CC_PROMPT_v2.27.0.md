# CC PROMPT — v2.27.0 — Backend: connections credential_state, CSV import/export, Windows platform stub

## What this does
Three backend additions for the credential profiles overhaul:
1. `list_connections()` returns `credential_state` per connection (non-secret: username, profile name,
   has_private_key, has_password) — drives the greyed-out display in the connection form
2. `GET /api/connections/export` and `POST /api/connections/import` — CSV without secrets,
   profile matched by seq_id; import creates connections with `profile_not_found` flag if seq_id missing
3. `windows` platform entry in PLATFORM_AUTH (frontend) + stub collector backend
Version bump: 2.26.10 → 2.27.0

---

## Change 1 — api/connections.py: add credential_state to list_connections

### 1a — After the masking loop in list_connections, add credential_state derivation

FIND (exact):
```
    # Mask credentials in list view
    for r in rows:
        r["credentials"] = "***" if r.get("credentials") else ""
        if r.get("last_seen"):
            try:
                r["last_seen"] = r["last_seen"].isoformat()
            except AttributeError:
                pass  # already a string (SQLite)
        if r.get("created_at"):
            try:
                r["created_at"] = r["created_at"].isoformat()
            except AttributeError:
                pass
        r["id"] = str(r["id"])
    return rows
```

REPLACE WITH:
```
    # Derive credential_state per connection (non-secret) + mask raw credentials
    for r in rows:
        raw_enc = r.get("credentials", "")
        r["credentials"] = "***" if raw_enc else ""
        if r.get("last_seen"):
            try: r["last_seen"] = r["last_seen"].isoformat()
            except AttributeError: pass
        if r.get("created_at"):
            try: r["created_at"] = r["created_at"].isoformat()
            except AttributeError: pass
        r["id"] = str(r["id"])

        # Derive credential_state from config + username_cache
        cfg = r.get("config") or {}
        if isinstance(cfg, str):
            try: cfg = json.loads(cfg)
            except Exception: cfg = {}
        profile_id = cfg.get("credential_profile_id")
        cred_state: dict = {"source": "none", "username": r.get("username_cache", "")}

        if profile_id:
            # Profile-linked: fetch safe fields
            try:
                from api.db.credential_profiles import get_profile_safe
                ps = get_profile_safe(str(profile_id))
                if ps:
                    cred_state = {
                        "source":          "profile",
                        "profile_id":      str(profile_id),
                        "profile_name":    ps.get("name", ""),
                        "profile_seq_id":  ps.get("seq_id"),
                        "username":        ps.get("username", "") or r.get("username_cache", ""),
                        "has_private_key": ps.get("has_private_key", False),
                        "has_passphrase":  ps.get("has_passphrase", False),
                        "has_password":    ps.get("has_password", False),
                    }
                else:
                    cred_state = {
                        "source":       "profile_not_found",
                        "profile_id":   str(profile_id),
                        "profile_name": "",
                        "username":     r.get("username_cache", ""),
                    }
            except Exception:
                cred_state = {"source": "profile_error", "username": r.get("username_cache", "")}
        elif raw_enc:
            # Inline credentials stored
            cred_state = {
                "source":          "inline",
                "username":        r.get("username_cache", ""),
                # We can't know has_private_key/has_password without decrypting in list view.
                # Frontend shows inline-creds warning badge regardless.
                "has_private_key": False,
                "has_password":    bool(raw_enc),
            }
        r["credential_state"] = cred_state

    return rows
```

---

## Change 2 — api/routers/connections.py: add export/import endpoints

Add these two endpoints at the END of the file, before the final newline:

```python

@router.get("/export")
def export_connections(_: str = Depends(get_current_user)):
    """Export all connections as CSV. No secrets included.
    Profile referenced by seq_id (human-readable stable ID).

    Columns: seq_id, platform, label, host, port, role, os_type, jump_via_label
    """
    import csv, io
    from api.connections import list_connections

    all_conns = list_connections()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[
        "profile_seq_id", "platform", "label", "host", "port",
        "role", "os_type", "jump_via_label",
    ], extrasaction="ignore")
    writer.writeheader()
    for c in all_conns:
        cfg = c.get("config") or {}
        if isinstance(cfg, str):
            import json
            try: cfg = json.loads(cfg)
            except Exception: cfg = {}
        cred_state = c.get("credential_state") or {}
        row = {
            "profile_seq_id":  cred_state.get("profile_seq_id", ""),
            "platform":        c.get("platform", ""),
            "label":           c.get("label", ""),
            "host":            c.get("host", ""),
            "port":            c.get("port", ""),
            "role":            cfg.get("role", ""),
            "os_type":         cfg.get("os_type", ""),
            "jump_via_label":  cfg.get("jump_via_label", ""),
        }
        writer.writerow(row)

    from fastapi.responses import Response
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=connections_export.csv"},
    )


@router.post("/import")
def import_connections(req: dict, user_role: tuple = Depends(get_current_user_and_role)):
    """Import connections from CSV data (base64-encoded or raw string).

    Body: { csv_data: "<base64 or raw CSV string>" }

    Profile matched by profile_seq_id column. If seq_id not found:
      - Creates connection with config.profile_not_found = true
      - Reports as warning in results

    Security: all values are validated; no SQL injection possible (parameterised queries).
    Existing connections (same platform+label) are skipped with a 'exists' result.
    """
    import csv, io, base64, re, json
    from api.connections import create_connection
    from api.db.credential_profiles import get_profile_by_seq_id

    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")

    raw = req.get("csv_data", "")
    if not raw:
        raise HTTPException(400, "csv_data required")

    # Attempt base64 decode; fall back to raw string
    try:
        csv_text = base64.b64decode(raw).decode("utf-8")
    except Exception:
        csv_text = raw

    # Validate input length
    if len(csv_text) > 500_000:
        raise HTTPException(400, "CSV too large (max 500KB)")

    reader = csv.DictReader(io.StringIO(csv_text))
    required_cols = {"platform", "label", "host"}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        raise HTTPException(400, f"CSV must contain columns: {required_cols}")

    # Value sanitisation helper — strips control chars, limits length
    _SAFE = re.compile(r'[\x00-\x1f\x7f]')
    def _clean(v: str, max_len: int = 255) -> str:
        return _SAFE.sub("", str(v or ""))[:max_len]

    # Valid platforms (whitelist)
    VALID_PLATFORMS = {
        "proxmox","fortigate","fortiswitch","truenas","pbs","unifi",
        "wazuh","grafana","portainer","kibana","netbox","synology",
        "security_onion","syncthing","caddy","traefik","opnsense",
        "adguard","bookstack","trilium","nginx","pihole","technitium",
        "cisco","juniper","aruba","docker_host","vm_host","elasticsearch",
        "logstash","windows",
    }

    results = []
    for row in reader:
        platform = _clean(row.get("platform", ""))
        label    = _clean(row.get("label", ""))
        host     = _clean(row.get("host", ""))

        if not platform or not label or not host:
            results.append({"label": label or "?", "status": "skip", "reason": "missing required fields"})
            continue
        if platform not in VALID_PLATFORMS:
            results.append({"label": label, "status": "skip", "reason": f"unknown platform: {platform}"})
            continue

        # Parse port safely
        try:
            port = int(_clean(row.get("port", "443"))) if row.get("port") else 443
            if port < 1 or port > 65535:
                port = 443
        except ValueError:
            port = 443

        # Resolve profile by seq_id
        profile_not_found = False
        profile_id = None
        seq_id_raw = _clean(row.get("profile_seq_id", ""))
        if seq_id_raw and seq_id_raw != "0" and seq_id_raw != "":
            try:
                seq_id = int(seq_id_raw)
                if seq_id > 0:
                    prof = get_profile_by_seq_id(seq_id)
                    if prof:
                        profile_id = str(prof["id"])
                    else:
                        profile_not_found = True
            except ValueError:
                profile_not_found = True

        config = {
            "role":    _clean(row.get("role", ""), 50),
            "os_type": _clean(row.get("os_type", ""), 50),
        }
        if profile_id:
            config["credential_profile_id"] = profile_id
        if profile_not_found:
            config["profile_not_found"] = True
        jump_label = _clean(row.get("jump_via_label", ""), 100)
        if jump_label:
            config["_import_jump_label"] = jump_label  # resolved post-import

        result = create_connection(
            platform=platform, label=label, host=host, port=port,
            auth_type="ssh" if platform in ("vm_host", "windows") else "api",
            credentials={}, config=config,
        )
        if result.get("status") == "ok":
            status = "created"
            if profile_not_found:
                status = "created_no_profile"
        elif "UNIQUE constraint" in str(result.get("message", "")) or \
             "duplicate key" in str(result.get("message", "")):
            status = "exists"
        else:
            status = "error"

        results.append({
            "label":             label,
            "status":            status,
            "profile_not_found": profile_not_found,
            "message":           result.get("message", ""),
        })

    ok = sum(1 for r in results if r["status"] in ("created", "created_no_profile"))
    skipped = sum(1 for r in results if r["status"] in ("exists", "skip"))
    errors = sum(1 for r in results if r["status"] == "error")

    return {
        "status": "ok",
        "summary": {"created": ok, "skipped": skipped, "errors": errors},
        "results": results,
    }
```

---

## Change 3 — gui/src/components/OptionsModal.jsx: add windows to PLATFORM_AUTH

FIND (exact):
```
  docker_host:     { auth_type: 'tcp', defaultPort: 2375, fields: [], _dockerHost: true },
  vm_host:         {
```

REPLACE WITH:
```
  docker_host:     { auth_type: 'tcp', defaultPort: 2375, fields: [], _dockerHost: true },
  windows:         {
    auth_type: 'windows', defaultPort: 5985,
    fields: [
      {
        key: 'username', label: 'Username',
        placeholder: 'Administrator or DOMAIN\\user or user@domain.com',
        hint: 'Accepts local\\user, DOMAIN\\user, or user@domain.com — stored as-is, format detected automatically',
      },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    configFields: [
      {
        key: 'winrm_auth_method', label: 'WinRM Auth Method', type: 'select',
        options: [
          { value: 'ntlm',        label: 'NTLM (recommended)' },
          { value: 'kerberos',    label: 'Kerberos (domain)' },
          { value: 'basic',       label: 'Basic (plaintext — HTTPS only)' },
          { value: 'certificate', label: 'Certificate' },
        ],
      },
      {
        key: 'account_type', label: 'Account Type', type: 'select',
        hint: 'Informational — affects lockout risk display and agent behaviour',
        options: [
          { value: 'local',           label: 'Local account' },
          { value: 'domain',          label: 'Domain account' },
          { value: 'service',         label: 'Service account' },
          { value: 'managed_service', label: 'Managed service account (gMSA)' },
        ],
      },
      {
        key: 'use_ssl', label: 'Use SSL (port 5986)', type: 'toggle',
        hint: 'Switches to HTTPS WinRM — strongly recommended for production',
      },
    ],
    advancedConfigFields: [
      { key: 'is_jump_host', label: 'This is a jump host / bastion', type: 'toggle', hint: 'Not polled as a compute node.' },
    ],
  },
  vm_host:         {
```

Also add `'windows'` to the PLATFORMS array:

FIND (exact):
```
const PLATFORMS = [
  'proxmox', 'fortigate', 'fortiswitch', 'truenas', 'pbs', 'unifi',
  'wazuh', 'grafana', 'portainer', 'kibana', 'netbox', 'synology',
  'security_onion', 'syncthing', 'caddy', 'traefik', 'opnsense',
  'adguard', 'bookstack', 'trilium', 'nginx', 'pihole', 'technitium',
  'cisco', 'juniper', 'aruba',
  'docker_host', 'vm_host', 'elasticsearch', 'logstash',
]
```

REPLACE WITH:
```
const PLATFORMS = [
  'proxmox', 'fortigate', 'fortiswitch', 'truenas', 'pbs', 'unifi',
  'wazuh', 'grafana', 'portainer', 'kibana', 'netbox', 'synology',
  'security_onion', 'syncthing', 'caddy', 'traefik', 'opnsense',
  'adguard', 'bookstack', 'trilium', 'nginx', 'pihole', 'technitium',
  'cisco', 'juniper', 'aruba',
  'docker_host', 'vm_host', 'windows', 'elasticsearch', 'logstash',
]
```

---

## Change 4 — api/collectors/windows.py (NEW FILE — stub)

```python
"""WindowsCollector — WinRM-based Windows host monitoring (stub).

Polls connections with platform='windows'. Auth via credential profile
(auth_type='windows'). Full implementation deferred; this stub provides
the collector skeleton so the platform registers in the manager.
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class WindowsCollector(BaseCollector):
    component = "windows"
    platforms = ["windows"]

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("WINDOWS_POLL_INTERVAL", "60"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("windows")
        if not conns:
            return {"health": "unconfigured", "hosts": []}

        hosts = []
        for conn in conns:
            label = conn.get("label") or conn.get("host", "?")
            hosts.append({
                "label":  label,
                "host":   conn.get("host", ""),
                "port":   conn.get("port", 5985),
                "dot":    "grey",
                "status": "stub — WinRM collector not yet implemented",
            })

        return {"health": "unconfigured", "hosts": hosts}

    def to_entities(self, state: dict):
        from api.collectors.base import Entity
        return [
            Entity(
                id=h.get("label", h.get("host", "unknown")),
                label=h.get("label", ""),
                component=self.component,
                platform="windows",
                section="COMPUTE",
                status="unknown",
                metadata={"host": h.get("host", ""), "port": h.get("port", 5985)},
            )
            for h in state.get("hosts", [])
        ] or super().to_entities(state)
```

---

## Change 5 — api/collectors/manager.py: register WindowsCollector

Find the block where all collectors are imported and instantiated. Add WindowsCollector to it.

FIND the import block that contains `DockerAgent01Collector` (exact line context may vary — find the collector import block and add the windows import):

Search for this pattern in manager.py:
```
from api.collectors.vm_hosts import VMHostsCollector
```

Add after that line:
```
from api.collectors.windows import WindowsCollector
```

Then find where VMHostsCollector is instantiated and add WindowsCollector in the same pattern. The manager typically builds a dict of `component → collector_instance`. Add:
```
WindowsCollector(),
```
to the list of collectors passed to the manager (same location as VMHostsCollector instantiation).

NOTE for CC: Read manager.py first to find the exact instantiation pattern, then add WindowsCollector in the same style used for other collectors.

---

## Version bump
Update VERSION: 2.26.10 → 2.27.0

## Commit
```bash
git add -A
git commit -m "feat(connections): v2.27.0 credential_state in list, CSV import/export, Windows platform stub"
git push origin main
```
