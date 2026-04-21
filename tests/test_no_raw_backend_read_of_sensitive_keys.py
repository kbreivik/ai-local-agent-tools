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
