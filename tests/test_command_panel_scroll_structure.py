"""v2.38.2 — CommandPanel scroll structure regression guards.

Locks in the v2.38.2 restructure: single outer scroll region for
everything below the task input, no inner scroll on the tool list.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent
PANEL = REPO_ROOT / "gui" / "src" / "components" / "CommandPanel.jsx"


def _src() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_outer_column_has_min_h_0():
    """The CommandPanel outer column must have min-h-0 so its flex-1
    scroll child can actually shrink below content height."""
    src = _src()
    assert 'data-component="CommandPanel"' in src, "marker div missing"
    # Outer must include both h-full and min-h-0
    assert re.search(
        r'<div\s+className="flex\s+flex-col\s+h-full\s+min-h-0"\s+data-component="CommandPanel"',
        src,
    ), "outer CommandPanel div must have 'flex flex-col h-full min-h-0' (v2.38.2)"


def test_single_outer_scroll_region_present():
    """Exactly one flex-1 overflow-y-auto min-h-0 wrapper below the
    task input. Previously the tool list had its own which fought for
    space with unscrollable siblings."""
    src = _src()
    # The wrapper div class — tolerate either attribute order
    patterns = [
        'flex-1 overflow-y-auto min-h-0',
        'overflow-y-auto flex-1 min-h-0',
        'flex-1 min-h-0 overflow-y-auto',
    ]
    matches = sum(src.count(p) for p in patterns)
    assert matches >= 1, (
        "CommandPanel must have a single 'flex-1 overflow-y-auto min-h-0' "
        "wrapper div containing the scrollable body (v2.38.2)"
    )


def test_tool_list_lost_its_own_scroll():
    """The tool list must no longer carry 'flex-1 overflow-y-auto' —
    that was the v2.38.1-and-earlier pattern that broke when Templates
    / Recent were open."""
    src = _src()
    # Extract a window around the tool list's visible.map() call
    m = re.search(r'\{visible\.map\(item\s*=>', src)
    assert m, "could not locate visible.map() in CommandPanel.jsx"
    # Look backwards a few hundred chars for any wrapper div class
    window = src[max(0, m.start() - 600): m.start()]
    # The old pattern included flex-1 overflow-y-auto. Neither should
    # appear within the ~600 chars immediately before visible.map().
    assert 'flex-1 overflow-y-auto' not in window, (
        "tool list wrapper must not have 'flex-1 overflow-y-auto' "
        "anymore — v2.38.2 moved scrolling to the outer wrapper"
    )


def test_task_input_block_still_has_shrink_0():
    """The task input / Run button block must remain pinned as shrink-0."""
    src = _src()
    # The task input header div is the one containing 'Agent Task'.
    # Use a non-greedy wildcard across the template-literal className so we
    # tolerate ${isTab ? ...} interpolations in between.
    assert re.search(
        r'shrink-0.*?Agent Task',
        src,
        flags=re.DOTALL,
    ), "task input block must retain 'shrink-0' (v2.38.2 keeps it pinned)"


def test_live_trace_nested_scroll_preserved():
    """The live-trace panel keeps its own maxHeight=100 + overflowY=auto
    because it's a bounded tail view. Don't accidentally remove it."""
    src = _src()
    assert 'maxHeight: 100' in src, "live-trace maxHeight must remain"
    # Find the live-trace block and confirm overflowY: 'auto' is on the
    # same element
    assert re.search(
        r"maxHeight:\s*100,\s*overflowY:\s*'auto'",
        src,
    ), "live-trace nested scroll (maxHeight:100 + overflowY:'auto') must be preserved"


def test_recent_and_templates_inside_scroll_region():
    """TaskTemplates and RecentTasks must render after the scroll
    wrapper opens (they can't sit above it or they'll steal space)."""
    src = _src()
    # Find the outer scroll wrapper and the two children
    wrapper_m = re.search(
        r'<div className="flex-1 overflow-y-auto min-h-0">',
        src,
    )
    tt_m = re.search(r'<TaskTemplates\s*/>', src)
    rt_m = re.search(r'<RecentTasks\s*/>', src)
    assert wrapper_m, "scroll wrapper not found"
    assert tt_m and rt_m, "TaskTemplates / RecentTasks not found"
    assert wrapper_m.start() < tt_m.start(), (
        "TaskTemplates must render inside (after) the scroll wrapper"
    )
    assert wrapper_m.start() < rt_m.start(), (
        "RecentTasks must render inside (after) the scroll wrapper"
    )
