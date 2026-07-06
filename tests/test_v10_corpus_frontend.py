from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "qa_frontend" / "frontend" / "src"


def test_frontend_renders_corpus_empty_state_and_family_columns():
    panel = (FRONTEND / "components" / "CorpusReadinessPanel.tsx").read_text(
        encoding="utf-8"
    )

    assert "No corpus data" in panel
    assert "V10 Corpus Readiness" in panel
    assert "candidate_for_v11_pilot" in panel
    for heading in (
        "Family",
        "Observations",
        "MATCH",
        "UNKNOWN",
        "MISMATCH",
        "FAILED",
        "Unique Labels",
        "Unique Devices",
        "Locale Count",
        "Last Seen",
        "Readiness",
        "V11 Candidate",
    ):
        assert heading in panel


def test_frontend_exposes_corpus_api_without_routing_controls():
    api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    panel = (FRONTEND / "components" / "CorpusReadinessPanel.tsx").read_text(
        encoding="utf-8"
    )

    assert "/api/v10/corpus/summary" in api
    assert "/api/v10/corpus/open/" in api
    assert "Controlled Routing remains disabled" in panel
    assert "Enable Controlled Routing" not in panel
