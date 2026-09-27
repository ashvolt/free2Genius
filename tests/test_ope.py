"""Feature 003 — offline policy evaluation.

Estimators are checked against a simulation whose true policy value is known,
which is the one thing synthetic data buys that real data cannot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f2g.ml import ope


@pytest.fixture(scope="module")
def trial():
    rng = np.random.default_rng(11)
    n = 25_000
    p0 = rng.uniform(0.05, 0.30, n)
    tau = rng.normal(0.03, 0.04, n)
    t = rng.integers(0, 2, n)
    y = (rng.random(n) < np.clip(p0 + tau * t, 0, 1)).astype(int)
    frame = pd.DataFrame({"converted": y, "treated": t, "p0": p0, "true_tau": tau})
    return frame, p0, p0 + tau, tau


def test_dr_interval_covers_the_oracle(trial):
    """SC-004: the estimator is validated, not just the policy."""
    frame, mu0, mu1, tau = trial
    pi = (tau > 0).astype(int)
    table = ope.evaluate_policy(frame, pi, mu0, mu1)
    assert ope.oracle_within_interval(table, "DR") is True


def test_estimators_rank_policies_correctly(trial):
    frame, mu0, mu1, tau = trial
    values = {}
    for name, pi in {
        "good": (tau > 0).astype(int),
        "all": np.ones(len(frame), int),
        "none": np.zeros(len(frame), int),
    }.items():
        t = ope.evaluate_policy(frame, pi, mu0, mu1)
        values[name] = float(t[t.estimator == "DR"].iloc[0]["value"])
    assert values["good"] > values["all"] > values["none"]


def test_clipped_fraction_is_reported(trial):
    frame, mu0, mu1, tau = trial
    pi = (tau > 0).astype(int)
    r = ope.ips(frame.converted, frame.treated, pi, 0.5, clip=1.5)
    assert r.clipped_fraction > 0, "clipping must be visible when it happens"


def test_snips_is_less_variable_than_ips(trial):
    frame, mu0, mu1, tau = trial
    pi = (tau > 0).astype(int)
    i = ope.ips(frame.converted, frame.treated, pi)
    s = ope.snips(frame.converted, frame.treated, pi)
    assert (s.ci_high - s.ci_low) <= (i.ci_high - i.ci_low) * 1.05


def test_contact_nobody_recovers_the_control_rate(trial):
    frame, mu0, mu1, _ = trial
    pi = np.zeros(len(frame), int)
    table = ope.evaluate_policy(frame, pi, mu0, mu1)
    dr = float(table[table.estimator == "DR"].iloc[0]["value"])
    control_rate = float(frame[frame.treated == 0].converted.mean())
    assert abs(dr - control_rate) < 0.01


def test_oracle_absent_without_ground_truth(trial):
    frame, mu0, mu1, tau = trial
    bare = frame.drop(columns=["p0", "true_tau"])
    table = ope.evaluate_policy(bare, (tau > 0).astype(int), mu0, mu1)
    assert "oracle" not in set(table.estimator)
    assert ope.oracle_within_interval(table) is None
