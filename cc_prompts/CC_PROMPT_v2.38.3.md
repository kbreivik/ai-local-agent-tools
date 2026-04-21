# CC PROMPT — v2.38.3 — External AI auth 401: use decrypting get_setting

## What this does

Fixes the HTTP 401 auth failure on every external AI escalation since
v2.36.3 shipped. Kent reported: "external ai has auth failed, while
test works". Same provider, same URL, same key — but only the Test
Connection button worked. URLs and headers are correct; this is a
settings-read layer bug.

### Root cause

`externalApiKey` is in `api.settings_manager.SENSITIVE_KEYS`, so every
write path encrypts the value at rest. `set_setting` calls
`encrypt_value(str(value))` before `backend.set_setting(key,
ciphertext)`. The DB therefore holds ciphertext for this key.

Two different read paths exist:

1. **`api.settings_manager.get_setting(key, registry)`** —
   - fetches via `backend.get_setting(key)`,
   - calls `is_encrypted(db_val)`,
   - if True, calls `decrypt_value(db_val)`,
   - returns `{"value": plaintext, "source": "db", "encrypted": True}`.

2. **`backend.get_setting(key)`** (the primitive store accessor from
   `mcp_server/tools/skills/storage.py`) —
   - fetches raw DB value,
   - returns ciphertext unchanged. No decryption.

`api/routers/settings.py::test_external_ai` (v2.35.21) uses path 1.
Test Connection ships the plaintext key → Claude accepts → 200 OK.

`api/agents/external_ai_client.py::synthesize_replace` (v2.36.3) uses
path 2. Production escalation ships the ciphertext string as the
`x-api-key` header → Claude returns HTTP 401 auth_failed → v2.36.3's
`ExternalAIAuthError` fires → v2.36.4's escalation banner raises.
Every external AI call has been broken since v2.36.3 landed.

Evidence:
- v2.35.21 release memo explicitly notes: *Test Connection "falls back
  to the DB-saved externalApiKey via `get_setting("externalApiKey",
  SETTINGS_KEYS)["value"]`"*.
- `api/agents/external_ai_client.py` line ~272: `api_key = (backend
  .get_setting("externalApiKey") or "").strip()` — raw backend call,
  no decryption.
- `api/settings_manager.py::SENSITIVE_KEYS` contains `externalApiKey`.
- Session `6d2219b9` (2026-04-21 12:55 filebeat task) recorded auth
  401 in production path while the Test Connection button for the
  same key/model succeeds seconds earlier on the same request.

URL is not the problem. Provider is not the problem. Model is not
the problem. Only the read layer.

### Fix

Swap the getter in `synthesize_replace`. Use `api.settings_manager
.get_setting(key, SETTINGS_KEYS)["value"]` — the same decrypting path
the Test endpoint uses — instead of `backend.get_setting(key)`.
Single-file change, scoped to the three Settings reads in one
function.

For consistency, read all three external-AI keys through the same
helper: `externalProvider` and `externalModel` aren't sensitive and
work either way, but routing both through `settings_manager` means
(a) one logical source-of-truth, (b) future sensitive keys don't
re-introduce this bug class, (c) env-var fallback behaviour matches
between keys.

Also add a structural CI guard: searching `api/` for the pattern
`backend.get_setting("<sensitive_key>")` (or the variable equivalent)
fails the test. That's the grep-able form of "never read a sensitive
key through the non-decrypting path". Prevents regression in future
code that might copy-paste the wrong pattern.

Version bump: 2.38.2 → 2.38.3 (`.x.3` — single-file logic fix, no
schema, no new deps, no new Settings).

---

## Change 1 — `api/agents/external_ai_client.py`

Find the `synthesize_replace` function (around line ~260). The current
shape of the Settings read block:

```python
async def synthesize_replace(
    *,
    task: str,
    agent_type: str,
    messages: list[dict],
    digest: str | None = None,
    context_max_chars: int = 12000,
    timeout_s: float = 45.0,
) -> ExternalAIResponse:
    """High-level helper: reads Settings, builds prompt, calls provider.

    Raises ExternalAI* on failure. Caller wraps this in try/except to
    produce the halt-on-failure behaviour.
    """
    from mcp_server.tools.skills.storage import get_backend
    backend = get_backend()

    provider = (backend.get_setting("externalProvider") or "claude").strip().lower()
    api_key = (backend.get_setting("externalApiKey") or "").strip()
    model = (backend.get_setting("externalModel") or "").strip()
```

Replace that block with:

```python
async def synthesize_replace(
    *,
    task: str,
    agent_type: str,
    messages: list[dict],
    digest: str | None = None,
    context_max_chars: int = 12000,
    timeout_s: float = 45.0,
) -> ExternalAIResponse:
    """High-level helper: reads Settings, builds prompt, calls provider.

    Raises ExternalAI* on failure. Caller wraps this in try/except to
    produce the halt-on-failure behaviour.

    v2.38.3: reads via api.settings_manager.get_setting so sensitive
    keys (externalApiKey is in SENSITIVE_KEYS) are decrypted before
    use. Pre-v2.38.3 this function read via the raw backend primitive
    which returned ciphertext — resulting in HTTP 401 auth failures
    on every external AI call.
    """
    from api.settings_manager import get_setting
    from api.routers.settings import SETTINGS_KEYS

    def _read(key: str, default: str = "") -> str:
        """Read a Settings value through the decrypting path. Returns
        stripped string or default on any error / empty value."""
        try:
            val = get_setting(key, SETTINGS_KEYS).get("value")
        except Exception as e:
            log.warning("external_ai: failed to read setting %r: %s", key, e)
            return default
        if val is None:
            return default
        return str(val).strip() or default

    provider = _read("externalProvider", "claude").lower()
    api_key  = _read("externalApiKey")
    model    = _read("externalModel")
```

The rest of the function (validation, `call_external_ai` dispatch,
metrics block) stays untouched.

**Notes on the rewrite:**

- The old local import `from mcp_server.tools.skills.storage import
  get_backend` is no longer needed in `synthesize_replace` — the
  `settings_manager.get_setting` function imports the backend
  internally when needed. If some OTHER function in
  `external_ai_client.py` still imports `get_backend`, leave that
  untouched; if `synthesize_replace` was the only consumer of the
  local `backend = get_backend()` binding, both lines are removed
  cleanly.
- `_read()` local helper centralises three concerns: try/except
  around the settings fetch (never let a settings read break the
  caller), None→"" normalisation, and `.strip()` + lower-case
  provider handling.
- `log.warning` on setting-read failure gives Kent something to
  grep in docker logs if DB/crypto ever goes south during a run;
  previously this would have surfaced as an unrelated AttributeError
  from the downstream `.strip()` call.
- Defaults preserved: `externalProvider` defaults to `"claude"`,
  `externalApiKey` / `externalModel` default to empty string (which
  the existing validation below catches with `ExternalAIAuthError`).

---

## Change 2 — `VERSION`

```
2.38.3
```

---

## Change 3 — Tests

### NEW `tests/test_external_ai_client_decrypts_key.py`

The critical regression test. Verifies that `synthesize_replace` reads
the API key through a decryption-aware path, so ciphertext can never
again reach the provider's auth header.

```python
"""v2.38.3 — External AI client must decrypt the API key before use.

Pre-v2.38.3: synthesize_replace read via backend.get_setting() which
is the raw primitive store accessor — returned ciphertext for
sensitive keys. Caused HTTP 401 on every external AI call because the
ciphertext was sent as the x-api-key header value.

Post-v2.38.3: reads via api.settings_manager.get_setting(key,
SETTINGS_KEYS)["value"] which calls decrypt_value() on encrypted
values before returning. Plaintext key reaches the provider. This
test pins the decryption wiring.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest


# ── Integration: synthesize_replace actually decrypts ────────────────────────

def test_synthesize_replace_decrypts_encrypted_api_key(monkeypatch):
    """Store an encrypted externalApiKey. Verify the outbound HTTP call
    receives the plaintext value, not the ciphertext."""
    from api.agents.external_ai_client import synthesize_replace
    from api.crypto import encrypt_value
    from api.settings_manager import SENSITIVE_KEYS

    # Sanity: confirm the key is treated as sensitive
    assert "externalApiKey" in SENSITIVE_KEYS, (
        "externalApiKey must be in SENSITIVE_KEYS for this test to be meaningful"
    )

    plaintext_key = "sk-ant-test-plaintext-key-XYZ123"
    ciphertext = encrypt_value(plaintext_key)
    # Encryption must actually transform the value — if it doesn't, the
    # bug can't exist and this test is tautological
    assert ciphertext != plaintext_key, "encrypt_value did not transform input"

    # Fake Settings backend that returns ciphertext for sensitive keys
    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  ciphertext,        # ← encrypted in DB
        "externalModel":   "claude-sonnet-4-6",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: fake_backend,
    )

    # Capture the Authorization/x-api-key the client would send
    captured: dict = {}

    async def _fake_call(**kwargs):
        # Mirror the signature of call_external_ai
        captured.update(kwargs)
        from api.agents.external_ai_client import ExternalAIResponse
        return ExternalAIResponse(
            text="ok", provider=kwargs["provider"], model=kwargs["model"],
            input_tokens=1, output_tokens=1, est_cost_usd=None, latency_ms=1,
        )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(side_effect=_fake_call),
    ):
        asyncio.run(synthesize_replace(
            task="ping", agent_type="observe", messages=[],
        ))

    # The regression: ciphertext must not reach the provider
    assert captured["api_key"] == plaintext_key, (
        f"synthesize_replace passed ciphertext to call_external_ai: "
        f"{captured.get('api_key')!r} — expected plaintext {plaintext_key!r}"
    )
    assert captured["provider"] == "claude"
    assert captured["model"] == "claude-sonnet-4-6"


def test_synthesize_replace_raises_auth_error_on_empty_key(monkeypatch):
    """Empty externalApiKey → ExternalAIAuthError BEFORE any HTTP call.
    Locks in the pre-call validation path."""
    from api.agents.external_ai_client import (
        synthesize_replace, ExternalAIAuthError,
    )

    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  "",
        "externalModel":   "claude-sonnet-4-6",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: _FakeBackend(),
    )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(),
    ) as mocked:
        with pytest.raises(ExternalAIAuthError):
            asyncio.run(synthesize_replace(
                task="ping", agent_type="observe", messages=[],
            ))
        assert mocked.call_count == 0, (
            "call_external_ai must NOT be invoked when api_key is empty"
        )


def test_synthesize_replace_raises_auth_error_on_empty_model(monkeypatch):
    """Empty externalModel → ExternalAIAuthError BEFORE any HTTP call."""
    from api.agents.external_ai_client import (
        synthesize_replace, ExternalAIAuthError,
    )

    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  "sk-ant-ok",
        "externalModel":   "",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: _FakeBackend(),
    )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(),
    ) as mocked:
        with pytest.raises(ExternalAIAuthError):
            asyncio.run(synthesize_replace(
                task="ping", agent_type="observe", messages=[],
            ))
        assert mocked.call_count == 0


# ── Structural: source-level guard against regression ──────────────────────

def test_source_reads_externalApiKey_through_decrypting_path():
    """The source file must read externalApiKey through the
    settings_manager.get_setting path, not via the raw backend
    primitive. Structural guard — catches copy-paste of the old
    pattern.
    """
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent
        / "api" / "agents" / "external_ai_client.py"
    ).read_text(encoding="utf-8")

    # Must import the decrypting helper
    assert "from api.settings_manager import get_setting" in src, (
        "external_ai_client.py must import get_setting from "
        "api.settings_manager — that's the decrypting read path"
    )
    # Must reference SETTINGS_KEYS registry (required for the decrypting call)
    assert "SETTINGS_KEYS" in src, (
        "external_ai_client.py must reference SETTINGS_KEYS — without "
        "the registry, get_setting can't find the key metadata"
    )
    # Must NOT read externalApiKey through the raw backend primitive
    # (accept either 'backend.get_setting("externalApiKey")' or
    # "…'externalApiKey')" forms)
    assert 'backend.get_setting("externalApiKey")' not in src, (
        "external_ai_client.py must not read externalApiKey via the raw "
        "backend — that path returns ciphertext. Use "
        "api.settings_manager.get_setting instead."
    )
    assert "backend.get_setting('externalApiKey')" not in src


def test_synthesize_replace_signature_unchanged():
    """Pin the public signature of synthesize_replace so callers in
    api/routers/agent.py don't break.
    """
    from api.agents.external_ai_client import synthesize_replace
    sig = inspect.signature(synthesize_replace)
    expected = [
        "task", "agent_type", "messages",
        "digest", "context_max_chars", "timeout_s",
    ]
    actual = list(sig.parameters.keys())
    assert actual == expected, (
        f"synthesize_replace signature drift — expected {expected}, "
        f"got {actual}"
    )
```

### NEW `tests/test_no_raw_backend_read_of_sensitive_keys.py`

Structural CI guard. Covers the generalisable rule: **no `api/` module
may read a SENSITIVE_KEYS value through the raw `backend.get_setting`
primitive**. Prevents future regressions of the same bug class in
other subsystems.

```python
"""v2.38.3 — Generalised sensitive-key read guard.

No code under api/ may read a key that lives in
api.settings_manager.SENSITIVE_KEYS via the raw backend.get_setting()
primitive. The raw accessor returns ciphertext for sensitive keys;
callers must go through api.settings_manager.get_setting(key,
SETTINGS_KEYS)['value'] which decrypts.

One explicit allowlist: api/settings_manager.py itself (it IS the
decrypting layer — it needs to call backend.get_setting as its
low-level read).
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent
API_DIR = REPO_ROOT / "api"

# Files allowed to use the raw primitive because they implement the
# decrypting layer itself OR they only read non-sensitive keys.
ALLOWED_FILES = {
    REPO_ROOT / "api" / "settings_manager.py",  # THE decrypting layer
    # routers/settings.py uses backend.get_setting() for seeding /
    # resync / admin paths that intentionally touch raw values. The
    # pattern in that file is always either under seed_defaults,
    # sync_env_from_db, or the migrate helper — never to ship a
    # sensitive key to an external API. Allowed.
    REPO_ROOT / "api" / "routers" / "settings.py",
}


def _sensitive_keys() -> frozenset[str]:
    """Parse SENSITIVE_KEYS from api/settings_manager.py without importing
    the module (imports would pull in DB / crypto side effects)."""
    src = (API_DIR / "settings_manager.py").read_text(encoding="utf-8")
    # Match the literal frozenset block
    m = re.search(
        r"SENSITIVE_KEYS\s*=\s*frozenset\(\{([^}]+)\}\)",
        src, flags=re.DOTALL,
    )
    assert m, "SENSITIVE_KEYS frozenset block not found in settings_manager.py"
    body = m.group(1)
    keys = frozenset(re.findall(r'"([^"]+)"|\'([^\']+)\'', body))
    # Above returns tuples of (double-quoted, single-quoted); flatten
    flat = frozenset(d or s for (d, s) in keys)
    assert flat, "SENSITIVE_KEYS parsed as empty — regex failed"
    return flat


def test_no_raw_backend_read_of_sensitive_key():
    """Scan every .py under api/ for backend.get_setting("<sensitive>")
    or .get_setting('<sensitive>'). Fail with a grouped report if any
    match outside the ALLOWED_FILES list.
    """
    keys = _sensitive_keys()
    # Build a regex that matches backend.get_setting("key") or
    # backend.get_setting('key') for any sensitive key name
    key_alt = "|".join(re.escape(k) for k in keys)
    pattern = re.compile(
        r'\.get_setting\(\s*["\'](' + key_alt + r')["\']',
    )

    violations: list[tuple[pathlib.Path, int, str, str]] = []
    for path in API_DIR.rglob("*.py"):
        if path in ALLOWED_FILES:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            m = pattern.search(line)
            if m:
                violations.append((
                    path.relative_to(REPO_ROOT),
                    lineno,
                    m.group(1),
                    line.strip(),
                ))

    if violations:
        msg_lines = [
            "Raw-backend read of SENSITIVE key(s) found outside "
            "api/settings_manager.py and api/routers/settings.py:",
            "",
        ]
        for path, lineno, key, line in violations:
            msg_lines.append(f"  {path}:{lineno}  [{key}]  {line}")
        msg_lines += [
            "",
            "Use api.settings_manager.get_setting(key, SETTINGS_KEYS)",
            "['value'] instead — that path decrypts. Raw backend reads",
            "return ciphertext for SENSITIVE_KEYS and will cause auth",
            "failures when shipped to external APIs (v2.38.3 regression",
            "prevention).",
        ]
        raise AssertionError("\n".join(msg_lines))


def test_allowed_files_exist():
    """Sanity: the ALLOWED_FILES paths must exist — otherwise the guard
    is silently too permissive after a refactor."""
    for p in ALLOWED_FILES:
        assert p.exists(), (
            f"ALLOWED_FILES member {p.relative_to(REPO_ROOT)} does not "
            f"exist — update test_no_raw_backend_read_of_sensitive_keys.py "
            f"ALLOWED_FILES"
        )
```

---

## Verify

```bash
# Fix applied
grep -n 'from api.settings_manager import get_setting' api/agents/external_ai_client.py  # 1
grep -n 'from api.routers.settings import SETTINGS_KEYS'   api/agents/external_ai_client.py  # 1
grep -n 'backend.get_setting("externalApiKey")'            api/agents/external_ai_client.py  # 0
grep -n 'backend.get_setting'                              api/agents/external_ai_client.py  # 0 inside synthesize_replace

# Run the new tests
pytest tests/test_external_ai_client_decrypts_key.py -v
pytest tests/test_no_raw_backend_read_of_sensitive_keys.py -v

# v2.36.3 tests still green (should pass unchanged — mocks bypass the Settings layer)
pytest tests/test_external_ai_client.py -v

# Earlier external-AI tests still pass
pytest tests/test_external_router.py                -v
pytest tests/test_external_ai_confirmation.py       -v
pytest tests/test_external_ai_calls_endpoint.py     -v
pytest tests/test_external_ai_test_endpoint.py      -v
```

Optional manual verification inside the running container (smoke only —
needs an encrypted key in the DB):

```bash
docker exec hp1_agent python -c "
from api.settings_manager import get_setting
from api.routers.settings import SETTINGS_KEYS
info = get_setting('externalApiKey', SETTINGS_KEYS)
print({'encrypted': info['encrypted'], 'source': info['source'],
       'value_len': len(info['value']),
       'starts_with': info['value'][:7] if info['value'] else ''})
"
# Expected: encrypted=True, source='db', value_len>=40,
# starts_with='sk-ant-' (or 'sk-...' for OpenAI, 'xai-' for Grok)
```

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.38.3 external AI auth 401 — use decrypting get_setting

Every external AI escalation since v2.36.3 returned HTTP 401 auth_failed
while the Test Connection button for the same provider/key/model
returned 200 OK. Kent reported the split: 'external ai has auth failed,
while test works, is it the correct url?' — URL is correct; this is a
settings-read-layer bug.

externalApiKey is in api.settings_manager.SENSITIVE_KEYS, so set_setting
encrypts the value before backend.set_setting(). The DB holds ciphertext.
Two read paths exist:

1. api.settings_manager.get_setting(key, registry)
   — calls is_encrypted(db_val) + decrypt_value(db_val)
   — returns plaintext

2. backend.get_setting(key)  (raw primitive from storage.py)
   — returns raw DB value
   — ciphertext for sensitive keys

api/routers/settings.py::test_external_ai (v2.35.21) uses path 1
— Test Connection works.

api/agents/external_ai_client.py::synthesize_replace (v2.36.3) used
path 2 — production escalation sent ciphertext as x-api-key header
value, Claude returned HTTP 401, v2.36.3's ExternalAIAuthError fired,
v2.36.4's escalation banner raised. Every external call has been broken
since v2.36.3 shipped.

Fix: swap synthesize_replace to read via settings_manager.get_setting
for all three external-AI keys (externalProvider / externalApiKey /
externalModel). externalApiKey is the one that MUST go through the
decrypting path; the other two are routed through the same helper for
consistency and to prevent future sensitive-key additions from
re-introducing this bug class. Added local _read() helper wrapping the
settings fetch with try/except + None/empty normalisation.

Tests: 4 regression tests in tests/test_external_ai_client_decrypts_key.py
pin the wiring — (1) integration test encrypts a known plaintext key,
runs synthesize_replace through a mocked backend, asserts the mocked
call_external_ai receives the plaintext (not ciphertext) as api_key;
(2) empty key raises ExternalAIAuthError before any HTTP call;
(3) empty model raises ExternalAIAuthError before any HTTP call;
(4) structural source-file guard asserts the decrypting imports are
present and the old raw-backend pattern is absent.

Plus tests/test_no_raw_backend_read_of_sensitive_keys.py — generalised
CI guard that scans every .py under api/ for backend.get_setting() on
any SENSITIVE_KEYS member and fails with a grouped report on
violations. Allowlist: api/settings_manager.py (implements the
decrypting layer itself) and api/routers/settings.py (seed/sync/admin
paths that intentionally touch raw values). Prevents this bug class
from recurring in other subsystems (e.g. if a future feature reads
proxmoxTokenSecret, fortigateApiKey, truenasApiKey, or ghcrToken via
the raw primitive).

No schema changes, no new Settings keys, no new deps. Single
production file touched: api/agents/external_ai_client.py."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke plan:

1. Hard-refresh (clears cached JS).
2. Open Settings → AI Services. Verify Test Connection still succeeds
   against the saved Claude key (regression guard — v2.35.21 path must
   still work after the v2.38.3 refactor if any code paths were
   affected).
3. Ensure External AI Router is in `manual` or `auto` mode with
   `requireConfirmation=True`.
4. Trigger an investigate task likely to hit budget_exhaustion
   (e.g. the filebeat auth-failure diagnosis from earlier — its
   session was `6d2219b9` on 2026-04-21 12:55). Operator approves
   the confirmation modal when it appears.
5. Watch the live trace. Success signs:
   - No `[escalation failed] External AI auth failed (HTTP 401)`
     escalation banner.
   - `final_answer` arrives with `[EXTERNAL: claude/claude-sonnet-4-6]`
     prefix.
   - `/api/logs/operations/{id}/trace?format=digest` shows
     `external_ai_routed` in Gates Fired.
6. Open Logs → External AI Calls view (v2.36.4). The new row should
   show `outcome=success`, non-zero input/output tokens, a latency,
   and an estimated cost. Previously all rows for this operator
   showed `outcome=auth_error` or `outcome=error`.
7. Optional regression query:
   ```sql
   SELECT outcome, COUNT(*)
   FROM external_ai_calls
   WHERE created_at > NOW() - INTERVAL '1 day'
   GROUP BY outcome
   ORDER BY 2 DESC;
   ```
   Should show `success` > 0 (and keep going up on subsequent runs).

---

## Scope guard — DO NOT TOUCH

- `api/routers/settings.py` — the Test Connection endpoint is
  already correct (v2.35.21). Do not refactor it.
- `api/settings_manager.py` — the decrypting layer itself. Do not
  touch `get_setting` / `set_setting` / `SENSITIVE_KEYS`.
- `api/crypto.py` — `encrypt_value`, `decrypt_value`, `is_encrypted`
  all unchanged.
- `api/agents/external_router.py` — rule engine unchanged.
- `api/agents/external_ai_confirmation.py` — wait primitive unchanged.
- `api/routers/external_ai.py` — billing endpoint unchanged.
- `call_external_ai`, `_call_claude`, `_call_openai_compatible` in
  `external_ai_client.py` — URL construction, header building, HTTP
  dispatch, response parsing — all unchanged. Only the Settings read
  block at the top of `synthesize_replace` changes.
- `api/db/external_ai_calls.py` — billing log table unchanged.
- Frontend (`ExternalAIConfirmModal.jsx`,
  `ExternalAICallsView.jsx`, `OptionsModal.jsx`) — unchanged.

---

## Followups (not v2.38.3)

- v2.38.4 could add a Prometheus counter
  `deathstar_external_ai_auth_failures_total{provider}` on the
  `ExternalAIAuthError` path so future auth drifts surface as an
  alertable metric instead of silent escalation-banner spam.
- Audit the other SENSITIVE_KEYS consumers (proxmox collectors read
  `proxmoxTokenSecret`, fortigate collector reads `fortigateApiKey`,
  truenas collector reads `truenasApiKey`, container updater reads
  `ghcrToken`). v2.38.3's structural guard will flag any that read
  through the raw primitive; if any do, they shipped with the same
  bug class and just happened to seed the env var on startup in
  `sync_env_from_db` which masks the problem.
- Consider moving SETTINGS_KEYS out of `api/routers/settings.py` into
  its own module so `external_ai_client.py` doesn't have to import
  from a router (mild circular-risk). Cosmetic; not urgent.
