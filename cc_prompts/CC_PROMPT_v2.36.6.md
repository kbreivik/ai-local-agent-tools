# CC PROMPT — v2.36.6 — Fix: UI Settings save drops Facts + Agent Budgets keys

## What this does

The Settings page's save pipeline filters the POST body through a hardcoded
allowlist (`SERVER_KEYS` in `gui/src/context/OptionsContext.jsx`). Any key
not in the allowlist is silently dropped. 30 keys across two Settings
groups were never added to the allowlist:

- **Agent Budgets** (v2.36.5 — today) — 4 keys
- **Facts & Knowledge** (v2.35.0 – v2.35.4) — 26 keys

Users editing the UI inputs for any of these 30 keys, clicking Save, and
getting a green "Settings saved" toast were never actually persisting
anything. The DB kept the registry defaults; the agent happily read those
defaults and behaved as if nothing had been configured. Kent discovered
this today when v2.36.5's `agentToolBudget_observe=16` had no effect —
the UNifi status task still capped at 8.

Fix adds all 30 keys to both `DEFAULTS` and `SERVER_KEYS` in
`OptionsContext.jsx`, plus a structural CI test that parses
`SETTINGS_KEYS` from `api/routers/settings.py` (Python AST) and
`SERVER_KEYS` from `OptionsContext.jsx` (regex), asserting every
registry key with a `"group"` field is reachable from the UI save path.
Catches the next "added a Settings group and forgot the UI allowlist"
regression in CI before it ships.

Version bump: 2.36.5 → 2.36.6 (`.x.N` — fix).

---

## Why

Evidence (from Kent on 2026-04-20, roughly 21:00 UTC):

1. v2.36.5 shipped. `VERSION` reads `2.36.5`; `_tool_budget_for(agent_type)`
   is correctly defined and wired at all five budget-check sites in
   `api/routers/agent.py`; `_MAX_TOOL_CALLS_BY_TYPE` no longer exists.
2. Kent set observe=16 / investigate=24 / execute=24 / build=24 in the
   Settings UI, saw the green "Settings saved" toast, and got back an
   observe task that capped at 8/8 (the pre-v2.36.5 hardcoded default for
   observe), not 16.
3. Diagnostic from inside the agent container:
   ```bash
   docker compose exec hp1_agent python -c "
   from mcp_server.tools.skills.storage import get_backend
   b = get_backend()
   for k in ['agentToolBudget_observe', 'agentToolBudget_investigate',
            'agentToolBudget_execute', 'agentToolBudget_build']:
       v = b.get_setting(k)
       print(f'{k} = {v!r} (type={type(v).__name__})')
   "
   ```
   returned `None (type=NoneType)` for all four keys. The POST never
   landed.
4. Backend POST endpoint (`api/routers/settings.py::update_settings`)
   filters only by `key not in SETTINGS_KEYS` membership — those 4 keys
   ARE in `SETTINGS_KEYS` so the endpoint would persist them if it
   received them. Backend is innocent.
5. Frontend save flow:
   ```
   SettingsPage.jsx::save()
     → options.saveOptions(draft)    [OptionsContext.jsx]
       → filter draft entries by SERVER_KEYS.has(k)
         → POST /api/settings with the surviving keys
   ```
   `SERVER_KEYS` in `OptionsContext.jsx` is a hardcoded frozenset that
   does not include any of the 4 agentToolBudget_* keys.

Comparing `SERVER_KEYS` against `SETTINGS_KEYS` registry for all keys
with a `"group"` field (i.e. keys the UI is meant to expose):

- **External AI Router** (v2.36.0 – v2.36.4) — all 11 keys ARE in
  `SERVER_KEYS`. Whoever wired v2.36.0/4 did it right.
- **Facts & Knowledge** (v2.35.0 – v2.35.4) — none of the 26 keys are
  in `SERVER_KEYS`. Every Facts threshold / decay / source-weight /
  runbook-mode / preflight setting Kent has "saved" via UI since v2.35.0
  has been silently dropped. The backend seeded the registry defaults
  into the DB at first boot (via `seed_defaults()`), so the agent has
  always read plausible values — just never the operator-tuned ones.
- **Agent Budgets** (v2.36.5 — today) — 4 keys missing.

30 keys total. One allowlist. One fix.

---

## Change 1 — `gui/src/context/OptionsContext.jsx`

Two edits in the same file. Preserve existing ordering where possible;
append new blocks at the end of the section they belong to with a clear
comment header.

### 1a — `DEFAULTS` object

After the existing `externalContextLastNToolResults: 5,` line (the last
External AI Router key), insert:

```jsx
  // Facts & Knowledge (v2.35.0 – v2.35.4 — v2.36.6 allowlisted)
  factInjectionThreshold:            0.7,
  factInjectionMaxRows:              40,
  factSourceWeight_manual:                 1.0,
  factSourceWeight_proxmox_collector:      0.9,
  factSourceWeight_swarm_collector:        0.9,
  factSourceWeight_docker_agent_collector: 0.85,
  factSourceWeight_pbs_collector:          0.85,
  factSourceWeight_kafka_collector:        0.8,
  factSourceWeight_fortiswitch_collector:  0.85,
  factSourceWeight_agent_observation:      0.5,
  factSourceWeight_rag_extraction:         0.4,
  factHalfLifeHours_collector:       168,
  factHalfLifeHours_agent:           24,
  factHalfLifeHours_manual_phase1:   720,
  factHalfLifeHours_manual_phase2:   1440,
  factHalfLifeHours_agent_volatile:  2,
  factVerifyCountCap:                10,
  factAgeRejectionMode:              'medium',
  factAgeRejectionMaxAgeMin:         5,
  factAgeRejectionMinConfidence:     0.85,
  runbookInjectionMode:              'augment',
  runbookClassifierMode:             'keyword',
  preflightPanelMode:                'always_visible',
  preflightDisambiguationTimeout:    300,
  preflightLLMFallbackEnabled:       true,
  preflightLLMFallbackMaxTokens:     200,

  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,
```

The defaults EXACTLY match `SETTINGS_KEYS[key]["default"]` in
`api/routers/settings.py` — zero behaviour change at first save because
the registry-seeded DB values and the DEFAULTS will agree.

### 1b — `SERVER_KEYS` set

After the existing `'autoUpdate', 'dashboardRefreshInterval',` line
(the last entry), insert — still inside the `new Set([...])`:

```jsx
  // Facts & Knowledge (v2.35.0 – v2.35.4 — v2.36.6 allowlisted)
  'factInjectionThreshold', 'factInjectionMaxRows',
  'factSourceWeight_manual', 'factSourceWeight_proxmox_collector',
  'factSourceWeight_swarm_collector', 'factSourceWeight_docker_agent_collector',
  'factSourceWeight_pbs_collector', 'factSourceWeight_kafka_collector',
  'factSourceWeight_fortiswitch_collector', 'factSourceWeight_agent_observation',
  'factSourceWeight_rag_extraction',
  'factHalfLifeHours_collector', 'factHalfLifeHours_agent',
  'factHalfLifeHours_manual_phase1', 'factHalfLifeHours_manual_phase2',
  'factHalfLifeHours_agent_volatile',
  'factVerifyCountCap',
  'factAgeRejectionMode', 'factAgeRejectionMaxAgeMin', 'factAgeRejectionMinConfidence',
  'runbookInjectionMode', 'runbookClassifierMode',
  'preflightPanelMode', 'preflightDisambiguationTimeout',
  'preflightLLMFallbackEnabled', 'preflightLLMFallbackMaxTokens',

  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',
```

**Do NOT touch** the keys above these blocks — the External AI Router
allowlist entries (externalRoutingMode, routeOnGateFailure, etc.) are
correct and in use.

---

## Change 2 — `tests/test_options_context_server_keys.py` (NEW)

Structural CI test. Parses both files, compares. Fails on divergence.
Python-only — no Node / jsdom dependency.

```python
"""v2.36.6 — UI Settings save-path allowlist coverage.

Background: `gui/src/context/OptionsContext.jsx::saveOptions` filters the
POST body through the `SERVER_KEYS` frozenset. Any `SETTINGS_KEYS` entry
(defined in `api/routers/settings.py`) with a `"group"` field is
intended to be UI-editable; if such a key is missing from `SERVER_KEYS`,
user edits silently drop before the POST and the DB never sees them.

This test is the CI guard. It parses both files and asserts every
grouped registry key has an allowlist entry. If this test fails, the fix
is almost always: append the missing key name(s) to `SERVER_KEYS` in
`gui/src/context/OptionsContext.jsx` (and probably add a matching entry
to `DEFAULTS` so the input renders with a reasonable seed value).

Runs in <100ms — pure file parsing, no DB, no subprocess.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS_PY = ROOT / "api" / "routers" / "settings.py"
OPTIONS_CONTEXT_JSX = ROOT / "gui" / "src" / "context" / "OptionsContext.jsx"


def _parse_settings_keys_with_groups() -> dict[str, str]:
    """Return {key: group_name} for every SETTINGS_KEYS entry with a 'group'.

    Uses the Python AST so we don't have to import the module (which would
    pull in FastAPI, DB, etc). Walks the module, finds `SETTINGS_KEYS = {...}`,
    iterates dict items, extracts the 'group' from each value dict.
    """
    src = SETTINGS_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    grouped: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not (isinstance(tgt, ast.Name) and tgt.id == "SETTINGS_KEYS"):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for k_node, v_node in zip(node.value.keys, node.value.values):
            if not isinstance(k_node, ast.Constant):
                continue
            if not isinstance(k_node.value, str):
                continue
            key = k_node.value
            if not isinstance(v_node, ast.Dict):
                continue
            for meta_k, meta_v in zip(v_node.keys, v_node.values):
                if (
                    isinstance(meta_k, ast.Constant)
                    and meta_k.value == "group"
                    and isinstance(meta_v, ast.Constant)
                    and isinstance(meta_v.value, str)
                ):
                    grouped[key] = meta_v.value
                    break
        break  # only one SETTINGS_KEYS assignment expected

    return grouped


def _parse_server_keys_from_jsx() -> set[str]:
    """Return the set of keys in `SERVER_KEYS = new Set([...])` in OptionsContext.jsx.

    Regex approach — we don't need a full JS parser for a static frozenset
    literal. Matches the block from `SERVER_KEYS = new Set([` to the
    closing `])` and extracts every single- or double-quoted string inside.
    """
    src = OPTIONS_CONTEXT_JSX.read_text(encoding="utf-8")
    m = re.search(
        r"SERVER_KEYS\s*=\s*new\s+Set\s*\(\s*\[(.*?)\]\s*\)",
        src, flags=re.DOTALL,
    )
    assert m, (
        "Could not locate `SERVER_KEYS = new Set([...])` in "
        f"{OPTIONS_CONTEXT_JSX}. File structure changed?"
    )
    block = m.group(1)
    # Strip JS comments ("// ..." to end of line) so they don't get
    # mistaken for keys and so quoted tokens inside comments are ignored.
    block = re.sub(r"//[^\n]*", "", block)
    # Extract every 'key' or "key" token
    return set(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", block))


def test_every_grouped_setting_is_server_allowlisted():
    """Every SETTINGS_KEYS entry with a 'group' MUST be in SERVER_KEYS.

    Keys with a 'group' are the ones Settings UI tabs render (Facts &
    Knowledge, External AI Router, Agent Budgets, etc). If a grouped key
    is missing from the SERVER_KEYS allowlist in OptionsContext.jsx,
    `saveOptions()` will strip it before the POST and the user's edit is
    silently lost.
    """
    grouped = _parse_settings_keys_with_groups()
    allowed = _parse_server_keys_from_jsx()

    # Sanity check — if either file couldn't be parsed we'd have 0 entries
    assert grouped, (
        f"Parsed 0 grouped keys from {SETTINGS_PY}. The SETTINGS_KEYS "
        "registry structure has changed — update the AST walker."
    )
    assert allowed, (
        f"Parsed 0 SERVER_KEYS entries from {OPTIONS_CONTEXT_JSX}. "
        "The `SERVER_KEYS = new Set([...])` literal has moved — update "
        "the regex."
    )

    missing = {key: group for key, group in grouped.items() if key not in allowed}
    if missing:
        # Group the missing keys by their 'group' label so the error
        # message is readable when a whole subsystem gets forgotten at once.
        by_group: dict[str, list[str]] = {}
        for k, g in missing.items():
            by_group.setdefault(g, []).append(k)
        lines = [
            "The following SETTINGS_KEYS entries have a 'group' label but "
            "are NOT in SERVER_KEYS in gui/src/context/OptionsContext.jsx.",
            "Edits made in the UI for these keys will be SILENTLY DROPPED "
            "by saveOptions() before the POST.",
            "",
            "Fix: append each missing key (as a quoted string) to the "
            "SERVER_KEYS `new Set([...])`; also add a matching default "
            "value to the DEFAULTS object so inputs render sensibly.",
            "",
        ]
        for g, keys in sorted(by_group.items()):
            lines.append(f"  [{g}]  ({len(keys)} keys)")
            for k in sorted(keys):
                lines.append(f"    - {k}")
        raise AssertionError("\n".join(lines))


def test_server_keys_unique():
    """Duplicate entries in SERVER_KEYS are a sign of a messy merge.

    Uses a raw list (duplicates preserved) so the regex extract count
    disagrees with the set length when duplicates exist.
    """
    src = OPTIONS_CONTEXT_JSX.read_text(encoding="utf-8")
    m = re.search(
        r"SERVER_KEYS\s*=\s*new\s+Set\s*\(\s*\[(.*?)\]\s*\)",
        src, flags=re.DOTALL,
    )
    assert m
    block = re.sub(r"//[^\n]*", "", m.group(1))
    all_entries = re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", block)
    dupes = [k for k in all_entries if all_entries.count(k) > 1]
    assert not dupes, f"Duplicate SERVER_KEYS entries: {sorted(set(dupes))}"


def test_defaults_present_for_every_server_key():
    """Every key in SERVER_KEYS SHOULD have a default in DEFAULTS too.

    Not strictly required (a missing default means the input renders as
    empty/undefined), but it's nearly always a bug: the user sees a
    blank field and if they click Save without typing, 'parseInt('') || 0'
    in the onChange handler writes 0. For int budgets that gets treated
    as 'restore hardcoded default' — silent no-op — which is what
    happened before v2.36.6.

    Tolerates a small known-exception list for keys intentionally UI-only
    or managed via other UI flows (Connections tab, etc).
    """
    src = OPTIONS_CONTEXT_JSX.read_text(encoding="utf-8")
    m_defaults = re.search(
        r"const\s+DEFAULTS\s*=\s*\{(.*?)^\}", src, flags=re.DOTALL | re.MULTILINE
    )
    assert m_defaults, "Could not locate `const DEFAULTS = { ... }`."
    defaults_block = re.sub(r"//[^\n]*", "", m_defaults.group(1))
    default_keys = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", defaults_block,
                                   flags=re.MULTILINE))

    allowed = _parse_server_keys_from_jsx()

    # A handful of keys are server-synced but intentionally not in DEFAULTS
    # (e.g. agentDockerHost is env-seeded only, not operator-editable).
    # Extend cautiously — each entry is a claim that the key genuinely
    # doesn't need a client-side default.
    KNOWN_SERVER_ONLY: set[str] = {
        "ghcrToken",               # sensitive, masked on GET
        "agentDockerHost",         # env-seeded, read-only on UI
        "swarmManagerIPs",
        "swarmWorkerIPs",
    }

    missing_defaults = allowed - default_keys - KNOWN_SERVER_ONLY
    assert not missing_defaults, (
        "SERVER_KEYS entries with no DEFAULTS seed: "
        f"{sorted(missing_defaults)}. Either add to DEFAULTS, or add to "
        "KNOWN_SERVER_ONLY in this test if it's intentionally UI-blank."
    )
```

---

## Change 3 — `VERSION`

```
2.36.6
```

---

## Verify

```bash
pytest tests/test_options_context_server_keys.py -v
# All three tests must pass.

# Spot-check that we did pull the exact 30 new keys — should print 30 new lines:
grep -oE "(factInjection|factSourceWeight|factHalfLifeHours|factVerify|factAgeRejection|runbook(Injection|Classifier)Mode|preflight|agentToolBudget)_?[A-Za-z0-9_]*" \
  gui/src/context/OptionsContext.jsx | sort -u | wc -l
# expect: >= 30 (32 because runbookInjectionMode/runbookClassifierMode parse separately)
```

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.36.6 add 30 missing Settings keys to SERVER_KEYS allowlist

Background: gui/src/context/OptionsContext.jsx::saveOptions filters the
POST body through a hardcoded SERVER_KEYS frozenset. Any key not in
the allowlist is silently dropped before the POST hits /api/settings.

Two Settings groups had their keys missing from SERVER_KEYS:

- Facts & Knowledge (v2.35.0 – v2.35.4) — 26 keys. Every Facts
  threshold, source-weight, decay, runbook-mode, and preflight setting
  Kent has 'saved' via UI since v2.35.0 was silently dropped. The
  backend seeded the registry defaults into the DB at first boot via
  seed_defaults(), so the agent has always read plausible values —
  just never the operator-tuned ones.

- Agent Budgets (v2.36.5) — 4 keys. Caught today when Kent set
  agentToolBudget_observe=16 in the UI and the next observe task
  still capped at 8/8.

The External AI Router keys (v2.36.0–4) are correctly in SERVER_KEYS.

Fix: add all 30 keys to both DEFAULTS and SERVER_KEYS in OptionsContext.jsx
with defaults matching SETTINGS_KEYS registry defaults exactly. Backend
is untouched — api/routers/settings.py::update_settings already accepts
these keys via the SETTINGS_KEYS membership check.

New CI test tests/test_options_context_server_keys.py parses
SETTINGS_KEYS from api/routers/settings.py (Python AST) and SERVER_KEYS
from gui/src/context/OptionsContext.jsx (regex), asserts every registry
key with a 'group' field is reachable from the UI save path. Also tests
no duplicate SERVER_KEYS entries and every SERVER_KEYS entry has a
matching DEFAULTS seed (with a small KNOWN_SERVER_ONLY exception list).

After deploy, users must re-edit any Facts or Agent Budget values they
had tried to save previously — the DB still has the registry defaults."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

1. UI: Settings → AI Services → Agent Budgets — set observe=16, save.
   Check DB:
   ```bash
   docker compose -f /opt/hp1-agent/docker/docker-compose.yml exec hp1_agent python -c "
   from mcp_server.tools.skills.storage import get_backend
   b = get_backend()
   print('observe =', b.get_setting('agentToolBudget_observe'))
   "
   ```
   Expect `observe = 16`.

2. Run an observe task (e.g. "UniFi list all clients"). Expect the
   budget cap, if hit, to fire at 16 not 8. Or better — the task
   converges before 16.

3. UI: Settings → AI Services → expand Facts & Knowledge (if the tab
   is there — it may be under a different tab; check OptionsModal.jsx
   tab list). Change `factInjectionThreshold` from 0.7 to 0.8, save.
   Repeat the DB check for that key. Expect `factInjectionThreshold =
   0.8`.

---

## Scope guard — do NOT touch

- `api/routers/settings.py` — backend is correct. Do not edit the
  registry, the POST endpoint, or the sensitive-keys filter.
- `api/settings_manager.py` — untouched.
- `api/routers/agent.py` — v2.36.5 wiring is correct. `_tool_budget_for`
  and all its call sites stay.
- External AI Router `SERVER_KEYS` entries — already present; do not
  duplicate them.
- Any Facts / Agent Budget UI input components — this prompt is purely
  about the save pipeline. If the inputs themselves need polish (e.g.
  the Facts thresholds don't actually have a UI tab yet), that's a
  separate prompt. v2.36.6 just makes the save work so that whenever
  the UI IS wired, the save pipeline doesn't silently drop the keys.
