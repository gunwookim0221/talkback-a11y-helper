from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "qa_frontend" / "frontend" / "src"


def test_terminal_completion_refreshes_standalone_and_signals_batch_history() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    panel = (FRONTEND / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")

    terminal_callback = app[app.index("onRunFinished:"):app.index("  });", app.index("onRunFinished:"))]
    assert "setHistoryRefreshToken" in terminal_callback
    assert "api.recentRuns()" in terminal_callback
    assert "historyRefreshToken={historyRefreshToken}" in app
    assert "historyRefreshToken?: number" in panel


def test_batch_history_refreshes_immediately_on_token_and_keeps_periodic_fallback() -> None:
    panel = (FRONTEND / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")

    assert "api.recentBatches()" in panel
    assert "void refreshAndSchedule();" in panel
    assert "window.setTimeout(refreshAndSchedule, 5000)" in panel
    assert "[historyRefreshToken, loadBatches]" in panel


def test_batch_refresh_failure_is_non_fatal_and_does_not_change_execution_state() -> None:
    panel = (FRONTEND / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")

    load_start = panel.index("const loadBatches")
    effect_start = panel.index("useEffect(() =>", load_start)
    load_block = panel[load_start:effect_start]
    assert "console.warn('Recent batch history poll failed:'" in load_block
    assert "return null;" in load_block
    assert "setRecentBatches(res)" in panel
    assert "setStatus" not in load_block


def test_standalone_and_batch_sources_feed_one_unified_history_view() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    panel = (FRONTEND / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")
    presentation = (FRONTEND / "reviewPresentation.ts").read_text(encoding="utf-8")

    assert "recentRuns: RecentRun[]" in panel
    assert "const [recentBatches, setRecentBatches]" in panel
    assert "api.recentRuns()" in app
    assert "api.recentBatches()" in panel
    assert "normalizeUnifiedHistory(recentRuns, recentBatches)" in panel
    assert "unifiedHistory.map" in panel
    assert "source: 'standalone'" in presentation
    assert "source: 'batch'" in presentation
