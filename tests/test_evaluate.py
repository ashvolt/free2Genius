"""Feature 002 — evaluation metrics. Metrics are tested against cases whose
answer is known analytically, so a bug in the metric cannot be mistaken for a
bug in the model."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f2g.ml import evaluate


@pytest.fixture
def randomised_trial():
    rng = np.random.default_rng(3)
    n = 20_000
    tau = rng.normal(0.03, 0.04, n)
    p0 = rng.uniform(0.05, 0.30, n)
    t = rng.integers(0, 2, n)
    y = (rng.random(n) < np.clip(p0 + tau * t, 0, 1)).astype(int)
    return y, t, tau


def test_qini_orders_oracle_above_random(randomised_trial):
    y, t, tau = randomised_trial
    oracle = evaluate.qini_curve(y, t, tau).coefficient
    rng = np.random.default_rng(0)
    random = evaluate.qini_curve(y, t, rng.random(len(y))).coefficient
    assert oracle > 0.3
    assert random < 0.1
    assert oracle > random


def test_qini_of_inverted_score_is_negative(randomised_trial):
    """A ranking that is deliberately backwards must score below random."""
    y, t, tau = randomised_trial
    assert evaluate.qini_curve(y, t, -tau).coefficient < 0


def test_decile_table_is_monotone_for_oracle(randomised_trial):
    y, t, tau = randomised_trial
    table = evaluate.uplift_decile_table(y, t, tau)
    assert len(table) == 10
    assert table.iloc[0]["realised_uplift"] > table.iloc[-1]["realised_uplift"]
    assert table["n"].sum() == len(y)


def test_tau_recovery_is_perfect_against_itself(randomised_trial):
    _, _, tau = randomised_trial
    r = evaluate.tau_recovery(tau, tau)
    assert r["spearman"] == pytest.approx(1.0)
    assert r["rmse"] == pytest.approx(0.0)
    assert r["sign_agreement"] == pytest.approx(1.0)


def test_calibration_error_zero_for_perfect_predictions():
    rng = np.random.default_rng(5)
    p = rng.uniform(0.05, 0.95, 40_000)
    y = (rng.random(len(p)) < p).astype(int)
    assert evaluate.calibration_error(y, p) < 0.02


def test_calibration_error_detects_bias():
    rng = np.random.default_rng(5)
    p = rng.uniform(0.05, 0.45, 40_000)
    y = (rng.random(len(p)) < p).astype(int)
    assert evaluate.calibration_error(y, np.clip(p * 2, 0, 1)) > 0.1


def test_ratio_is_suppressed_when_denominator_near_zero():
    """A baseline with ~zero uplift must not produce a -2577% headline.

    This exact artifact appeared during development; the guard exists because of
    it, so the guard is pinned by a test.
    """
    rng = np.random.default_rng(11)
    n = 8000
    t = rng.integers(0, 2, n)
    y = (rng.random(n) < 0.2).astype(int)  # no real effect anywhere
    out = evaluate.policy_comparison(y, t, {"propensity": rng.random(n), "x": rng.random(n)}, 0.2)
    row = out[out.ranking == "x"].iloc[0]
    assert "vs_propensity_pp" in out.columns
    if abs(out[out.ranking == "propensity"].iloc[0]["incremental_per_contact"]) < evaluate.MIN_RATIO_DENOMINATOR:
        assert np.isnan(row["vs_propensity_pct"])


def test_budget_sweep_shape(randomised_trial):
    y, t, tau = randomised_trial
    sweep = evaluate.budget_sweep(y, t, {"oracle": tau}, budgets=(0.1, 0.2, 0.5))
    assert list(sweep["budget"]) == [0.1, 0.2, 0.5]
    assert "oracle_pp" in sweep.columns and "random_pp" in sweep.columns
    # Oracle advantage must shrink as reach grows — the property the operating
    # budget was chosen from.
    assert sweep.iloc[0]["oracle_pp"] > sweep.iloc[-1]["oracle_pp"]


def test_slice_metrics_flags_low_confidence():
    df = pd.DataFrame({"band": ["a"] * 500 + ["b"] * 20, "converted": [0, 1] * 260})
    vals = np.linspace(0, 1, len(df))
    out = evaluate.slice_metrics(
        df, vals, "band", lambda g, v: {"mean": float(v.mean())}, min_count=100
    )
    assert bool(out[out.band == "b"].iloc[0]["low_confidence"]) is True
    assert bool(out[out.band == "a"].iloc[0]["low_confidence"]) is False
