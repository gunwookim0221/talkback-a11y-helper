from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "qa_frontend" / "frontend" / "src"


def test_advanced_is_closed_by_default_and_follows_validator_sections() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    advanced = (FRONTEND / "components" / "AdvancedSection.tsx").read_text(encoding="utf-8")

    assert app.index("<CurrentRunPanel") < app.index("<ReviewRequiredPanel")
    assert app.index("<ReviewRequiredPanel") < app.index("<RecentRunsPanel")
    assert app.index("<RecentRunsPanel") < app.index("<AdvancedSection")
    assert '<details className="panel advancedSection"' in advanced
    assert "open=" not in advanced
    assert 'aria-labelledby="advanced-title"' in advanced
    assert "고급 기능" in advanced


def test_engineering_panels_are_only_rendered_inside_advanced_boundary() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    advanced_start = app.index("<AdvancedSection>")
    advanced_end = app.index("</AdvancedSection>")
    before = app[:advanced_start]
    inside = app[advanced_start:advanced_end]

    for component in ("PluginDiscoveryPanel", "ComparePanel", "CorpusReadinessPanel", "RuntimeDashboardPanel", "OutputsPanel"):
        rendered = f"<{component}"
        assert rendered in inside
        assert rendered not in before

    assert "AutomationDiagnosticsPanel" in inside
    assert "Log Tail" in inside
    assert "Run diagnostics" in inside
    assert "Runtime Preflight details" in inside


def test_advanced_groups_keep_critical_warnings_on_main() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    advanced_start = app.index("<AdvancedSection>")
    main = app[:advanced_start]

    assert "actionBannerWarn" in main
    assert "TalkBack disabled" in main
    assert "language change required" in main
    assert "Setup required: TalkBack A11y Helper" in main


def test_automation_diagnostics_have_a_separate_advanced_projection() -> None:
    panel = (FRONTEND / "components" / "AutomationDiagnosticsPanel.tsx").read_text(encoding="utf-8")
    review = (FRONTEND / "components" / "ReviewRequiredPanel.tsx").read_text(encoding="utf-8")

    assert "automation_diagnostics" in panel
    assert "AUTOMATION_DIAGNOSTIC" in panel
    assert "QA Review" in panel
    assert "검토 필요" not in panel
    assert "automationDiagnosticsDetails" not in review


def test_advanced_css_supports_disclosure_focus_and_narrow_layout() -> None:
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")

    assert ".advancedSection" in styles
    assert ".advancedSection[open]" in styles
    assert ".advancedContent" in styles
    assert ".advancedGroup" in styles
    assert "@media (max-width: 600px)" in styles
    assert ".advancedPanelHeader" in styles
