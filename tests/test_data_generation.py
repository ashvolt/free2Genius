"""Feature 001 — tasks T028-T030, T035. Success criteria SC-001, SC-003, SC-004."""
from __future__ import annotations

import numpy as np
import pytest

from f2g.data.generate import build, generate_cohort
from f2g.data.schema import FEATURES, LABEL_COLUMNS, ORACLE_COLUMNS


def test_determinism_same_seed():
    """SC-004: two runs at the same seed produce identical output."""
    a = generate_cohort(2000, seed=99, cohort="pilot", treatment_share=0.5, id_prefix="x")
    b = generate_cohort(2000, seed=99, cohort="pilot", treatment_share=0.5, id_prefix="x")
    assert a.equals(b)


def test_different_seeds_differ():
    a = generate_cohort(2000, seed=1, cohort="pilot", treatment_share=0.5, id_prefix="x")
    b = generate_cohort(2000, seed=2, cohort="pilot", treatment_share=0.5, id_prefix="x")
    assert not a["converted"].equals(b["converted"])


def test_observed_ate_matches_true_tau(small_cohort):
    """SC-001: the simulation is internally consistent.

    If the observed treated-minus-control difference did not track the mean of
    the hidden tau, every uplift metric computed on this data would be measuring
    something other than what it claims to.
    """
    treated = small_cohort[small_cohort.treated == 1]
    control = small_cohort[small_cohort.treated == 0]
    observed_ate = treated.converted.mean() - control.converted.mean()
    true_ate = small_cohort.true_tau.mean()

    se = np.sqrt(
        treated.converted.var(ddof=1) / len(treated)
        + control.converted.var(ddof=1) / len(control)
    )
    assert abs(observed_ate - true_ate) < 2 * se, (
        f"observed ATE {observed_ate:.4f} vs true {true_ate:.4f}, 2SE={2 * se:.4f}"
    )


def test_segment_effect_separation(small_cohort):
    """SC-003: a clearly positive segment and a clearly negative one both exist.

    Without a negative segment there is nothing for do-no-harm targeting to
    avoid, and the whole argument for uplift over propensity is untestable.
    """
    by_segment = small_cohort.groupby("segment").true_tau.mean()
    assert by_segment.max() >= 0.04, f"no strongly positive segment: {by_segment.to_dict()}"
    assert by_segment.min() <= -0.01, f"no negative segment: {by_segment.to_dict()}"
    assert by_segment["sleeping_dog"] < 0
    assert by_segment["persuadable"] > by_segment["sure_thing"]


def test_tau_keeps_probabilities_valid(small_cohort):
    p1 = small_cohort.p0 + small_cohort.true_tau
    assert (p1 > 0).all() and (p1 < 1).all()


def test_retention_only_for_converters(small_cohort):
    non_converters = small_cohort[small_cohort.converted == 0]
    assert (non_converters.retained_30d == -1).all()
    converters = small_cohort[small_cohort.converted == 1]
    assert converters.retained_30d.isin([0, 1]).all()


def test_retention_tracks_value_fit(small_cohort):
    """SC-006: the guardrail must be informative, not decorative."""
    conv = small_cohort[small_cohort.converted == 1].copy()
    conv["vf_quartile"] = conv.value_fit.rank(pct=True).mul(4).clip(upper=3.999).astype(int)
    rates = conv.groupby("vf_quartile").retained_30d.mean()
    assert rates.max() - rates.min() >= 0.10, f"retention barely varies with value fit: {rates.to_dict()}"


def test_live_cohort_uses_unobserved_sentinel():
    """FR-008: a sentinel that cannot be silently averaged as a real value."""
    _, live = build(n_users=2000, seed=7, n_live=800)
    for col in LABEL_COLUMNS:
        assert (live[col] == -1).all(), f"{col} should be the unobserved sentinel"
    assert live.cohort.eq("live").all()


def test_live_and_pilot_share_feature_columns():
    pilot, live = build(n_users=2000, seed=7, n_live=800)
    for col in FEATURES:
        assert col in pilot.columns and col in live.columns


@pytest.mark.parametrize("col", ORACLE_COLUMNS)
def test_oracle_columns_present_for_evaluation(col, small_cohort):
    """Oracle columns must exist — they are how estimators get validated —
    but they must never be features. The exclusion is asserted separately."""
    assert col in small_cohort.columns
