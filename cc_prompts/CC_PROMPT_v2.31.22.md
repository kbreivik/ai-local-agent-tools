# CC PROMPT — v2.31.22 — fix(auth): credential resolution priority + passphrase kwarg

## What this does
Two bugs found while debugging elastic-01's "No authentication methods
available" error:

1. **Credential resolution priority bug** — `resolve_credentials_for_connection`
   in `api/db/credential_profiles.py` checks inline credentials FIRST.
   If a connection has a linked profile AND stale inline creds (e.g. just
   `username` with no key), the inline creds win — the profile's private
   key is never loaded. Paramiko gets a username with no key → auth fail.

   Fix: when a `credential_profile_id` is set in config, prefer profile
   creds over inline. Only fall back to inline if no profile is linked.

2. **`passphrase` kwarg bug** — `api/routers/discovery.py` test endpoint
   passes `passphrase=creds.get("passphrase", "")` to `_ssh_run()`, but
   `_ssh_run()` in `api/collectors/vm_hosts.py` doesn't accept that
   parameter. Any profile with `auth_type: "ssh"` (new naming from
   v2.26.10) triggers `TypeError: _ssh_run() got an unexpected keyword
   argument 'passphrase'`.

   Fix: add `passphrase=None` to `_ssh_run` signature and pass it
   through to paramiko's key loading.

Version bump: 2.31.21 → 2.31.22

---

## Change 1 — `api/db/credential_profiles.py` — fix resolution priority

Find `resolve_credentials_for_connection` (near end of file). Current:

```python
def resolve_credentials_for_connection(connection: dict, all_connections: list[dict]) -> dict:
    creds = connection.get('credentials') or {}
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except Exception: creds = {}

    # Has its own credentials
    if creds.get('username') or creds.get('private_key') or creds.get('password'):
        return creds

    # Linked profile
    cfg = connection.get('config') or {}
    if isinstance(cfg, str):
        try: cfg = json.loads(cfg)
        except Exception: cfg = {}
    profile_id = cfg.get('credential_profile_id')
    if profile_id:
        profile = get_profile(profile_id)
        if profile:
            return profile.get('credentials') or {}

    return creds
```

Replace with:

```python
def resolve_credentials_for_connection(connection: dict, all_connections: list[dict]) -> dict:
    """Return effective credentials for a connection.

    Priority:
    1. Linked credential profile (connection.config.credential_profile_id)
       — when a profile is linked, it is the authoritative credential source.
         Inline creds are ignored (they may be stale from before the profile
         was linked).
    2. Connection's own inline credentials (if non-empty key or password)
    3. Empty dict (no credentials available)
    """
    # Check for linked profile FIRST — profile is authoritative when set
    cfg = connection.get('config') or {}
    if isinstance(cfg, str):
        try: cfg = json.loads(cfg)
        except Exception: cfg = {}
    profile_id = cfg.get('credential_profile_id')
    if profile_id:
        profile = get_profile(profile_id)
        if profile:
            profile_creds = profile.get('credentials') or {}
            if isinstance(profile_creds, str):
                try: profile_creds = json.loads(profile_creds)
                except Exception: profile_creds = {}
            if profile_creds.get('username') or profile_creds.get('private_key') or profile_creds.get('password'):
                return profile_creds
            # Profile exists but has no usable creds — log and fall through
            log.warning("resolve_credentials: profile %s linked but has no usable credentials", profile_id)

    # Inline credentials (no profile linked, or profile was empty)
    creds = connection.get('credentials') or {}
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except Exception: creds = {}

    return creds
```

Key change: profile is checked FIRST when `credential_profile_id` is set.
Stale inline creds no longer shadow the profile's key.

---

## Change 2 — `api/collectors/vm_hosts.py` — accept `passphrase` in `_ssh_run`

Find the `_ssh_run` function signature:

```python
def _ssh_run(host, port, username, password, private_key, script,
             jump_host=None, _log_meta=None):
```

Replace with:

```python
def _ssh_run(host, port, username, password, private_key, script,
             jump_host=None, _log_meta=None, passphrase=None):
```

Then find `_make_pkey` inside `_ssh_run`:

```python
    def _make_pkey(key_str):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(io.StringIO(key_str))
            except Exception:
                continue
        raise ValueError("Could not parse private key (tried RSA, Ed25519, ECDSA)")
```

Replace with:

```python
    def _make_pkey(key_str, passphrase=None):
        pw = passphrase if passphrase else None
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(io.StringIO(key_str), password=pw)
            except Exception:
                continue
        raise ValueError("Could not parse private key (tried RSA, Ed25519, ECDSA)")
```

Then update ALL calls to `_make_pkey` inside `_ssh_run` to pass `passphrase`:

In the jump_host branch:
```python
j_transport.auth_publickey(jump_host["username"], _make_pkey(jump_host["private_key"]))
```
→
```python
j_transport.auth_publickey(jump_host["username"], _make_pkey(jump_host["private_key"], jump_host.get("passphrase")))
```

And:
```python
**({"pkey": _make_pkey(private_key)} if private_key else
```
→
```python
**({"pkey": _make_pkey(private_key, passphrase)} if private_key else
```

In the non-jump-host branch:
```python
kw["pkey"] = _make_pkey(private_key)
```
→
```python
kw["pkey"] = _make_pkey(private_key, passphrase)
```

---

## Change 3 — `api/routers/discovery.py` — no change needed

The discovery test already passes `passphrase=creds.get("passphrase", "")`
correctly. Now that `_ssh_run` accepts the kwarg, it will work.

Verify the call looks like this (should already be correct):

```python
out = await asyncio.to_thread(
    _ssh_run, host, port,
    creds.get("username", ""),
    creds.get("password", ""),
    creds.get("private_key", ""),
    "echo deathstar-ok",
    passphrase=creds.get("passphrase", ""),
)
```

No edit needed here — just confirming it's correct.

---

## Version bump

Update VERSION: 2.31.21 → 2.31.22

---

## Commit

```
git add -A
git commit -m "fix(auth): v2.31.22 profile-first credential resolution + passphrase kwarg in _ssh_run"
git push origin main
```

---

## How to test

### Test 1 — credential resolution priority

1. elastic-01 should already be green (inline creds were cleared manually).
   But if any other connection has a linked profile AND stale inline creds,
   it would now also work. Verify:
   ```bash
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/dashboard/summary \
     | python3 -c "import sys,json;d=json.load(sys.stdin);[print(v['label'],v['dot']) for v in d['vm_hosts']['vms']]"
   ```
   All VM hosts should be green (except worker-03 which is still Down).

### Test 2 — passphrase kwarg

1. Use the discovery test with a profile that has `auth_type: "ssh"`:
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST http://192.168.199.10:8000/api/discovery/test \
     -H 'Content-Type: application/json' \
     -d '{"host":"192.168.199.21","port":22,"profile_id":"857a5278-daf8-4f4a-9e0d-ce7ff2bd685a"}'
   ```
   Should return `{"ok": true, "message": "SSH OK"}` instead of the
   `_ssh_run() got an unexpected keyword argument 'passphrase'` error.

### Test 3 — no regression on working connections

1. ds-docker-manager-01 (uses `auto-admin-ai-lab` profile, auth_type
   `ssh_key`) should still connect fine — verify via dashboard or:
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST \
     http://192.168.199.10:8000/api/dashboard/vm-hosts/fb98d83e-ffc6-4660-a82b-fea031dce2f3/exec \
     -H 'Content-Type: application/json' -d '{"command":"uptime"}'
   ```
