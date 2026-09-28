"""Feature 009 — governance artifacts stay true.

The point of these tests is that a stale governance document becomes a failing
build rather than something discovered during a review.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from f2g.governance import model_card

DOCS = Path(__file__).resolve().parent.parent / "docs" / "governance"


def _artifacts_present() -> bool:
    from f2g import config

    return (config.ARTIFACT_DIR / "reports" / "model_evaluation.json").exists() and (
        config.ARTIFACT_DIR / "reports" / "policy_report.json"
    ).exists()


def test_model_card_matches_current_evaluation_output():
    """FR-014 / SC-004: the committed card is what the metrics generate.

    If this fails, someone retrained without regenerating the card, and the card
    is now describing a model that no longer exists.
    """
    if not _artifacts_present():
        pytest.skip("run the pipeline first: make all")

    generated = model_card.generate()
    committed = model_card.CARD_PATH.read_text(encoding="utf-8")

    # The generated-on date is the only line expected to move.
    def strip_date(text: str) -> list[str]:
        return [ln for ln in text.splitlines() if not ln.startswith("**Generated**")]

    assert strip_date(generated) == strip_date(committed), (
        "MODEL_CARD.md is stale. Regenerate: python -m f2g.governance.model_card"
    )


def test_model_card_names_its_limitations():
    card = model_card.CARD_PATH.read_text(encoding="utf-8")
    for required in ("Known limitations", "Synthetic data", "Out-of-scope use",
                     "Failure modes"):
        assert required in card, f"model card is missing the '{required}' section"


def test_model_card_states_the_data_is_synthetic():
    assert "synthetic" in model_card.CARD_PATH.read_text(encoding="utf-8").lower()


def test_model_card_generation_fails_loudly_without_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(model_card, "REPORT_DIR", tmp_path)
    with pytest.raises(model_card.ArtifactsMissing, match="f2g.ml.train"):
        model_card.generate()


def test_every_risk_names_a_control_or_an_acceptance():
    """A mitigation with no control is accepted risk, and must say so."""
    register = (DOCS / "RISK_REGISTER.md").read_text(encoding="utf-8")
    sections = [s for s in register.split("\n## ") if s.startswith("R")]
    assert len(sections) >= 10, "risk register looks truncated"
    for section in sections:
        heading = section.splitlines()[0]
        has_control = "**Control**" in section
        has_acceptance = "Accepted" in section or "accepted" in section
        assert has_control or has_acceptance, f"risk '{heading}' names neither"


def test_risk_register_links_controls_to_code():
    register = (DOCS / "RISK_REGISTER.md").read_text(encoding="utf-8")
    for path in ("f2g/agent/guardrails.py", "f2g/ml/policy.py",
                 "f2g/experiment/analysis.py", "f2g/agent/scope.py"):
        assert path in register, f"no risk cites {path}"


def test_consent_note_covers_the_required_ground():
    note = (DOCS / "CONSENT_AND_DATA_USE.md").read_text(encoding="utf-8")
    for required in ("Purpose limitation", "Lawful basis", "Retention", "Rights",
                     "Where the data goes"):
        assert required in note


def test_governance_docs_state_synthetic_provenance():
    for name in ("MODEL_CARD.md", "RISK_REGISTER.md", "CONSENT_AND_DATA_USE.md"):
        text = (DOCS / name).read_text(encoding="utf-8").lower()
        assert "synthetic" in text, f"{name} does not state its data provenance"


def test_telemetry_summary_shape():
    from f2g.api.telemetry import summarise

    assert summarise([])["generations"] == 0

    rows = [
        {
            "telemetry": json.dumps({"provider": "deterministic", "latency_s": 0.01,
                                     "prompt_tokens": 10, "completion_tokens": 5,
                                     "repair_attempts": 0}),
            "guardrails": json.dumps({"blocked": False,
                                      "checks": {"numeric_grounding": True,
                                                 "coherence": False}}),
            "degraded": 0, "degraded_reason": "", "prompt_version": "concierge-v1.3.0",
        }
    ]
    out = summarise(rows)
    assert out["generations"] == 1
    assert out["guardrails"]["failures_by_check"]["coherence"] == 1
    assert "p50" in out["latency_s"]
    assert out["prompt_versions"]["concierge-v1.3.0"] == 1


def test_telemetry_flags_a_high_block_rate():
    from f2g.api.telemetry import summarise

    rows = [
        {
            "telemetry": json.dumps({"provider": "p", "latency_s": 1.0}),
            "guardrails": json.dumps({"blocked": True, "checks": {"numeric_grounding": False}}),
            "degraded": 1, "degraded_reason": "guardrail_block: x", "prompt_version": "v1",
        }
    ] * 4
    out = summarise(rows)
    assert out["guardrails"]["flagged"] is True
    assert out["degradation"]["rate"] == 1.0
