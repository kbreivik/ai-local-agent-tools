#!/usr/bin/env python3
"""
Prompt Queue Runner for Claude Code — Option C (Shadow State)

File ownership:
    INDEX.md         → Claude Desktop SOT (read-only for this runner)
    QUEUE_STATE.json → Runner's internal state (machine-readable)
    QUEUE_STATUS.md  → Runner's live progress view (human-readable, auto-generated)

Features:
    - Live terminal title bar: model, cost, tokens, elapsed, queue progress
    - Periodic inline status lines during long prompts
    - Cumulative cost/token tracking across session
    - Interactive sync on startup (previous results) and shutdown (Ctrl+C)

Usage:
    python run_queue.py                  # persistent watcher, 3 min poll
    python run_queue.py --poll 60        # poll every 60s
    python run_queue.py --one            # run next pending, then exit
    python run_queue.py --dry-run        # show current status
    python run_queue.py --sync           # merge state back into INDEX.md and exit
    python run_queue.py --reset          # clear QUEUE_STATE.json (fresh start)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


# ─── ANSI ─────────────────────────────────────────────────────────────────────

class C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"
    WHITE = "\033[37m"

    @classmethod
    def disable(cls):
        for a in ["BOLD","DIM","RED","GREEN","YELLOW","BLUE","CYAN","MAGENTA","WHITE","RESET"]:
            setattr(cls, a, "")

_tty = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
if not _tty:
    C.disable()


# ─── Terminal title ───────────────────────────────────────────────────────────

def set_title(text: str):
    """Set terminal window/tab title via OSC escape. Works on Windows Terminal,
    iTerm2, most Linux terminals."""
    if _tty:
        sys.stdout.write(f"\033]0;{text}\007")
        sys.stdout.flush()

def clear_title():
    set_title("")


# ─── Logging ──────────────────────────────────────────────────────────────────

def info(msg):  print(f"{C.BLUE}[queue]{C.RESET} {msg}")
def ok(msg):    print(f"{C.GREEN}[queue]{C.RESET} {msg}")
def warn(msg):  print(f"{C.YELLOW}[queue]{C.RESET} {msg}")
def err(msg):   print(f"{C.RED}[queue]{C.RESET} {msg}", file=sys.stderr)

def banner(text):
    print(f"\n{C.CYAN}{'━'*72}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  {text}{C.RESET}")
    print(f"{C.CYAN}{'━'*72}{C.RESET}")

def prompt_yn(msg: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        if not sys.stdin.isatty():
            return default
        answer = input(f"{C.YELLOW}[queue]{C.RESET} {msg} ({hint}) ").strip().lower()
        if not answer:
            return default
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def fmt_duration(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    m, sec = divmod(int(s), 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"

def fmt_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}k"
    return f"{n/1_000_000:.2f}M"

def fmt_cost(usd: float) -> str:
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.2f}"


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class IndexEntry:
    filename: str
    version: str
    theme: str
    status: str
    line_number: int


@dataclass
class StateEntry:
    filename: str
    version: str
    theme: str
    runner_status: str   # PENDING | RUNNING | DONE | ERROR
    commit_sha: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    log_file: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass
class SessionStats:
    """Cumulative stats for the entire runner session."""
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    prompts_done: int = 0
    prompts_failed: int = 0
    prompts_total: int = 0
    session_start: float = field(default_factory=time.monotonic)
    current_prompt: str = ""
    current_version: str = ""
    current_start: float = 0.0
    model: str = ""
    branch: str = ""

    def title_string(self) -> str:
        """Build the terminal title bar string."""
        parts = []

        # Model
        if self.model:
            parts.append(self.model)

        # Cost
        parts.append(fmt_cost(self.total_cost))

        # Tokens
        total_tok = self.total_input_tokens + self.total_output_tokens
        if total_tok > 0:
            parts.append(f"{fmt_tokens(total_tok)} tok")

        # Queue progress
        done = self.prompts_done + self.prompts_failed
        parts.append(f"{done}/{self.prompts_total} done")

        # Current prompt elapsed
        if self.current_start > 0:
            elapsed = time.monotonic() - self.current_start
            parts.append(f"⏱ {fmt_duration(elapsed)}")

        # Current prompt name
        if self.current_prompt:
            parts.append(self.current_version or self.current_prompt)

        # Session elapsed
        session_elapsed = time.monotonic() - self.session_start
        parts.append(f"session {fmt_duration(session_elapsed)}")

        # Branch
        if self.branch:
            parts.append(self.branch)

        return " │ ".join(parts)

    def inline_status(self) -> str:
        """Build an inline status line for periodic display during execution."""
        parts = []
        done = self.prompts_done + self.prompts_failed
        parts.append(f"Queue {done}/{self.prompts_total}")
        parts.append(fmt_cost(self.total_cost))
        total_tok = self.total_input_tokens + self.total_output_tokens
        if total_tok:
            parts.append(f"{fmt_tokens(total_tok)} tok")
        if self.current_start > 0:
            parts.append(f"⏱ {fmt_duration(time.monotonic() - self.current_start)}")
        if self.model:
            parts.append(self.model)
        return " · ".join(parts)


# ─── Title updater thread ────────────────────────────────────────────────────

class TitleUpdater:
    """Background thread that updates terminal title every second."""

    def __init__(self, stats: SessionStats):
        self.stats = stats
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            try:
                set_title(self.stats.title_string())
            except Exception:
                pass
            self._stop.wait(1.0)


# ─── INDEX.md parser (read-only) ─────────────────────────────────────────────

ROW_RE = re.compile(
    r"\|\s*(?P<file>[^|]+?)\s*"
    r"\|\s*(?P<ver>[^|]+?)\s*"
    r"\|\s*(?P<theme>[^|]+?)\s*"
    r"\|\s*(?P<status>[^|]+?)\s*\|"
)

def read_index(path: Path) -> list[IndexEntry]:
    if not path.exists():
        return []
    entries = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if "---" in line and "|" in line:
            continue
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        fname = m.group("file").strip()
        if not fname.upper().endswith(".MD"):
            continue
        entries.append(IndexEntry(
            filename=fname,
            version=m.group("ver").strip(),
            theme=m.group("theme").strip(),
            status=m.group("status").strip(),
            line_number=i,
        ))
    return entries


# ─── QUEUE_STATE.json ─────────────────────────────────────────────────────────

class QueueState:
    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, StateEntry] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("entries", []):
                se = StateEntry(**{k: v for k, v in item.items() if k in StateEntry.__dataclass_fields__})
                self._entries[se.filename] = se

    def save(self):
        data = {
            "updated_at": _now_iso(),
            "entries": [asdict(e) for e in self._entries.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, filename: str) -> Optional[StateEntry]:
        return self._entries.get(filename)

    def upsert(self, entry: StateEntry):
        self._entries[entry.filename] = entry
        self.save()

    def all(self) -> list[StateEntry]:
        return list(self._entries.values())

    def reset(self):
        self._entries.clear()
        self.save()

    def discover_new(self, index_entries: list[IndexEntry]) -> list[StateEntry]:
        new = []
        for ie in index_entries:
            if "PENDING" not in ie.status.upper():
                continue
            if ie.filename in self._entries:
                continue
            se = StateEntry(
                filename=ie.filename, version=ie.version,
                theme=ie.theme, runner_status="PENDING",
            )
            self._entries[se.filename] = se
            new.append(se)
        if new:
            self.save()
        return new

    def next_pending(self) -> Optional[StateEntry]:
        for e in self._entries.values():
            if e.runner_status == "PENDING":
                return e
        return None

    def pending_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.runner_status == "PENDING")

    def running_entry(self) -> Optional[StateEntry]:
        for e in self._entries.values():
            if e.runner_status == "RUNNING":
                return e
        return None


# ─── QUEUE_STATUS.md writer ──────────────────────────────────────────────────

STATUS_SYM = {"PENDING": "⏳", "RUNNING": "🔄", "DONE": "✅", "ERROR": "❌"}

def write_status_md(path: Path, state: QueueState, stats: Optional[SessionStats] = None):
    entries = state.all()
    total = len(entries)
    done  = sum(1 for e in entries if e.runner_status == "DONE")
    errs  = sum(1 for e in entries if e.runner_status == "ERROR")
    pend  = sum(1 for e in entries if e.runner_status == "PENDING")
    run   = sum(1 for e in entries if e.runner_status == "RUNNING")

    lines = [
        "# Queue Status",
        "",
        f"> Auto-generated by run_queue.py — {_now_human()}",
        "",
    ]

    # Summary line
    summary = f"**Progress:** {done}/{total} done"
    if errs: summary += f" · {errs} error(s)"
    if pend: summary += f" · {pend} pending"
    if run:  summary += f" · 1 running"
    lines.append(summary)

    # Cost summary
    total_cost = sum(e.cost_usd for e in entries)
    total_in = sum(e.input_tokens for e in entries)
    total_out = sum(e.output_tokens for e in entries)
    if total_cost > 0:
        lines.append(
            f"**Cost:** {fmt_cost(total_cost)} · "
            f"{fmt_tokens(total_in)} in / {fmt_tokens(total_out)} out"
        )
    lines.append("")

    # Progress bar
    if total > 0:
        pct = done / total
        filled = int(pct * 30)
        lines += ["```", f"[{'█'*filled}{'░'*(30-filled)}] {pct:.0%}", "```", ""]

    # Table
    lines += [
        "| Status | File | Version | Theme | SHA | Duration | Cost | Tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        sym = STATUS_SYM.get(e.runner_status, "❓")
        sha = e.commit_sha or "—"
        dur = fmt_duration(e.duration_s) if e.duration_s > 0 else "—"
        cost = fmt_cost(e.cost_usd) if e.cost_usd > 0 else "—"
        tok = fmt_tokens(e.input_tokens + e.output_tokens) if (e.input_tokens + e.output_tokens) > 0 else "—"
        err_note = f" ⚠ {e.error}" if e.error else ""
        lines.append(
            f"| {sym} {e.runner_status}{err_note} "
            f"| {e.filename} | {e.version} | {e.theme} "
            f"| {sha} | {dur} | {cost} | {tok} |"
        )
    lines += ["", "---", f"*{done + errs} of {total} processed*", ""]

    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


# ─── Sync: merge state → INDEX.md ────────────────────────────────────────────

def sync_to_index(index_path: Path, state: QueueState) -> int:
    if not index_path.exists():
        err("INDEX.md not found")
        return 0
    lines = index_path.read_text(encoding="utf-8").splitlines()
    count = 0
    for se in state.all():
        if se.runner_status not in ("DONE", "ERROR"):
            continue
        new_status = (
            f"DONE ({se.commit_sha})" if se.runner_status == "DONE"
            else f"ERROR ({se.error})"
        )
        for i, line in enumerate(lines):
            if se.filename in line and ("PENDING" in line or "RUNNING" in line):
                lines[i] = re.sub(
                    r"\|\s*(PENDING|RUNNING)\s*\|",
                    f"| {new_status} |",
                    line, count=1,
                )
                count += 1
                break
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def update_index_entry(index_path: Path, entry: StateEntry):
    """Update a single entry's status in INDEX.md immediately.
    Handles PENDING→RUNNING, PENDING→DONE, RUNNING→DONE, RUNNING→ERROR, etc."""
    if not index_path.exists():
        return
    lines = index_path.read_text(encoding="utf-8").splitlines()

    if entry.runner_status == "DONE":
        new_status = f"DONE ({entry.commit_sha})"
    elif entry.runner_status == "ERROR":
        new_status = f"ERROR ({entry.error})"
    elif entry.runner_status == "RUNNING":
        new_status = "RUNNING"
    else:
        return

    for i, line in enumerate(lines):
        if entry.filename in line and ("PENDING" in line or "RUNNING" in line):
            lines[i] = re.sub(
                r"\|\s*(PENDING|RUNNING)\s*\|",
                f"| {new_status} |",
                line, count=1,
            )
            break
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Git helpers ──────────────────────────────────────────────────────────────

def git(*args, cwd=None):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)

def git_head(cwd):   return git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
def git_short(cwd):  return git("rev-parse", "--short", "HEAD", cwd=cwd).stdout.strip()
def git_branch(cwd): return git("branch", "--show-current", cwd=cwd).stdout.strip()

def git_push(cwd):
    return git("push", cwd=cwd).returncode == 0

def git_commit_files(msg, files, cwd):
    for f in files:
        git("add", f, cwd=cwd)
    git("commit", "-m", msg, cwd=cwd)
    return git_short(cwd)


# ─── Task builder ─────────────────────────────────────────────────────────────

def build_task(prompt_path: Path, runner_path: Optional[Path], entry: StateEntry) -> str:
    parts = ["You are running in automated queue mode.", ""]
    if runner_path and runner_path.exists():
        parts += [runner_path.read_text(encoding="utf-8"), "", "---", ""]
    parts += [
        f"Prompt: {entry.filename} ({entry.version})",
        f"Theme: {entry.theme}",
        "", "Prompt content:", "",
        prompt_path.read_text(encoding="utf-8"),
        "", "---", "",
        "After implementing, commit and push your changes.",
        "Do NOT modify INDEX.md or any queue status files — the runner handles that.",
    ]
    return "\n".join(parts)


# ─── Claude subprocess with stream-json parsing ──────────────────────────────

@dataclass
class ClaudeResult:
    exit_code: int
    duration_s: float
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


def run_claude(
    task: str, cwd: Path, log_file: Path, timeout_s: int,
    stats: Optional[SessionStats] = None,
) -> ClaudeResult:
    """
    Run claude --print with real-time output streaming.
    Uses plain text mode for readable output. Attempts to parse cost/token
    info from Claude Code's summary lines if present.
    """
    cmd = ["claude", "--print", "--dangerously-skip-permissions"]
    start = time.monotonic()

    cost = 0.0
    in_tok = 0
    out_tok = 0
    model = ""
    last_status_time = start
    STATUS_INTERVAL = 30

    with open(log_file, "w", encoding="utf-8") as lf:
        lf.write(f"{'='*72}\nTASK INPUT\n{'='*72}\n{task}\n")
        lf.write(f"{'='*72}\nCLAUDE OUTPUT — {_now_human()}\n{'='*72}\n")
        lf.flush()

        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=cwd, text=True, bufsize=1,
        )
        proc.stdin.write(task)
        proc.stdin.close()

        for line in proc.stdout:
            now = time.monotonic()

            # Display the line
            sys.stdout.write(f"{C.DIM}  │{C.RESET} {line}")
            sys.stdout.flush()
            lf.write(line)
            lf.flush()

            # Try to extract cost/token info from Claude Code output lines
            # Claude Code sometimes prints summary lines like:
            #   "Cost: $0.42 | Tokens: 12345 in, 678 out"
            #   or JSON snippets with usage data
            stripped = line.strip()
            try:
                # Check if line is a JSON object with usage data
                if stripped.startswith("{") and stripped.endswith("}"):
                    data = json.loads(stripped)
                    if "cost_usd" in data:
                        cost = data["cost_usd"] or cost
                    if "total_cost_usd" in data:
                        cost = data["total_cost_usd"] or cost
                    if "model" in data and data["model"]:
                        model = data["model"]
                    if "usage" in data and isinstance(data["usage"], dict):
                        u = data["usage"]
                        in_tok = u.get("input_tokens", in_tok) or in_tok
                        out_tok = u.get("output_tokens", out_tok) or out_tok
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

            # Update stats for title bar
            if stats:
                if model:
                    stats.model = model

            # Periodic inline status
            if now - last_status_time >= STATUS_INTERVAL:
                elapsed = now - start
                status_parts = [fmt_duration(elapsed)]
                if cost > 0:
                    status_parts.append(fmt_cost(cost))
                if model:
                    status_parts.append(model)
                status_line = " · ".join(status_parts)
                sys.stdout.write(
                    f"{C.DIM}  ├─ {status_line}{C.RESET}\n"
                )
                sys.stdout.flush()
                lf.write(f"[STATUS] {status_line}\n")
                lf.flush()
                last_status_time = now

        proc.wait(timeout=timeout_s)

        # Write final stats to log
        lf.write(f"\n{'='*72}\n")
        lf.write(f"EXIT CODE: {proc.returncode}\n")
        lf.write(f"DURATION:  {fmt_duration(time.monotonic() - start)}\n")
        lf.write(f"{'='*72}\n")

    return ClaudeResult(
        exit_code=proc.returncode,
        duration_s=time.monotonic() - start,
        cost_usd=cost,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model,
    )


# ─── Countdown display ───────────────────────────────────────────────────────

def countdown(seconds: int, stats: Optional[SessionStats] = None):
    end = time.monotonic() + seconds
    try:
        while True:
            left = int(end - time.monotonic())
            if left <= 0:
                break
            m, s = divmod(left, 60)
            extra = ""
            if stats and stats.total_cost > 0:
                extra = f" · session {fmt_cost(stats.total_cost)}"
            sys.stdout.write(
                f"\r{C.DIM}[queue] Next poll in {m}m{s:02d}s{extra} · Ctrl+C to stop{C.RESET}   "
            )
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        raise


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso():   return datetime.datetime.now().isoformat(timespec="seconds")
def _now_human(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _now_file():  return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# ─── Terminal display ─────────────────────────────────────────────────────────

def print_table(state: QueueState):
    entries = state.all()
    if not entries:
        info("No entries tracked yet.")
        return
    print(f"\n  {'St':<4} {'Version':<10} {'File':<35} {'Cost':<9} {'SHA':<9} {'Time'}")
    print(f"  {'──':<4} {'───────':<10} {'────':<35} {'────':<9} {'───':<9} {'────'}")
    for e in entries:
        sym = STATUS_SYM.get(e.runner_status, "?")
        c = {"DONE":C.GREEN,"RUNNING":C.MAGENTA,"PENDING":C.YELLOW,"ERROR":C.RED}.get(e.runner_status, C.DIM)
        sha = e.commit_sha[:7] if e.commit_sha else "—"
        dur = fmt_duration(e.duration_s) if e.duration_s else "—"
        cost = fmt_cost(e.cost_usd) if e.cost_usd > 0 else "—"
        print(f"  {c}{sym:<4} {e.version:<10} {e.filename:<35} {cost:<9} {sha:<9} {dur}{C.RESET}")
    print()


def print_summary(state: QueueState, stats: SessionStats):
    entries = state.all()
    done_entries = [e for e in entries if e.runner_status == "DONE"]
    err_entries  = [e for e in entries if e.runner_status == "ERROR"]

    banner("Session Summary")

    for e in done_entries:
        cost = fmt_cost(e.cost_usd) if e.cost_usd > 0 else ""
        tok = fmt_tokens(e.input_tokens + e.output_tokens) if (e.input_tokens + e.output_tokens) > 0 else ""
        extra = f"  {cost}  {tok}".rstrip()
        print(f"  {C.GREEN}✓{C.RESET} {e.version:<10} {e.filename:<35} → {e.commit_sha} ({fmt_duration(e.duration_s)}){extra}")
    for e in err_entries:
        print(f"  {C.RED}✗{C.RESET} {e.version:<10} {e.filename:<35} — {e.error}")

    # Totals
    total_t = sum(e.duration_s for e in entries if e.duration_s)
    total_c = stats.total_cost
    total_tok = stats.total_input_tokens + stats.total_output_tokens
    parts = [f"{len(done_entries)} ok, {len(err_entries)} failed, {fmt_duration(total_t)}"]
    if total_c > 0:
        parts.append(fmt_cost(total_c))
    if total_tok > 0:
        parts.append(f"{fmt_tokens(total_tok)} tokens")
    if stats.model:
        parts.append(stats.model)

    print(f"\n  {C.BOLD}Total:{C.RESET} {' · '.join(parts)}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Claude Code Prompt Queue (Shadow State)")
    p.add_argument("--dry-run",     action="store_true",  help="Show status and exit")
    p.add_argument("--one",         action="store_true",  help="Run next pending, then exit")
    p.add_argument("--sync",        action="store_true",  help="Merge state → INDEX.md and exit")
    p.add_argument("--reset",       action="store_true",  help="Clear state (fresh start)")
    p.add_argument("--retry",       action="store_true",  help="Reset ERROR entries back to PENDING")
    p.add_argument("--poll",        type=int, default=180,help="Poll interval seconds (default 180)")
    p.add_argument("--prompts-dir", type=str, default="cc_prompts")
    p.add_argument("--log-dir",     type=str, default=None)
    p.add_argument("--timeout",     type=int, default=600)
    p.add_argument("--max-runs",    type=int, default=20)
    p.add_argument("--no-push",     action="store_true")
    args = p.parse_args()

    root    = Path.cwd()
    pdir    = root / args.prompts_dir
    idx     = pdir / "INDEX.md"
    runner  = pdir / "QUEUE_RUNNER.md"
    logd    = Path(args.log_dir) if args.log_dir else pdir / "logs"
    st_path = pdir / "QUEUE_STATE.json"
    md_path = pdir / "QUEUE_STATUS.md"

    if not idx.exists():
        err(f"INDEX.md not found at {idx}")
        sys.exit(1)
    if not shutil.which("claude"):
        err("claude CLI not found. npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    state = QueueState(st_path)

    # ── Reset ─────────────────────────────────────────────────────────────
    if args.reset:
        state.reset()
        ok("QUEUE_STATE.json cleared.")
        if md_path.exists():
            md_path.unlink()
        sys.exit(0)

    # ── Retry (reset ERRORs → PENDING) ────────────────────────────────────
    if args.retry:
        error_entries = [e for e in state.all() if e.runner_status == "ERROR"]
        if not error_entries:
            info("No ERROR entries to retry.")
            sys.exit(0)
        # Reset in state
        for e in error_entries:
            e.runner_status = "PENDING"
            e.error = ""
            e.started_at = ""
            e.finished_at = ""
            e.duration_s = 0.0
            e.log_file = ""
            e.cost_usd = 0.0
            e.input_tokens = 0
            e.output_tokens = 0
            state.upsert(e)
        # Reset in INDEX.md
        if idx.exists():
            lines = idx.read_text(encoding="utf-8").splitlines()
            for e in error_entries:
                for i, line in enumerate(lines):
                    if e.filename in line and "ERROR" in line:
                        lines[i] = re.sub(
                            r"\|\s*ERROR\s*\([^)]*\)\s*\|",
                            "| PENDING |",
                            line, count=1,
                        )
                        break
            idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok(f"Reset {len(error_entries)} ERROR entry/entries back to PENDING:")
        for e in error_entries:
            print(f"  {C.YELLOW}⏳{C.RESET} {e.filename}")
        info("Run again to process them.")
        sys.exit(0)

    # ── Sync (manual) ─────────────────────────────────────────────────────
    if args.sync:
        n = sync_to_index(idx, state)
        ok(f"Merged {n} result(s) into INDEX.md.")
        info("Commit + push INDEX.md when ready.")
        sys.exit(0)

    # ── Init ──────────────────────────────────────────────────────────────
    new = state.discover_new(read_index(idx))
    if new:
        info(f"Discovered {len(new)} new prompt(s) from INDEX.md")

    stale = state.running_entry()
    if stale:
        warn(f"Stale RUNNING: {stale.filename} → reset to PENDING")
        stale.runner_status = "PENDING"
        state.upsert(stale)

    stats = SessionStats(
        prompts_total=state.pending_count(),
        branch=git_branch(root),
    )

    write_status_md(md_path, state, stats)

    # ── Startup cleanup ─────────────────────────────────────────────────
    # If previous session crashed before cleaning state, completed entries
    # may still be in QUEUE_STATE.json. INDEX.md was already updated live,
    # so just clean them out.
    stale_completed = [e for e in state.all() if e.runner_status in ("DONE", "ERROR")]
    if stale_completed and not args.dry_run:
        info(f"Cleaning {len(stale_completed)} completed entry/entries from previous session state.")
        # Ensure INDEX.md has the results (in case of crash before write)
        sync_to_index(idx, state)
        for e in stale_completed:
            state._entries.pop(e.filename, None)
        state.save()
        write_status_md(md_path, state, stats)

    info(f"Root:    {root}")
    info(f"Branch:  {stats.branch}")
    info(f"Tracked: {len(state.all())} · Pending: {state.pending_count()}")
    info(f"State:   {st_path.name} · Status: {md_path.name}")
    info(f"Poll:    {args.poll}s")

    if args.dry_run:
        print_table(state)
        sys.exit(0)

    logd.mkdir(parents=True, exist_ok=True)

    # ── Signals ───────────────────────────────────────────────────────────
    stop = False
    def on_sig(sig, frame):
        nonlocal stop
        if stop:
            err("Force quit.")
            clear_title()
            sys.exit(130)
        stop = True
        warn("Stopping after current prompt... (again to force)")
    signal.signal(signal.SIGINT, on_sig)

    # ── Title updater ─────────────────────────────────────────────────────
    title_updater = TitleUpdater(stats)
    title_updater.start()

    # ── Watch loop ────────────────────────────────────────────────────────
    runs = 0
    info("Watcher started.\n")

    try:
        while not stop:
            new = state.discover_new(read_index(idx))
            if new:
                info(f"New: {', '.join(e.filename for e in new)}")
                stats.prompts_total += len(new)
                write_status_md(md_path, state, stats)

            entry = state.next_pending()
            if not entry:
                if args.one:
                    info("No pending prompts.")
                    break
                try:
                    countdown(args.poll, stats)
                except KeyboardInterrupt:
                    stop = True
                continue

            prompt_path = pdir / entry.filename
            if not prompt_path.exists():
                err(f"Missing: {prompt_path}")
                entry.runner_status = "ERROR"
                entry.error = "file not found"
                entry.finished_at = _now_iso()
                state.upsert(entry)
                update_index_entry(idx, entry)
                stats.prompts_failed += 1
                write_status_md(md_path, state, stats)
                continue

            runs += 1
            if runs > args.max_runs:
                warn(f"Safety cap ({args.max_runs}). Restart to continue.")
                break

            banner(f"[{runs}] {entry.version} — {entry.filename}  ({state.pending_count()} pending)")
            info(f"Theme: {entry.theme}")

            # Mark RUNNING
            entry.runner_status = "RUNNING"
            entry.started_at = _now_iso()
            state.upsert(entry)
            update_index_entry(idx, entry)

            stats.current_prompt = entry.filename
            stats.current_version = entry.version
            stats.current_start = time.monotonic()

            write_status_md(md_path, state, stats)

            task = build_task(prompt_path, runner if runner.exists() else None, entry)
            log_file = logd / f"{_now_file()}_{entry.filename.replace('.md','')}.log"

            result = run_claude(task, root, log_file, args.timeout, stats)

            entry.duration_s = result.duration_s
            entry.log_file = str(log_file)
            entry.finished_at = _now_iso()
            entry.cost_usd = result.cost_usd
            entry.input_tokens = result.input_tokens
            entry.output_tokens = result.output_tokens
            entry.model = result.model

            stats.current_prompt = ""
            stats.current_version = ""
            stats.current_start = 0
            stats.total_cost += result.cost_usd
            stats.total_input_tokens += result.input_tokens
            stats.total_output_tokens += result.output_tokens
            if result.model:
                stats.model = result.model

            if result.exit_code != 0:
                err(f"Exit {result.exit_code} — log: {log_file}")
                entry.runner_status = "ERROR"
                entry.error = f"exit code {result.exit_code}"
                stats.prompts_failed += 1
                state.upsert(entry)
                update_index_entry(idx, entry)
                write_status_md(md_path, state, stats)
                continue

            sha = git_short(root)
            entry.runner_status = "DONE"
            entry.commit_sha = sha
            stats.prompts_done += 1
            state.upsert(entry)
            update_index_entry(idx, entry)
            write_status_md(md_path, state, stats)

            # Result line with cost info
            parts = [f"✓ {entry.version} → {sha} ({fmt_duration(result.duration_s)})"]
            if result.cost_usd > 0:
                parts.append(fmt_cost(result.cost_usd))
            if result.input_tokens + result.output_tokens > 0:
                parts.append(f"{fmt_tokens(result.input_tokens + result.output_tokens)} tok")
            ok(" · ".join(parts))

            if args.one:
                break

            if not stop:
                info("Checking for more...")
                time.sleep(3)

    finally:
        title_updater.stop()
        clear_title()

    # ── End ───────────────────────────────────────────────────────────────
    write_status_md(md_path, state, stats)

    if runs > 0:
        print_summary(state, stats)

    info(f"Pending: {state.pending_count()}")

    # ── Exit sync prompt ──────────────────────────────────────────────────
    completed = [e for e in state.all() if e.runner_status in ("DONE", "ERROR")]
    if completed:
        print()
        info(f"INDEX.md already updated for {len(completed)} prompt(s).")

        # Check if there are uncommitted INDEX.md changes to push
        idx_diff = git("diff", "--name-only", str(idx.relative_to(root)), cwd=root)
        idx_staged = git("diff", "--cached", "--name-only", str(idx.relative_to(root)), cwd=root)
        has_changes = bool(idx_diff.stdout.strip() or idx_staged.stdout.strip())

        if has_changes and prompt_yn("Commit and push INDEX.md?"):
            sha = git_commit_files(
                "queue: mark completed prompts in INDEX.md",
                [str(idx.relative_to(root))],
                root,
            )
            ok(f"Committed: {sha}")
            if not args.no_push:
                if git_push(root):
                    ok("Pushed.")
                else:
                    warn("Push failed — do it manually.")

        # Clean completed entries from state so they don't nag on next start
        for e in completed:
            state._entries.pop(e.filename, None)
        state.save()
        write_status_md(md_path, state, stats)

    # Recent commits
    r = git("log", "--oneline", "-5", cwd=root)
    if r.stdout.strip():
        print(f"\n{C.DIM}  Recent commits:{C.RESET}")
        for ln in r.stdout.strip().splitlines():
            print(f"  {C.DIM}  {ln}{C.RESET}")
        print()


if __name__ == "__main__":
    main()
