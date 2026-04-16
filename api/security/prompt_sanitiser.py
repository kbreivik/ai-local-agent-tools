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


def sanitise(text: str, *, max_chars: int = 8000, source_hint: str = "") -> tuple[str, bool]:
    """Return (cleaned, scrubbed_bool). `scrubbed` is True if any pattern fired.

    `source_hint` is only used for logging — e.g. "container_name", "log_line".
    """
    if not text or not isinstance(text, str):
        return text or "", False

    scrubbed = False
    out = text

    for pat, replacement in _INJECTION_PATTERNS:
        new = pat.sub(replacement, out)
        if new != out:
            scrubbed = True
            out = new

    # Neutralise role-ish XML tags (leave other XML alone)
    def _tag_sub(m: re.Match) -> str:
        nonlocal scrubbed
        word = m.group(2).lower()
        if word in _ROLE_WORDS:
            scrubbed = True
            return f"\u2039{m.group(1)}{m.group(2)}\u203a"   # Unicode angle brackets
        return m.group(0)
    out = _ANGLE_ROLE_TAG.sub(_tag_sub, out)

    # Length cap
    if len(out) > max_chars:
        scrubbed = True
        out = out[:max_chars] + f"\n[truncated: was {len(text)} chars]"

    if scrubbed and source_hint:
        log.info("prompt_sanitiser: scrubbed content from %s (len=%d)",
                 source_hint, len(text))

    return out, scrubbed


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
