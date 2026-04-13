#!/usr/bin/env python3
"""
Prompt Queue Runner for Claude Code — Option C (Shadow State)

File ownership:
    INDEX.md         → Claude Desktop SOT (read-only for this runner)
    QUEUE_STATE.json → Runner's internal state (machine-readable)
    QUEUE_STATUS.md  → Runner's live progress view (human-readable, auto-generated)

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
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# ─── ANSI ─────────────────────────────────────────────────────────────────────

class C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"

    @classmethod
    def disable(cls):
        for a in ["BOLD","DIM","RED","GREEN","YELLOW","BLUE","CYAN","MAGENTA","RESET"]:
            setattr(cls, a, "")

if not (sys.stdout.isatty() and os.environ.get("NO_COLOR") is None):
    C.disable()


# ─── Logging ──────────────────────────────────────────────────────────────────

def info(msg):  print(f"{C.BLUE}[queue]{C.RESET} {msg}")
def ok(msg):    print(f"{C.GREEN}[queue]{C.RESET} {msg}")
def warn(msg):  print(f"{C.YELLOW}[queue]{C.RESET} {msg}")
def err(msg):   print(f"{C.RED}[queue]{C.RESET} {msg}", file=sys.stderr)

def banner(text):
    print(f"\n{C.CYAN}{'━'*64}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  {text}{C.RESET}")
    print(f"{C.CYAN}{'━'*64}{C.RESET}")

def prompt_yn(msg: str, default: bool = True) -> bool:
    """Interactive yes/no prompt. Returns default on EOF/non-tty."""
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


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class IndexEntry:
    """A row parsed from INDEX.md."""
    filename: str
    version: str
    theme: str
    status: str
    line_number: int


@dataclass
class StateEntry:
    """Runner's internal tracking for one prompt."""
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
    """Shadow state file — the runner's private ledger."""

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, StateEntry] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("entries", []):
                se = StateEntry(**item)
                self._entries[se.filename] = se

    def save(self):
        data = {
            "updated_at": _now_iso(),
            "entries": [asdict(e) for e in self._entries.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic on POSIX

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
        """
        Scan INDEX.md for PENDING rows not yet in state.
        Returns newly discovered entries.
        """
        new = []
        for ie in index_entries:
            if "PENDING" not in ie.status.upper():
                continue
            if ie.filename in self._entries:
                existing = self._entries[ie.filename]
                if existing.runner_status in ("DONE", "ERROR", "RUNNING", "PENDING"):
                    continue
            se = StateEntry(
                filename=ie.filename,
                version=ie.version,
                theme=ie.theme,
                runner_status="PENDING",
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

def write_status_md(path: Path, state: QueueState):
    """Regenerate human-readable status from current state."""
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
        f"**Progress:** {done}/{total} done"
        + (f" · {errs} error(s)" if errs else "")
        + (f" · {pend} pending" if pend else "")
        + (f" · 1 running" if run else ""),
        "",
    ]

    if total > 0:
        pct = done / total
        filled = int(pct * 30)
        lines += [
            "```",
            f"[{'█' * filled}{'░' * (30 - filled)}] {pct:.0%}",
            "```",
            "",
        ]

    lines += [
        "| Status | File | Version | Theme | SHA | Duration |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        sym = STATUS_SYM.get(e.runner_status, "❓")
        sha = e.commit_sha or "—"
        dur = f"{e.duration_s:.0f}s" if e.duration_s > 0 else "—"
        err_note = f" ⚠ {e.error}" if e.error else ""
        lines.append(
            f"| {sym} {e.runner_status}{err_note} "
            f"| {e.filename} | {e.version} | {e.theme} | {sha} | {dur} |"
        )

    lines += ["", "---", f"*{done + errs} of {total} processed*", ""]

    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


# ─── Sync: merge state → INDEX.md ────────────────────────────────────────────

def sync_to_index(index_path: Path, state: QueueState) -> int:
    """One-time write: merge DONE/ERROR results back into INDEX.md."""
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


# ─── Claude subprocess with real-time streaming ──────────────────────────────

def run_claude(task: str, cwd: Path, log_file: Path, timeout_s: int) -> tuple[int, float]:
    cmd = ["claude", "--print", "--dangerously-skip-permissions"]
    start = time.monotonic()

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
            sys.stdout.write(f"{C.DIM}  │{C.RESET} {line}")
            sys.stdout.flush()
            lf.write(line)
            lf.flush()

        proc.wait(timeout=timeout_s)

    return proc.returncode, time.monotonic() - start


# ─── Countdown display ───────────────────────────────────────────────────────

def countdown(seconds: int):
    end = time.monotonic() + seconds
    try:
        while True:
            left = int(end - time.monotonic())
            if left <= 0:
                break
            m, s = divmod(left, 60)
            sys.stdout.write(
                f"\r{C.DIM}[queue] Next poll in {m}m{s:02d}s · Ctrl+C to stop{C.RESET}   "
            )
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()
        raise


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

def _now_human():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _now_file():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# ─── Terminal display ─────────────────────────────────────────────────────────

def print_table(state: QueueState):
    entries = state.all()
    if not entries:
        info("No entries tracked yet.")
        return
    print(f"\n  {'St':<4} {'Version':<10} {'File':<35} {'Theme':<30} {'SHA':<9} {'Time'}")
    print(f"  {'──':<4} {'───────':<10} {'────':<35} {'─────':<30} {'───':<9} {'────'}")
    for e in entries:
        sym = STATUS_SYM.get(e.runner_status, "?")
        c = {"DONE":C.GREEN,"RUNNING":C.MAGENTA,"PENDING":C.YELLOW,"ERROR":C.RED}.get(e.runner_status, C.DIM)
        sha = e.commit_sha[:7] if e.commit_sha else "—"
        dur = f"{e.duration_s:.0f}s" if e.duration_s else "—"
        th = (e.theme[:27]+"...") if len(e.theme)>30 else e.theme
        print(f"  {c}{sym:<4} {e.version:<10} {e.filename:<35} {th:<30} {sha:<9} {dur}{C.RESET}")
    print()


def print_summary(state: QueueState):
    entries = state.all()
    done = [e for e in entries if e.runner_status == "DONE"]
    errs = [e for e in entries if e.runner_status == "ERROR"]
    banner("Session Summary")
    for e in done:
        print(f"  {C.GREEN}✓{C.RESET} {e.version:<10} {e.filename:<35} → {e.commit_sha} ({e.duration_s:.0f}s)")
    for e in errs:
        print(f"  {C.RED}✗{C.RESET} {e.version:<10} {e.filename:<35} — {e.error}")
    total_t = sum(e.duration_s for e in entries if e.duration_s)
    print(f"\n  {C.BOLD}Total:{C.RESET} {len(done)} ok, {len(errs)} failed, {total_t:.0f}s\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Claude Code Prompt Queue (Shadow State)")
    p.add_argument("--dry-run",     action="store_true",  help="Show status and exit")
    p.add_argument("--one",         action="store_true",  help="Run next pending, then exit")
    p.add_argument("--sync",        action="store_true",  help="Merge state → INDEX.md and exit")
    p.add_argument("--reset",       action="store_true",  help="Clear state (fresh start)")
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

    # Preflight
    if not idx.exists():
        err(f"INDEX.md not found at {idx}")
        sys.exit(1)
    if not shutil.which("claude"):
        err("claude CLI not found. npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    state = QueueState(st_path)

    # ── Commands ──────────────────────────────────────────────────────────
    if args.reset:
        state.reset()
        ok("QUEUE_STATE.json cleared.")
        if md_path.exists():
            md_path.unlink()
        sys.exit(0)

    if args.sync:
        n = sync_to_index(idx, state)
        ok(f"Merged {n} result(s) back into INDEX.md.")
        info("Commit + push INDEX.md when ready.")
        sys.exit(0)

    # ── Init ──────────────────────────────────────────────────────────────
    new = state.discover_new(read_index(idx))
    if new:
        info(f"Discovered {len(new)} new prompt(s) from INDEX.md")

    # Recover crashed RUNNING → PENDING
    stale = state.running_entry()
    if stale:
        warn(f"Stale RUNNING: {stale.filename} → reset to PENDING")
        stale.runner_status = "PENDING"
        state.upsert(stale)

    write_status_md(md_path, state)

    # ── Startup sync check ────────────────────────────────────────────────
    unsynced = [e for e in state.all() if e.runner_status in ("DONE", "ERROR")]
    if unsynced and not args.dry_run:
        warn(f"{len(unsynced)} unsynced result(s) from a previous session:")
        for e in unsynced:
            sym = "✓" if e.runner_status == "DONE" else "✗"
            print(f"  {C.DIM}  {sym} {e.filename} → {e.runner_status}{C.RESET}")
        if prompt_yn("Sync these into INDEX.md now before starting?"):
            n = sync_to_index(idx, state)
            ok(f"Merged {n} result(s) into INDEX.md.")
            # Clear synced entries from state so they don't pile up
            for e in unsynced:
                state._entries.pop(e.filename, None)
            state.save()
            write_status_md(md_path, state)
        else:
            info("Skipped sync — results stay in QUEUE_STATE.json.")

    info(f"Root:    {root}")
    info(f"Branch:  {git_branch(root)}")
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
            sys.exit(130)
        stop = True
        warn("Stopping after current prompt... (again to force)")
    signal.signal(signal.SIGINT, on_sig)

    # ── Watch loop ────────────────────────────────────────────────────────
    runs = 0
    info("Watcher started.\n")

    while not stop:
        # Pick up new prompts from INDEX.md every cycle
        new = state.discover_new(read_index(idx))
        if new:
            info(f"New: {', '.join(e.filename for e in new)}")
            write_status_md(md_path, state)

        entry = state.next_pending()
        if not entry:
            if args.one:
                info("No pending prompts.")
                break
            try:
                countdown(args.poll)
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
            write_status_md(md_path, state)
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
        write_status_md(md_path, state)

        before = git_head(root)
        task = build_task(prompt_path, runner if runner.exists() else None, entry)
        log_file = logd / f"{_now_file()}_{entry.filename.replace('.md','')}.log"

        code, dur = run_claude(task, root, log_file, args.timeout)

        entry.duration_s = dur
        entry.log_file = str(log_file)
        entry.finished_at = _now_iso()

        if code != 0:
            err(f"Exit {code} — log: {log_file}")
            entry.runner_status = "ERROR"
            entry.error = f"exit code {code}"
            state.upsert(entry)
            write_status_md(md_path, state)
            continue

        sha = git_short(root)
        entry.runner_status = "DONE"
        entry.commit_sha = sha
        state.upsert(entry)
        write_status_md(md_path, state)

        ok(f"✓ {entry.version} → {sha} ({dur:.0f}s)")

        if args.one:
            break

        if not stop:
            info("Checking for more...")
            time.sleep(3)

    # ── End ───────────────────────────────────────────────────────────────
    write_status_md(md_path, state)

    if runs > 0:
        print_summary(state)

    info(f"Pending: {state.pending_count()}")

    # ── Exit sync prompt ──────────────────────────────────────────────────
    syncable = [e for e in state.all() if e.runner_status in ("DONE", "ERROR")]
    if syncable:
        print()
        info(f"{len(syncable)} result(s) ready to sync back to INDEX.md:")
        for e in syncable:
            sym = f"{C.GREEN}✓{C.RESET}" if e.runner_status == "DONE" else f"{C.RED}✗{C.RESET}"
            sha = e.commit_sha or e.error
            print(f"    {sym} {e.filename} → {sha}")

        if prompt_yn("\n  Sync into INDEX.md now?"):
            n = sync_to_index(idx, state)
            ok(f"Merged {n} result(s) into INDEX.md.")

            if prompt_yn("  Commit and push INDEX.md?"):
                sha = git_commit_files(
                    "queue: sync results to INDEX.md",
                    [str(idx.relative_to(root))],
                    root,
                )
                ok(f"Committed: {sha}")
                if not args.no_push:
                    if git_push(root):
                        ok("Pushed.")
                    else:
                        warn("Push failed — do it manually.")

            # Clear synced entries
            for e in syncable:
                state._entries.pop(e.filename, None)
            state.save()
            write_status_md(md_path, state)
        else:
            info("Results stay in QUEUE_STATE.json. Run --sync anytime.")

    r = git("log", "--oneline", "-5", cwd=root)
    if r.stdout.strip():
        print(f"\n{C.DIM}  Recent commits:{C.RESET}")
        for ln in r.stdout.strip().splitlines():
            print(f"  {C.DIM}  {ln}{C.RESET}")
        print()


if __name__ == "__main__":
    main()
