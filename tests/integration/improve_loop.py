"""
Improvement loop — runs tests repeatedly, reports failures, pauses for fixes.

Usage:
    python -m tests.integration.improve_loop
    python -m tests.integration.improve_loop --rounds 3 --category safety
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from tests.integration.test_agent import (
    TEST_CASES, run_all_tests, save_results, print_summary,
)

FIX_PROMPT_PATH = Path(__file__).parent.parent / "fix_prompt.txt"


def _build_fix_prompt(failures: list) -> str:
    lines = []
    for r in failures:
        lines.append(f"TASK: {r.task}")
        lines.append(f"CATEGORY: {r.category}")
        lines.append(f"AGENT_TYPE_SEEN: {r.agent_type}")
        lines.append(f"TOOLS_USED: {r.tools_used}")
        for f in r.failures:
            lines.append(f"  FAIL: {f}")
        for w in r.warnings:
            lines.append(f"  WARN: {w}")
        lines.append("")

    failure_block = "\n".join(lines)

    crits = [r for r in failures if r.critical]
    crit_note = ""
    if crits:
        crit_note = f"\n⛔ CRITICAL failures ({len(crits)}) — fix these first:\n" + "\n".join(
            f"  {r.id}: {r.failures[0]}" for r in crits if r.failures
        ) + "\n"

    return f"""The following HP1 agent integration tests failed. Fix the issues.
{crit_note}
FAILURES:
{failure_block}
Rules:
- Only fix what's failing — don't change passing behavior
- Safety tests (destructive tool without plan) are CRITICAL — fix first
- Soft tests are advisory — fix if easy, skip if complex
- After fixing, the test runner will re-evaluate automatically

Files most likely to need changes:
  api/routers/agent.py      — SYSTEM_PROMPT, routing, tool intercepts
  api/agents/router.py      — classify_task keywords, prompts, tool allowlists
  mcp_server/tools/         — tool implementations
  api/memory/hooks.py       — before_tool_call injection

Begin fixes now.
"""


async def improvement_loop(
    max_rounds: int = 5,
    categories: list[str] | None = None,
    auto: bool = False,
) -> None:
    print(f"\n{'═'*55}")
    print(f"  HP1 Agent Improvement Loop  (max {max_rounds} rounds)")
    print(f"{'═'*55}\n")

    for round_n in range(1, max_rounds + 1):
        print(f"\n{'─'*40}")
        print(f"  ROUND {round_n}/{max_rounds}  —  {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'─'*40}\n")

        results = await run_all_tests(categories=categories)
        save_results(results)

        hard    = [r for r in results if not r.soft]
        passed  = sum(1 for r in hard if r.passed)
        total   = len(hard)
        score   = round(passed / total * 100) if total else 0
        failures = [r for r in results if not r.passed]

        print(f"\n  Score: {passed}/{total} ({score}%)")

        if not failures:
            print("  ✓ All tests passed!\n")
            break

        if score >= 90:
            print(f"  ✓ Score {score}% ≥ 90% target — stopping.\n")
            break

        # Write fix prompt
        fix_prompt = _build_fix_prompt(failures)
        FIX_PROMPT_PATH.write_text(fix_prompt)
        print(f"\n  Fix prompt written → {FIX_PROMPT_PATH}")
        print(f"  Failures: {len(failures)}")

        if round_n == max_rounds:
            print(f"\n  Max rounds reached. Final score: {score}%")
            break

        if auto:
            print("\n  [auto mode] Re-running immediately…")
            await asyncio.sleep(2)
        else:
            print("\n  Apply fixes in Claude Code, then press Enter to re-test…")
            print(f"  (Fix prompt: {FIX_PROMPT_PATH})")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                break

    print_summary(results)


def main():
    parser = argparse.ArgumentParser(description="HP1 Agent Improvement Loop")
    parser.add_argument("--rounds", "-r", type=int, default=5, help="Max improvement rounds")
    parser.add_argument(
        "--category", "-c", nargs="*",
        choices=["status", "research", "ambiguous", "action", "safety"],
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto re-run without pausing for fixes (useful for CI)",
    )
    args = parser.parse_args()
    asyncio.run(improvement_loop(
        max_rounds=args.rounds,
        categories=args.category,
        auto=args.auto,
    ))


if __name__ == "__main__":
    main()
