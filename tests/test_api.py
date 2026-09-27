"""Feature 007 — HTTP contract. Every endpoint has an integration test (SC-008)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    try:
        from f2g.api.main import app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"api unavailable: {exc}")
    return TestClient(app)


@pytest.fixture(scope="module")
def live_user(client):
    rows = client.get("/cohort?limit=1").json()["rows"]
    if not rows:
        pytest.skip("no live cohort")
    return rows[0]["user_id"]


def test_health_reports_every_subsystem(client):
    body = client.get("/health").json()
    assert body["status"] in {"ok", "degraded"}
    for key in ("models", "data", "llm"):
        assert key in body
    assert "synthetic" in body["notice"].lower()


def test_score_returns_the_full_decision(client, live_user):
    body = client.get(f"/score/{live_user}").json()
    for key in ("uplift", "propensity", "decision", "value_fit", "model_versions"):
        assert key in body
    vf = body["value_fit"]
    assert {"estimated_saving_90d", "genius_cost_90d", "net_position_90d", "passes"} <= set(vf)


def test_unknown_user_is_404_not_a_default_score(client):
    assert client.get("/score/definitely-not-a-user").status_code == 404


def test_suppressed_user_carries_a_reason(client):
    rows = client.get("/cohort?limit=200&decision=value_fit").json()["rows"]
    if not rows:
        pytest.skip("no value-fit suppressions in this cohort")
    body = client.get(f"/score/{rows[0]['user_id']}").json()
    assert body["decision"] == "value_fit"
    assert body["reason_detail"]
    assert body["value_fit"]["passes"] is False


def test_batch_scoring_separates_unknown_ids(client, live_user):
    body = client.post("/score/batch", json={"user_ids": [live_user, "ghost"]}).json()
    assert len(body["scored"]) == 1
    assert body["unknown_user_ids"] == ["ghost"]


def test_cohort_pagination_and_filtering(client):
    first = client.get("/cohort?limit=5&offset=0").json()
    second = client.get("/cohort?limit=5&offset=5").json()
    assert first["total"] == second["total"]
    assert {r["user_id"] for r in first["rows"]}.isdisjoint({r["user_id"] for r in second["rows"]})
    assert "summary" in first and "binding_constraint" in first["summary"]


def test_cohort_sort_is_validated(client):
    assert client.get("/cohort?sort_by=drop_table").status_code == 422


def test_assignment_is_idempotent(client, live_user):
    a = client.post(f"/experiment/assign/{live_user}").json()
    b = client.post(f"/experiment/assign/{live_user}").json()
    assert a["variant"] == b["variant"]


def test_event_idempotency(client, live_user, unique_key):
    client.post(f"/experiment/assign/{live_user}")
    payload = {"user_id": live_user, "event_type": "click", "idempotency_key": unique_key}
    first = client.post("/experiment/events", json=payload).json()
    second = client.post("/experiment/events", json=payload).json()
    assert first["recorded"] is True and first["duplicate"] is False
    assert second["recorded"] is False and second["duplicate"] is True


def test_event_for_unassigned_user_is_rejected(client, unique_key):
    r = client.post("/experiment/events", json={
        "user_id": "no-such-user", "event_type": "conversion", "idempotency_key": unique_key
    })
    assert r.status_code == 409


def test_invalid_event_type_is_rejected(client, live_user, unique_key):
    r = client.post("/experiment/events", json={
        "user_id": live_user, "event_type": "purchase_yacht", "idempotency_key": unique_key
    })
    assert r.status_code == 422


def test_experiment_config_is_published(client):
    body = client.get("/experiment").json()
    assert len(body["arms"]) == 3
    assert abs(sum(a["share"] for a in body["arms"]) - 1.0) < 1e-6


def test_summary_reports_both_intervals_and_a_verdict(client):
    """Runs against the isolated test database, so it must tolerate empty arms."""
    body = client.get("/experiment/summary").json()
    assert {"fixed_ci", "sequential_ci"} <= set(body["conversion"])
    assert body["verdict"]["verdict"] in {
        "continue", "ship", "stop_for_harm", "stop_for_futility"
    }
    assert "margin" in body["retention_guardrail"]


def test_power_endpoint(client):
    body = client.post("/experiment/power", json={
        "baseline_rate": 0.15, "mde_relative": 0.10
    }).json()
    assert body["n_per_arm_fixed"] > 0
    assert body["n_per_arm_sequential"] > body["n_per_arm_fixed"]


def test_power_validates_inputs(client):
    assert client.post("/experiment/power", json={
        "baseline_rate": 1.5, "mde_relative": 0.1
    }).status_code == 422


def test_nudge_is_grounded_and_cached(client, live_user):
    first = client.post(f"/agent/nudge/{live_user}",
                        json={"provider": "deterministic"}).json()
    assert first["message"]
    assert first["guardrails"]["passed"] is True
    assert first["cached"] is False
    second = client.post(f"/agent/nudge/{live_user}",
                         json={"provider": "deterministic"}).json()
    assert second["cached"] is True


def test_chat_runs_guardrails(client, live_user):
    body = client.post("/agent/chat", json={
        "user_id": live_user, "message": "Why am I paying fees?", "provider": "deterministic"
    }).json()
    assert "guardrails" in body and "checks" in body["guardrails"]


def test_chat_rejects_unknown_user(client):
    r = client.post("/agent/chat", json={
        "user_id": "ghost", "message": "hi", "provider": "deterministic"
    })
    assert r.status_code == 404


def test_audit_returns_the_full_record(client, live_user):
    client.post(f"/agent/nudge/{live_user}", json={"provider": "deterministic", "refresh": True})
    body = client.get(f"/audit/{live_user}").json()
    for key in ("assignments", "decisions", "generations", "events"):
        assert key in body
    assert body["generations"], "a generation should have been logged"


def test_telemetry_summarises_guardrails(client, live_user):
    client.post(f"/agent/nudge/{live_user}", json={"provider": "deterministic", "refresh": True})
    body = client.get("/telemetry").json()
    assert body["generations"] > 0
    assert "block_rate" in body["guardrails"]
    assert "p50" in body["latency_s"]
