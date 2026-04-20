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
        if isinstance(node, ast.AnnAssign):
            # `SETTINGS_KEYS: dict[str, dict] = {...}` — annotated assignment
            tgt = node.target
            value = node.value
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            tgt = node.targets[0]
            value = node.value
        else:
            continue
        if not (isinstance(tgt, ast.Name) and tgt.id == "SETTINGS_KEYS"):
            continue
        if not isinstance(value, ast.Dict):
            continue
        for k_node, v_node in zip(value.keys, value.values):
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
