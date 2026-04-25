#!/usr/bin/env python3
"""DEATHSTAR sensor stack — agent-optimized linter runner.

Runs the configured set of code sensors (ruff, bandit, gitleaks, eslint, mypy)
across the repo. Outputs failures only, one per line, in a machine-friendly
format with custom HINT lines tuned for this codebase:

    [TOOL] file:line - rule message
      HINT: ...

Exits 1 on any failure, 0 if clean. Tools that aren't installed are skipped
with a one-line notice. Run from the repo root or any subdirectory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUFF_CONFIG = REPO_ROOT / ".ruff.toml"
ESLINT_SENSORS_JSON = REPO_ROOT / ".eslintrc.sensors.json"
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"
GUI_DIR = REPO_ROOT / "gui"


# ─────────────────────────────────────────────────────────────────────────────
# HINT library — calibrated to the DEATHSTAR codebase
# ─────────────────────────────────────────────────────────────────────────────

RUFF_HINTS: dict[str, str] = {
    "C901": (
        "complexity above 80 — split into helpers (see api/agents/step_*.py for the "
        "step_state→step_facts→step_llm pipeline pattern, or pipeline.py for setup "
        "extraction)."
    ),
    "PLR0913": (
        "too many arguments — consolidate into a dataclass. See api/agents/step_state.py "
        "(StepState) or api/agents/context.py for examples."
    ),
    "E501": (
        "line too long (>250). Wrap or extract; long log/SQL strings can use textwrap.dedent "
        "or implicit string concat across lines."
    ),
    "F821": "undefined name — likely a missing import, a typo, or removed variable still referenced.",
    "F811": "redefined while unused — duplicate def/import; remove the unused earlier definition.",
}

BANDIT_HINTS: dict[str, str] = {
    "B105": (
        "hardcoded password string — pull from env via api/connections.py "
        "(Fernet-encrypted) or os.environ; never commit credentials."
    ),
    "B106": (
        "hardcoded password argument — use the existing settings/config pattern "
        "(api/connections.py, encrypted credentials_blob)."
    ),
    "B107": "hardcoded password default — use None and resolve from env at runtime.",
    "B108": "insecure tempfile — use tempfile.mkstemp / NamedTemporaryFile with delete=True.",
    "B404": "subprocess import — ensure shell=False and explicit arg list (see CLAUDE.md → Subprocess policy).",
    "B602": "subprocess with shell=True — REMOVE shell=True; pass an arg list. CLAUDE.md forbids this.",
    "B603": "subprocess without shell — verify the arg list contains no untrusted input.",
    "B608": "possible SQL injection — use parameterised queries via api/db/queries.py.",
}

GITLEAKS_HINTS: dict[str, str] = {
    "deathstar-fernet-key": (
        "Fernet key in source — must live in /opt/hp1-agent/docker/.env "
        "(Ansible-managed, chmod 600). See CLAUDE.md → Key Environment Variables."
    ),
    "deathstar-jwt-token": (
        "JWT token in source — issue via api/auth.py at runtime; never hardcode."
    ),
    "deathstar-api-token-assignment": (
        "API token literal — encrypt via Fernet in api/connections.py.credentials_blob "
        "or load from os.environ."
    ),
    "deathstar-admin-password-literal": (
        "ADMIN_PASSWORD must come from .env (Ansible-managed); never literal in code."
    ),
}

ESLINT_HINTS: dict[str, str] = {
    "complexity": (
        "function complexity above 60 — extract subcomponents or custom hooks. "
        "See gui/src/components/DashboardLayout.jsx for a layered approach."
    ),
    "max-lines": (
        "file > 3000 lines — split by responsibility. ServiceCards.jsx is the "
        "current upper bound; new files should stay well below."
    ),
    "max-params": (
        "function with more than 12 params — group into a single options object."
    ),
    "no-unused-vars": (
        "unused identifier — remove the import/declaration, or prefix with `_` if "
        "intentionally kept (matches varsIgnorePattern)."
    ),
}

MYPY_HINTS: dict[str, str] = {
    "no-untyped-def": "missing type hints — annotate function signature (Python 3.13 native generics OK).",
    "assignment": "incompatible assignment — narrow the type or fix the value.",
    "arg-type": "wrong argument type — check the call site against the function signature.",
    "attr-defined": "attribute access on an unexpected type — verify the object before access.",
    "no-redef": "redefinition — duplicate def/class; remove or rename.",
}


@dataclass
class Failure:
    tool: str
    file: str
    line: int
    rule: str
    message: str

    def hint(self) -> str:
        if self.tool == "ruff":
            return RUFF_HINTS.get(self.rule, "")
        if self.tool == "bandit":
            return BANDIT_HINTS.get(self.rule, "")
        if self.tool == "gitleaks":
            return GITLEAKS_HINTS.get(self.rule, "")
        if self.tool == "eslint":
            return ESLINT_HINTS.get(self.rule, "")
        if self.tool == "mypy":
            return MYPY_HINTS.get(self.rule, "")
        return ""

    def render(self) -> str:
        rel = self.file
        try:
            rel = str(Path(self.file).resolve().relative_to(REPO_ROOT))
        except (ValueError, OSError):
            pass
        rel = rel.replace("\\", "/")
        head = f"[{self.tool.upper()}] {rel}:{self.line} - {self.rule} {self.message}".rstrip()
        hint = self.hint()
        return f"{head}\n  HINT: {hint}" if hint else head


@dataclass
class Result:
    skipped: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    runtime_errors: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Tool runners
# ─────────────────────────────────────────────────────────────────────────────

def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        check=False,
    )


PY_TARGETS = ["api", "mcp_server", "scripts"]


def run_ruff(result: Result) -> None:
    exe = _which("ruff")
    if not exe:
        result.skipped.append("ruff (not installed — pip install ruff)")
        return
    if not RUFF_CONFIG.exists():
        result.runtime_errors.append("ruff: .ruff.toml missing at repo root")
        return
    cmd = [exe, "check", "--no-cache", "--output-format", "json",
           "--config", str(RUFF_CONFIG), *PY_TARGETS]
    try:
        cp = _run(cmd, cwd=REPO_ROOT)
    except subprocess.TimeoutExpired:
        result.runtime_errors.append("ruff: timed out after 300s")
        return
    if cp.returncode not in (0, 1):
        result.runtime_errors.append(f"ruff: exit {cp.returncode}: {cp.stderr.strip()[:300]}")
        return
    try:
        items = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        result.runtime_errors.append("ruff: could not parse JSON output")
        return
    for it in items:
        loc = it.get("location") or {}
        result.failures.append(Failure(
            tool="ruff",
            file=it.get("filename", "?"),
            line=int(loc.get("row", 0) or 0),
            rule=it.get("code", "?"),
            message=it.get("message", "").strip(),
        ))


BANDIT_CONFIG = REPO_ROOT / ".bandit"


def run_bandit(result: Result) -> None:
    exe = _which("bandit")
    if not exe:
        result.skipped.append("bandit (not installed — pip install bandit)")
        return
    cmd = [exe, "-r", *PY_TARGETS, "-f", "json", "-q",
           "--severity-level", "medium", "--confidence-level", "medium"]
    if BANDIT_CONFIG.exists():
        cmd[1:1] = ["-c", str(BANDIT_CONFIG)]
    try:
        cp = _run(cmd, cwd=REPO_ROOT)
    except subprocess.TimeoutExpired:
        result.runtime_errors.append("bandit: timed out after 300s")
        return
    if cp.returncode not in (0, 1):
        result.runtime_errors.append(f"bandit: exit {cp.returncode}: {cp.stderr.strip()[:300]}")
        return
    try:
        payload = json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        result.runtime_errors.append("bandit: could not parse JSON output")
        return
    for it in payload.get("results", []):
        result.failures.append(Failure(
            tool="bandit",
            file=it.get("filename", "?"),
            line=int(it.get("line_number", 0) or 0),
            rule=it.get("test_id", "?"),
            message=(it.get("issue_text") or "").strip(),
        ))


def run_gitleaks(result: Result) -> None:
    exe = _which("gitleaks")
    if not exe:
        result.skipped.append("gitleaks (not installed — see github.com/gitleaks/gitleaks)")
        return
    if not GITLEAKS_CONFIG.exists():
        result.runtime_errors.append("gitleaks: .gitleaks.toml missing at repo root")
        return
    with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as tf:
        report_path = Path(tf.name)
    try:
        # --no-git: scan the working tree only, not git history (avoids
        # noise from old commits that contained sample tokens before the
        # cc_prompts/ allowlist landed).
        cmd = [exe, "detect", "--no-banner", "--no-git",
               "--config", str(GITLEAKS_CONFIG),
               "--report-format", "json", "--report-path", str(report_path),
               "--source", str(REPO_ROOT), "--redact"]
        try:
            cp = _run(cmd, cwd=REPO_ROOT, timeout=600)
        except subprocess.TimeoutExpired:
            result.runtime_errors.append("gitleaks: timed out after 600s")
            return
        if cp.returncode not in (0, 1):
            result.runtime_errors.append(f"gitleaks: exit {cp.returncode}: {cp.stderr.strip()[:300]}")
            return
        if not report_path.exists() or report_path.stat().st_size == 0:
            return
        try:
            findings = json.loads(report_path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            result.runtime_errors.append("gitleaks: could not parse report JSON")
            return
        for it in findings or []:
            result.failures.append(Failure(
                tool="gitleaks",
                file=it.get("File") or "?",
                line=int(it.get("StartLine") or 0),
                rule=it.get("RuleID") or "?",
                message=(it.get("Description") or "").strip(),
            ))
    finally:
        try:
            report_path.unlink()
        except OSError:
            pass


def _build_eslint_flat_config(spec: dict) -> str:
    """Translate the JSON sensor spec into a temporary ESLint v9 flat config."""
    rules_js = json.dumps(spec.get("rules", {}), indent=2)
    ignores_js = json.dumps(spec.get("ignores", []) or [
        "node_modules/**", "dist/**", "**/__tests__/**", "**/*.test.{js,jsx}"
    ])
    return (
        "export default [\n"
        "  {\n"
        "    files: ['**/*.{js,jsx}'],\n"
        "    languageOptions: {\n"
        "      ecmaVersion: 'latest',\n"
        "      sourceType: 'module',\n"
        "      parserOptions: { ecmaFeatures: { jsx: true } },\n"
        "    },\n"
        "    linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: 'off' },\n"
        f"    rules: {rules_js},\n"
        "  },\n"
        f"  {{ ignores: {ignores_js} }},\n"
        "];\n"
    )


def run_eslint(result: Result) -> None:
    if not GUI_DIR.exists():
        result.skipped.append("eslint (gui/ directory missing)")
        return
    eslint_bin = GUI_DIR / "node_modules" / ".bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
    if not eslint_bin.exists():
        # Fall back to a globally installed eslint.
        gpath = _which("eslint")
        if not gpath:
            result.skipped.append("eslint (run `npm install` in gui/ or install eslint globally)")
            return
        eslint_bin = Path(gpath)
    if not ESLINT_SENSORS_JSON.exists():
        result.runtime_errors.append("eslint: .eslintrc.sensors.json missing at repo root")
        return
    try:
        spec = json.loads(ESLINT_SENSORS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.runtime_errors.append(f"eslint: invalid JSON in .eslintrc.sensors.json: {exc}")
        return
    cfg_text = _build_eslint_flat_config(spec)
    cfg_path = GUI_DIR / ".eslint.sensors.generated.mjs"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    try:
        cmd = [str(eslint_bin), "--config", str(cfg_path), "--format", "json", "src/"]
        try:
            cp = _run(cmd, cwd=GUI_DIR, timeout=300)
        except subprocess.TimeoutExpired:
            result.runtime_errors.append("eslint: timed out after 300s")
            return
        # eslint exit codes: 0 = clean, 1 = lint errors, 2 = config error.
        if cp.returncode == 2:
            result.runtime_errors.append(f"eslint: config error: {cp.stderr.strip()[:300]}")
            return
        try:
            files = json.loads(cp.stdout or "[]")
        except json.JSONDecodeError:
            result.runtime_errors.append("eslint: could not parse JSON output")
            return
        for f in files or []:
            for m in f.get("messages", []) or []:
                if (m.get("severity") or 0) < 2:  # 1 = warn, 2 = error
                    continue
                result.failures.append(Failure(
                    tool="eslint",
                    file=f.get("filePath") or "?",
                    line=int(m.get("line") or 0),
                    rule=m.get("ruleId") or "?",
                    message=(m.get("message") or "").strip(),
                ))
    finally:
        try:
            cfg_path.unlink()
        except OSError:
            pass


MYPY_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)? (?P<sev>error|note|warning): (?P<msg>.*?)(?:  \[(?P<code>[a-z0-9_-]+)\])?$")


def run_mypy(result: Result) -> None:
    exe = _which("mypy")
    if not exe:
        result.skipped.append("mypy (not installed — pip install mypy)")
        return
    cmd = [exe, "--no-color-output", "--no-error-summary", "--show-error-codes",
           "--ignore-missing-imports", "--follow-imports=silent",
           "--exclude", r"(^|/)(tests?|node_modules|gui|data|logs|\.venv|venv)(/|$)",
           "api", "mcp_server", "scripts"]
    try:
        cp = _run(cmd, cwd=REPO_ROOT)
    except subprocess.TimeoutExpired:
        result.runtime_errors.append("mypy: timed out after 300s")
        return
    if cp.returncode not in (0, 1):
        result.runtime_errors.append(f"mypy: exit {cp.returncode}: {cp.stderr.strip()[:300]}")
        return
    for line in (cp.stdout or "").splitlines():
        m = MYPY_RE.match(line.strip())
        if not m or m.group("sev") != "error":
            continue
        result.failures.append(Failure(
            tool="mypy",
            file=m.group("file"),
            line=int(m.group("line")),
            rule=m.group("code") or "error",
            message=m.group("msg").strip(),
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

RUNNERS = {
    "ruff": run_ruff,
    "bandit": run_bandit,
    "gitleaks": run_gitleaks,
    "eslint": run_eslint,
    "mypy": run_mypy,
}

# mypy is opt-in: the codebase is largely untyped, so a default run produces
# noise. Use `--only mypy` (or `make mypy`) to run it on demand.
DEFAULT_SENSORS = ["ruff", "bandit", "gitleaks", "eslint"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEATHSTAR sensor stack runner")
    parser.add_argument("--only", help="Comma-separated subset of sensors to run", default="")
    parser.add_argument("--list", action="store_true", help="List available sensors and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name in RUNNERS:
            tag = " (opt-in)" if name not in DEFAULT_SENSORS else ""
            print(f"{name}{tag}")
        return 0

    selected = [s.strip() for s in args.only.split(",") if s.strip()] or list(DEFAULT_SENSORS)
    unknown = [s for s in selected if s not in RUNNERS]
    if unknown:
        print(f"Unknown sensors: {', '.join(unknown)}", file=sys.stderr)
        return 2

    result = Result()
    for name in selected:
        RUNNERS[name](result)

    for line in result.skipped:
        print(f"# skipped: {line}")
    for line in result.runtime_errors:
        print(f"# runtime: {line}", file=sys.stderr)
    for f in result.failures:
        print(f.render())

    return 1 if (result.failures or result.runtime_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
