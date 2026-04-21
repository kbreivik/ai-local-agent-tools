"""v2.38.1 — structural guards for Operation ID column + Analysis deep-link wiring."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


# ─── OpsView ID column + Identifiers block ────────────────────────────────────

def test_ops_view_has_id_column_header():
    src = _read("gui/src/components/LogTable.jsx")
    # Header array now includes ID between Started and Label
    assert "['Started','ID','Label','Status','Duration','Model','Calls','Feedback']" in src, (
        "OpsView header must include 'ID' column between 'Started' and 'Label' (v2.38.1)"
    )


def test_ops_view_has_copy_id_helper():
    src = _read("gui/src/components/LogTable.jsx")
    assert "const copyId = useCallback" in src, (
        "OpsView must define copyId useCallback for click-to-copy (v2.38.1)"
    )
    assert "navigator.clipboard.writeText" in src, (
        "copyId must use navigator.clipboard (v2.38.1)"
    )


def test_ops_view_has_open_in_analysis_helper():
    src = _read("gui/src/components/LogTable.jsx")
    assert "openInAnalysis" in src, (
        "OpsView must define openInAnalysis useCallback (v2.38.1)"
    )
    assert "deathstar_analysis_deeplink" in src, (
        "openInAnalysis must write to sessionStorage under deathstar_analysis_deeplink (v2.38.1)"
    )
    assert "operation_full_context" in src, (
        "openInAnalysis must use the operation_full_context template (v2.38.1)"
    )
    assert "navigate-to-tab" in src, (
        "openInAnalysis must dispatch 'navigate-to-tab' event (v2.38.1)"
    )


def test_ops_view_detail_has_identifiers_block():
    src = _read("gui/src/components/LogTable.jsx")
    assert "Identifiers" in src, (
        "OpsView expanded detail must include 'Identifiers' block (v2.38.1)"
    )
    assert "Deep-dive in Analysis" in src, (
        "OpsView expanded detail must include 'Deep-dive in Analysis' button (v2.38.1)"
    )


def test_ops_view_detail_colspan_matches_new_column_count():
    src = _read("gui/src/components/LogTable.jsx")
    # 8 columns now, so detail row colSpan must be 8
    assert "colSpan={8}" in src, (
        "OpsView detail <td> must use colSpan={8} after ID column was added (v2.38.1)"
    )
    # And must NOT still use the old colSpan={7}
    assert "colSpan={7}" not in src, (
        "OpsView detail still contains legacy colSpan={7} — update to colSpan={8} (v2.38.1)"
    )


# ─── Scoped autoscroll in SessionOutputView ───────────────────────────────────

def test_session_output_uses_scoped_scroll():
    src = _read("gui/src/components/LogTable.jsx")
    assert "linesContainerRef" in src, (
        "SessionOutputView must use linesContainerRef for scoped autoscroll (v2.38.1)"
    )
    # The new scoped write
    assert "el.scrollTop = el.scrollHeight" in src, (
        "SessionOutputView must set scrollTop=scrollHeight directly — no scrollIntoView (v2.38.1)"
    )


def test_session_output_removes_scroll_into_view():
    src = _read("gui/src/components/LogTable.jsx")
    # scrollIntoView was the root cause — must be gone from this file
    assert "scrollIntoView" not in src.split("export function OpsView")[0], (
        "scrollIntoView must not appear in SessionOutputView or earlier sections of LogTable.jsx (v2.38.1)"
    )


# ─── App.jsx consumer ──────────────────────────────────────────────────────────

def test_app_listens_for_navigate_to_tab():
    src = _read("gui/src/App.jsx")
    assert "navigate-to-tab" in src, (
        "App.jsx must register a listener for 'navigate-to-tab' (v2.38.1)"
    )


# ─── AnalysisView consumer ─────────────────────────────────────────────────────

def test_analysis_view_imports_usecallback():
    src = _read("gui/src/components/AnalysisView.jsx")
    assert "useCallback" in src, (
        "AnalysisView must import useCallback (needed by v2.38.1 applyDeepLink)"
    )


def test_analysis_view_consumes_deeplink():
    src = _read("gui/src/components/AnalysisView.jsx")
    assert "deathstar_analysis_deeplink" in src, (
        "AnalysisView must read sessionStorage['deathstar_analysis_deeplink'] (v2.38.1)"
    )
    assert "sessionStorage.removeItem" in src, (
        "AnalysisView must clear the deep-link after consuming it (v2.38.1)"
    )
    assert "applyDeepLink" in src, (
        "AnalysisView must define applyDeepLink callback (v2.38.1)"
    )
    # Also listens for late-arriving events
    assert "navigate-to-tab" in src, (
        "AnalysisView must listen for 'navigate-to-tab' to handle late deep-links (v2.38.1)"
    )
