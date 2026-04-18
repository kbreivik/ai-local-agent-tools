"""Defanger for untrusted text that will be concatenated into an LLM prompt.

Philosophy:
  * Do not remove content — the LLM still needs to see the raw data to reason
    about it. But neutralise anything that looks like instructions targeting
    the LLM itself.
  * Escape XML-like tags commonly used in system prompts.
  * Cap length defensively — no single field should be able to balloon the
    context window.
  * Expose a `scrubbed` flag so callers can log/alert when a pattern fired.

This is not a replacement for allow-listing tool arguments or validating
entity IDs. It's a last-line defence for free-text fields the operator
doesn't control.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def _inc_block(pattern: str, site: str) -> None:
    """Increment the sanitizer block counter. Best-effort — never raises."""
    try:
        from api.metrics import SANITIZER_BLOCKS_COUNTER
        SANITIZER_BLOCKS_COUNTER.labels(pattern=pattern, site=site).inc()
    except Exception:
        pass


# ── Strict secret patterns (v2.34.15) ─────────────────────────────────────────
# These patterns are intentionally narrow: each matches a shape that is
# *definitionally* a secret, so false positives against version strings,
# UUIDs-as-identifiers, container IDs, and large integers stay near zero.
#
# DO NOT loosen these. Past incidents traced back to patterns like
# r"\d+\.\d+\.\d+" (ate version strings) and r"[0-9a-f]{32,}" (ate
# container IDs and hashes).

# JWT: three base64url segments separated by dots, prefixed with "eyJ"
# (every JWT header starts with `{"alg":...}` → base64url `eyJ...`).
# Rejects version strings like "2.34.15" and dotted identifiers.
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"
)

# API keys: common vendor-prefixed shapes (OpenAI, Slack bot, GitHub, AWS).
_API_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{20,}|xoxb-[A-Za-z0-9\-]{20,}|"
    r"gh[posu]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)

# UUID-in-key-context: a standard 8-4-4-4-12 UUID IS flagged only when
# preceded by a key-like label (token/secret/key/auth/password/bearer)
# within ~10 chars of separator whitespace. Bare UUIDs in logs are
# identifiers, not secrets.
_UUID_IN_KEY_CTX_RE = re.compile(
    r"(?i)(?:token|secret|key|auth|password|bearer)"
    r"[\s=:\"']{1,10}"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def _scrub_secrets(text: str, site: str) -> tuple[str, bool]:
    """Redact JWTs, vendored API keys, and UUIDs in key-like context.

    Only matches things that are structurally a secret — version strings,
    bare UUIDs in logs, and large integers must pass through untouched.
    """
    scrubbed = False

    def _sub_jwt(m: re.Match) -> str:
        nonlocal scrubbed
        scrubbed = True
        _inc_block("jwt", site)
        return "[REDACTED:jwt]"

    def _sub_key(m: re.Match) -> str:
        nonlocal scrubbed
        scrubbed = True
        _inc_block("api_key", site)
        return "[REDACTED:api_key]"

    def _sub_uuid(m: re.Match) -> str:
        nonlocal scrubbed
        scrubbed = True
        _inc_block("uuid_key_ctx", site)
        # Preserve the label/separator prefix; redact just the UUID group.
        return m.group(0).replace(m.group(1), "[REDACTED:uuid]")

    text = _JWT_RE.sub(_sub_jwt, text)
    text = _API_KEY_RE.sub(_sub_key, text)
    text = _UUID_IN_KEY_CTX_RE.sub(_sub_uuid, text)
    return text, scrubbed


# Patterns that indicate an attempt to redirect the LLM. Case-insensitive.
# Each match is annotated inline so the model sees the redaction and can
# tell the operator about it.
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ignore (all |the |any )?(previous|prior|above) (instructions?|rules?|prompt)",
                re.I), "[redacted:instruction-override]"),
    (re.compile(r"disregard (all |the |any )?(previous|prior|above)",
                re.I), "[redacted:instruction-override]"),
    (re.compile(r"you are now (a |an )?[^.\n]{0,80}", re.I),
     "[redacted:role-redefine]"),
    (re.compile(r"new instructions?:", re.I),
     "[redacted:new-instructions]"),
    (re.compile(r"system ?prompt:", re.I),
     "[redacted:system-prompt-injection]"),
    (re.compile(r"```(system|assistant|tool)\b", re.I),
     "[redacted:role-fence]"),
    (re.compile(r"</?(system|assistant|user|tool|instructions?)>", re.I),
     "[redacted:role-tag]"),
    (re.compile(r"\[INST\]|\[\/INST\]", re.I),
     "[redacted:llama-inst-tag]"),
    (re.compile(r"<\|im_(start|end)\|>", re.I),
     "[redacted:chatml-tag]"),
]

# Generic XML-like tag neutralisation: < becomes ‹ so the model doesn't
# interpret them as structural. Only triggers if the line looks like it's
# trying to open a role-ish tag — we don't mangle legitimate < in log output
# (stack traces, JSON, etc.).
_ANGLE_ROLE_TAG = re.compile(r"<(/?)(\w{1,20})>")
_ROLE_WORDS = frozenset({"system", "assistant", "user", "tool", "instruction", "instructions"})


def _site_from_hint(source_hint: str) -> str:
    """Map a free-form source_hint to a stable Prometheus label value."""
    h = (source_hint or "").lower()
    if h.startswith("tool_result"):
        return "tool_result"
    if h.startswith("entity_history"):
        return "entity_history"
    if h.startswith("entity_ask"):
        return "entity_ask"
    if h.startswith("rag") or h.startswith("doc"):
        return "rag"
    if h.startswith("system_prompt") or h.startswith("prompt"):
        return "system_prompt"
    return "other"


def sanitise(text: str, *, max_chars: int = 8000, source_hint: str = "") -> tuple[str, bool]:
    """Return (cleaned, scrubbed_bool). `scrubbed` is True if any pattern fired.

    Scope: LLM-inbound text only — tool results being appended to the
    conversation, free-text fields injected into a new sub-agent's system
    prompt, RAG retrieval output, etc. DO NOT call this on outbound API
    response bodies; it is not an egress redactor and its patterns are
    tuned for attack-surface, not exfil.

    `source_hint` is used for logging + the Prometheus `site` label — pass
    something like "tool_result:<name>", "entity_history", "rag".
    """
    if not text or not isinstance(text, str):
        return text or "", False

    site = _site_from_hint(source_hint)
    scrubbed = False
    out = text

    # Strict secret scrub (JWT / vendored API key / UUID in key context).
    out, secret_scrubbed = _scrub_secrets(out, site)
    scrubbed = scrubbed or secret_scrubbed

    for pat, replacement in _INJECTION_PATTERNS:
        new = pat.sub(replacement, out)
        if new != out:
            scrubbed = True
            _inc_block("injection", site)
            out = new

    # Neutralise role-ish XML tags (leave other XML alone)
    def _tag_sub(m: re.Match) -> str:
        nonlocal scrubbed
        word = m.group(2).lower()
        if word in _ROLE_WORDS:
            scrubbed = True
            _inc_block("role_tag", site)
            return f"\u2039{m.group(1)}{m.group(2)}\u203a"   # Unicode angle brackets
        return m.group(0)
    out = _ANGLE_ROLE_TAG.sub(_tag_sub, out)

    # Length cap
    if len(out) > max_chars:
        scrubbed = True
        _inc_block("length_cap", site)
        out = out[:max_chars] + f"\n[truncated: was {len(text)} chars]"

    if scrubbed and source_hint:
        log.info("prompt_sanitiser: scrubbed content from %s (len=%d)",
                 source_hint, len(text))

    return out, scrubbed


def sanitize_for_llm(text: str, *, max_chars: int = 8000, source_hint: str = "") -> str:
    """Scope-explicit wrapper around ``sanitise``. Returns cleaned text only.

    Use at any boundary where untrusted text enters an LLM prompt or tool
    result; DO NOT call on outbound API response bodies.
    """
    cleaned, _ = sanitise(text, max_chars=max_chars, source_hint=source_hint)
    return cleaned


def sanitise_dict(d: dict, *, max_chars: int = 2000, source_hint: str = "") -> tuple[dict, bool]:
    """Walk a dict, sanitising string values. Returns (new_dict, any_scrubbed).
    Keys are preserved as-is. Non-string values are passed through."""
    if not isinstance(d, dict):
        return d, False
    out: dict = {}
    any_scrubbed = False
    for k, v in d.items():
        if isinstance(v, str):
            cleaned, scrubbed = sanitise(v, max_chars=max_chars, source_hint=source_hint)
            out[k] = cleaned
            any_scrubbed = any_scrubbed or scrubbed
        elif isinstance(v, dict):
            cleaned_d, scrubbed = sanitise_dict(v, max_chars=max_chars, source_hint=source_hint)
            out[k] = cleaned_d
            any_scrubbed = any_scrubbed or scrubbed
        elif isinstance(v, list):
            cleaned_list = []
            for item in v:
                if isinstance(item, str):
                    ci, scrubbed = sanitise(item, max_chars=max_chars, source_hint=source_hint)
                    cleaned_list.append(ci)
                    any_scrubbed = any_scrubbed or scrubbed
                else:
                    cleaned_list.append(item)
            out[k] = cleaned_list
        else:
            out[k] = v
    return out, any_scrubbed
