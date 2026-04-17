# CC PROMPT — v2.34.10 — feat(vm_exec): read-only network diagnostic commands + safe pipe support

## Evidence

Live trace 2026-04-17 16:21. Sub-agent diagnosed Logstash→Kafka timeouts via
docker logs, then tried to **verify** connectivity with:

```
step 5: vm_exec 'docker exec f3ef70283135 nc -zv 192.168.199.33 9094 2>&1 | head -5'
        → error: Shell metacharacters not allowed

step 6: vm_exec 'docker exec f3ef70283135 nc -zv 192.168.199.33 9094'
        → blocked: Command segment not in allowlist. Call vm_exec_allowlist_request()
```

The agent did exactly the right thing — verify the connectivity hypothesis
with a real port test — and was blocked twice. `nc`, `netstat`, `ss`, `curl`
(with read-only flags) are standard diagnostic primitives. Every serious
investigate or execute task will eventually need them. Forcing the agent to
`vm_exec_allowlist_request()` each time means every new deploy requires
manual approval for the same trivially-safe commands.

Two coupled fixes:

1. **Expand the default allowlist** with a `network_diagnostics` group:
   `nc -zv`, `nc -vz`, `netstat`, `ss`, `curl --head`, `curl -I`,
   `curl -o /dev/null`, `ping -c`, `host`, `dig`, `nslookup`, `traceroute`,
   `mtr -r -c`, `tracepath`. All read-only. All bounded by a count
   argument so they can't run forever. Each entry in the allowlist with
   `blast_radius: none` (per v2.33.6).

2. **Safe pipe passthrough** for a whitelist of trailing operations:
   `| head`, `| tail`, `| grep`, `| wc`, `| sort | uniq`, `2>&1`. These
   don't change semantics; they just trim output. The existing
   `_validate_command` from v2.23.3 currently blocks the whole call on any
   shell metacharacter — that's overkill for output filtering. Parse the
   command, if everything before the first `|` or `2>&1` is allowlisted AND
   everything after is from the pipe-safelist, allow.

Version bump: 2.34.9 → 2.34.10

---

## Change 1 — api/db/vm_exec_allowlist.py — seed the network diagnostics group

Add to the base seed (or migration that adds the rows):

```python
NETWORK_DIAGNOSTIC_COMMANDS = [
    # (pattern, description, blast_radius)
    ("nc -zv", "port probe (read-only)", "none"),
    ("nc -vz", "port probe (read-only)", "none"),
    ("netstat -tuln", "socket listing (read-only)", "none"),
    ("netstat -an", "socket listing (read-only)", "none"),
    ("ss -tuln", "socket listing (read-only)", "none"),
    ("ss -an", "socket listing (read-only)", "none"),
    ("curl --head", "HTTP HEAD probe (read-only)", "none"),
    ("curl -I", "HTTP HEAD probe (read-only)", "none"),
    ("curl -o /dev/null -s -w", "HTTP response timing (read-only)", "none"),
    ("ping -c", "ICMP with count limit", "none"),
    ("host ", "DNS resolution", "none"),
    ("dig ", "DNS query", "none"),
    ("nslookup ", "DNS resolution", "none"),
    ("traceroute -m", "route trace with hop limit", "none"),
    ("mtr -r -c", "packet report with count", "none"),
    ("tracepath ", "path MTU discovery", "none"),

    # docker exec variants — safe read-only forms
    ("docker exec .* nc -zv", "port probe inside container", "none"),
    ("docker exec .* nc -vz", "port probe inside container", "none"),
    ("docker exec .* netstat -tuln", "socket listing inside container", "none"),
    ("docker exec .* netstat -an", "socket listing inside container", "none"),
    ("docker exec .* ss -tuln", "socket listing inside container", "none"),
    ("docker exec .* ss -an", "socket listing inside container", "none"),
    ("docker exec .* cat /etc/resolv.conf", "DNS config inside container", "none"),
    ("docker exec .* ip addr", "network interfaces inside container", "none"),
    ("docker exec .* ip route", "route table inside container", "none"),
]
```

Each row gets added to the allowlist table with `group='network_diagnostics'`,
`enabled=True`, `blast_radius='none'`. Existing allowlist rows untouched.

## Change 2 — api/mcp_server/tools/vm.py::_validate_command — safe pipe parsing

The current `_validate_command` (from v2.23.3) likely does something like:

```python
def _validate_command(cmd: str) -> tuple[bool, str]:
    if any(c in cmd for c in "|;&<>`$"):
        return False, "Shell metacharacters not allowed"
    ...
```

Replace with a parser that handles a limited safelist of pipes:

```python
PIPE_SAFELIST = {
    "head",            # may have -N or --lines=
    "tail",
    "grep",            # text match only, no file arg
    "wc",
    "sort",
    "uniq",
    "awk",             # read-only awk — we detect and warn but allow
    "sed",             # only for s/X/Y/ style replacement of output
    "cut",
    "tr",
}

# Redirection safelist
REDIRECT_SAFELIST = {
    "2>&1",            # merge stderr into stdout (very common)
    "> /dev/null",     # discard output
    "2> /dev/null",    # discard stderr
}


def _split_pipeline(cmd: str) -> list[str]:
    """Split a shell command on `|` respecting quoted strings.

    Returns list of pipeline stages. Trailing `2>&1` or `> /dev/null` is
    attached to the last stage.
    """
    # Strip trailing redirects first (they don't split the pipeline)
    cmd_stripped = cmd.strip()
    for redir in REDIRECT_SAFELIST:
        if cmd_stripped.endswith(redir):
            cmd_stripped = cmd_stripped[: -len(redir)].rstrip()
            break

    stages = []
    current = []
    in_quote = None
    for ch in cmd_stripped:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
        elif ch == "|":
            stages.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    stages.append("".join(current).strip())
    return stages


def _validate_command(cmd: str) -> tuple[bool, str | None]:
    # Dangerous characters that never have a safe use in vm_exec
    if any(c in cmd for c in ";&`$<"):
        return False, "Shell metacharacters not allowed: ; & ` $ <"

    stages = _split_pipeline(cmd)
    if not stages:
        return False, "Empty command"

    # Stage 0 — the actual command — must match the allowlist
    ok, reason = _check_allowlist(stages[0])
    if not ok:
        return False, reason

    # Remaining stages — each must be a safelisted pipe
    for idx, stage in enumerate(stages[1:], start=1):
        cmd_head = stage.split()[0] if stage.split() else ""
        if cmd_head not in PIPE_SAFELIST:
            return False, f"Pipe stage {idx} uses disallowed command: {cmd_head!r}. Allowed: {sorted(PIPE_SAFELIST)}"
        # For grep/awk/sed: forbid `-f file` flags that read files
        if cmd_head in ("grep", "awk", "sed") and " -f " in stage:
            return False, f"{cmd_head} -f (file argument) not allowed in pipe"

    return True, None
```

## Change 3 — agent prompt update

In `RESEARCH_PROMPT` (investigate) and `ACTION_PROMPT` (execute), add a
section about network diagnostics:

```
═══ NETWORK DIAGNOSTICS ═══
For connectivity / port / DNS verification, these commands are allowlisted
and read-only. Use them when you need to confirm a networking hypothesis:

  nc -zv <host> <port>              port probe
  netstat -tuln | grep <port>       local listeners
  ss -tuln                          local listeners (faster)
  curl -I http://<host>:<port>/     HTTP HEAD probe
  ping -c 3 <host>                  ICMP (always bounded by count)
  dig <hostname>                    DNS query
  host <hostname>                   DNS (short form)

Inside containers:
  docker exec <id> nc -zv <host> <port>
  docker exec <id> netstat -tuln

Safe pipes are supported for output trimming: `| head`, `| tail`, `| grep`,
`| wc`, `2>&1`. Do NOT use `;`, `&`, `` ` ``, `$( )`, or `<`.
```

## Change 4 — audit counter

Add Prometheus counter for pipeline usage so we can see how often pipes
are used and whether any new patterns emerge:

```python
VM_EXEC_PIPE_COUNTER = Counter(
    "deathstar_vm_exec_pipe_usage_total",
    "vm_exec calls that use a safe pipe stage",
    ["pipe_stage"],  # head | tail | grep | wc | ...
)
```

Increment once per stage per call.

## Change 5 — tests

`tests/test_vm_exec_network_diagnostics.py`:

```python
def test_nc_port_probe_allowed():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("nc -zv 192.168.199.33 9094")
    assert ok is True

def test_docker_exec_nc_allowed():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("docker exec abc123 nc -zv 192.168.199.33 9094")
    assert ok is True

def test_pipe_head_allowed():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("nc -zv 192.168.199.33 9094 2>&1 | head -5")
    assert ok is True

def test_pipe_grep_allowed():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("netstat -tuln | grep 9094")
    assert ok is True

def test_dangerous_chars_still_blocked():
    from mcp_server.tools.vm import _validate_command
    ok, reason = _validate_command("nc -zv host 9094; rm -rf /")
    assert ok is False
    assert ";" in reason or "metacharacter" in reason.lower()

def test_grep_with_file_arg_blocked():
    """grep -f FILE could read arbitrary files."""
    from mcp_server.tools.vm import _validate_command
    ok, reason = _validate_command("netstat -tuln | grep -f /etc/passwd")
    assert ok is False
    assert "-f" in reason

def test_command_substitution_blocked():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("nc -zv $(cat /etc/hostname) 9094")
    assert ok is False

def test_pipe_to_unknown_command_blocked():
    from mcp_server.tools.vm import _validate_command
    ok, reason = _validate_command("nc -zv host 9094 | tee /tmp/out")
    assert ok is False
    assert "tee" in reason

def test_ping_with_count_allowed():
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("ping -c 3 192.168.199.33")
    assert ok is True
```

## Version bump
Update `VERSION`: 2.34.9 → 2.34.10

## Commit
```
git add -A
git commit -m "feat(vm_exec): v2.34.10 read-only network diagnostics allowlist + safe pipe support"
git push origin main
```

## How to test after push
1. Redeploy.
2. Re-run the Logstash investigate task. When sub-agent reaches the
   connectivity-check step, `vm_exec 'docker exec <id> nc -zv 192.168.199.33 9094 2>&1 | head -5'`
   should now execute and return actual output — confirming or refuting
   the Kafka broker 3 timeout theory.
3. Manual test from vm_exec playground:
   - `nc -zv 192.168.199.33 9094` → works
   - `netstat -tuln | grep 9094` → works
   - `nc -zv host 9094; rm -rf /` → blocked (semicolon)
   - `nc -zv $(cat /etc/passwd) 9094` → blocked (command substitution)
4. Check Prometheus: `deathstar_vm_exec_pipe_usage_total{pipe_stage="head"}`
   increments when the first pipe-using call runs.
5. Regression: existing vm_exec allowlist entries still work; non-network
   commands still go through the normal allowlist flow.
