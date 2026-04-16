# CC PROMPT — v2.31.17 — fix(windows): swap pywinrm → pypsrp (PSRP over Microsoft.PowerShell endpoint)

## What this does
The v2.31.15/16 Windows collector uses pywinrm. pywinrm's `run_ps()` opens
a WinRS **cmd** shell (resource URI
`http://schemas.microsoft.com/wbem/wsman/1/windows/shell/cmd`) and runs
`powershell -encodedcommand` inside it. That endpoint's default Windows
SDDL is:

```
O:NSG:BAD:P(A;;GA;;;BA)(A;;GR;;;IU)
```

— only Built-in Administrators (full) and Interactive Users (read) are
granted. `Remote Management Users` is absent. The user's `ai-agent` account
is in `Remote Management Users` + `Performance Monitor Users` + `Event Log
Readers` and has Read+Invoke on the `Microsoft.PowerShell`
PSSessionConfiguration — but has no access at all to the WinRS cmd shell.
Result: pywinrm fails at `open_shell()` with `wsmanfault_code: 5` before
any script runs.

We verified this from the live traceback:
```
File ".../winrm/__init__.py", line 44, in run_cmd
    shell_id = self.protocol.open_shell()
File ".../winrm/protocol.py", line 307, in send_message
    raise WSManFaultError(...): Access is denied.
```

**Fix:** swap to **pypsrp**, which uses PSRP over the
`http://schemas.microsoft.com/powershell/Microsoft.PowerShell` endpoint —
the one `ai-agent` already has Invoke on. No Windows-side changes.
Architecturally cleaner too — pypsrp is the maintained library;
pywinrm is in maintenance-only mode.

Three changes. All small.

---

## Change 1 — `requirements.txt`

Remove:
```
pywinrm>=0.5.0
```

Add (alphabetically near `psycopg2-binary`):
```
pypsrp>=0.8.0
```

---

## Change 2 — `api/collectors/windows.py` — swap the transport in `_winrm_run`

Open `api/collectors/windows.py`. Find the `_winrm_run` function (added in
v2.31.15). Replace its entire body with the pypsrp-based implementation.

**Keep the function signature identical** so callers don't change:

```python
def _winrm_run(host, port, username, password, script,
               transport="ntlm", use_ssl=False, read_timeout=30,
               operation_timeout=25):
    """Run a PowerShell script on a Windows host via PSRP (pypsrp).

    Uses the Microsoft.PowerShell endpoint, not WinRS — which means the
    target user only needs Invoke on the PSSessionConfiguration, not
    Execute on the default WinRS cmd shell SDDL.

    Returns stdout str. Raises RuntimeError on PS errors or auth failure.
    """
    from pypsrp.client import Client

    # pypsrp accepts: 'negotiate' (default), 'ntlm', 'kerberos',
    # 'basic', 'certificate', 'credssp'. Keep our accepted set in sync
    # with pypsrp's vocabulary.
    _VALID_AUTH = ("negotiate", "ntlm", "kerberos", "basic", "certificate", "credssp")
    auth = (transport or "ntlm").lower()
    if auth not in _VALID_AUTH:
        auth = "ntlm"

    t0 = time.monotonic()
    log.debug("PSRP exec → %s@%s:%d (%s, ssl=%s) | cmd: %s",
              username, host, port, auth, use_ssl,
              (script or "")[:80].replace("\n", " "))

    client = Client(
        server=host,
        port=port,
        username=username,
        password=password,
        ssl=use_ssl,
        auth=auth,
        cert_validation=False if use_ssl else True,
        read_timeout=read_timeout,
        operation_timeout=operation_timeout,
    )

    try:
        output, streams, had_errors = client.execute_ps(script)
    except Exception as e:
        # pypsrp raises WSManFaultError / AuthenticationError / etc.
        # Normalise to RuntimeError so callers (collector + discovery test)
        # don't need to import pypsrp-specific exception types.
        raise RuntimeError(str(e)) from e
    finally:
        try:
            client.close()
        except Exception:
            pass

    elapsed = int((time.monotonic() - t0) * 1000)
    if had_errors:
        # streams.error is a list of ErrorRecord objects — coerce to strings
        err_text = "\n".join(str(e) for e in (streams.error or []))
        raise RuntimeError(
            f"PowerShell errors ({elapsed}ms): {err_text[:400] or 'had_errors=True, no error records'}"
        )

    log.debug("PSRP exec ← %s@%s:%d | %d bytes | %dms",
              username, host, port, len(output or ""), elapsed)
    return output or ""
```

**Also remove the stale `import winrm` at the top of the file if present.**
The new `_winrm_run` imports pypsrp lazily inside the function, same pattern
we used for pywinrm — avoids hard-failing module load if the runtime image
hasn't been rebuilt yet.

Everything else in the file (the `_POLL_PS` script, `_parse_poll_output`,
`_resolve_winrm_creds`, `_poll_one_host`, the `WindowsCollector` class,
`to_entities`) stays untouched.

---

## Change 3 — `api/routers/discovery.py` — no code change, but verify

The discovery test's Windows branch already calls
`_winrm_run(host, port, username, password, "hostname; Get-Date -Format 'o'", ...)`
via `asyncio.to_thread`. Since we kept the signature identical, this branch
needs no edit. But read it to confirm it's still calling the helper from
`api.collectors.windows` and not importing pywinrm directly.

If the branch has any stray `import winrm` or direct pywinrm usage, remove
those too. The only pywinrm reference in the entire repo should be gone.

Sanity check (CC, run after edits):
```bash
grep -rn "import winrm" api/ mcp_server/ || echo "clean"
grep -rn "pywinrm"      api/ mcp_server/ || echo "clean"
# Both should print "clean"
```

---

## Commit

```
git add -A
git commit -m "fix(windows): v2.31.17 swap pywinrm→pypsrp (use Microsoft.PowerShell endpoint)"
git push origin main
```

---

## How to test

After CI builds and you deploy v2.31.17 on agent-01:

1. **Dep swap worked**:
   ```bash
   docker exec hp1_agent python -c "import pypsrp; print('pypsrp:', pypsrp.__version__)"
   docker exec hp1_agent python -c "import winrm" 2>&1 | head -1
   # pypsrp: 0.8.x
   # ModuleNotFoundError: No module named 'winrm'   ← pywinrm gone, correct
   ```

2. **Discovery test now passes** (uses the PowerShell endpoint — which
   `ai-agent` HAS been granted Invoke on):
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST \
     http://192.168.199.10:8000/api/discovery/test \
     -H 'Content-Type: application/json' \
     -d '{"host":"192.168.199.51","port":5985,"platform":"windows","profile_id":"689b6e18-f538-412b-ba2d-71e1b55ffafd"}' \
     | python3 -m json.tool
   ```
   Expect: `"ok": true, "message": "WinRM OK: MS-S1-SRV-01"`.

3. **Force collector poll and read entity**:
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST \
     http://192.168.199.10:8000/api/collectors/windows/poll
   sleep 5
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/entities \
     | python3 -c "import sys,json;[print(json.dumps(e,indent=2)) for e in json.load(sys.stdin) if e['component']=='windows']"
   ```
   Expect: `status: "healthy"`, real hostname (MS-S1-SRV-01), CPU%, mem%,
   uptime, disks, services map with `WinRM: Running`.

4. **Dashboard**: refresh UI. The WINDOWS section shows a green card for
   MS-S1 with uptime + CPU + mem + disk bar.

5. **Verify no new permissions were needed on MS-S1**:
   ```powershell
   # On MS-S1 — confirm SDDL is unchanged (Remote Management Users still absent)
   (Get-Item WSMan:\localhost\Service\RootSDDL).Value
   # Still: O:NSG:BAD:P(A;;GA;;;BA)(A;;GR;;;IU)S:P(AU;FA;GA;;;WD)(AU;SA;GXGW;;;WD)
   ```

---

## Notes

- **Why pypsrp is the right library**: Microsoft's modern remote management
  model is PSRP (PowerShell Remoting Protocol). WinRS is the older,
  cmd.exe-shell-based path. Every permission tutorial that tells you to
  "grant Remote Management Users Execute on `winrm configsddl default`"
  is working around pywinrm's WinRS choice. pypsrp sidesteps the issue
  entirely by using the PowerShell endpoint where `Invoke` permission is
  the relevant grant — which `New-PSSession` respects out of the box for
  `Remote Management Users`.

- **Slightly larger image**: pypsrp pulls `pyspnego`, `cryptography` (we
  already have it), `requests` (already indirect via docker SDK). Net
  image delta ≈ 5 MB. Acceptable.

- **Kerberos works the same way it did with pywinrm** — needs a valid
  `krb5.conf` in the container. NTLM remains the recommended default
  for LAN.

- **Not in scope for v2.31.17**: the `win_exec` agent tool. That's next —
  now that the collector is proven to work over PSRP, the agent tool is
  a thin wrapper over the same `_winrm_run`.
