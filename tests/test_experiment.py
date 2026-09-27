"""Feature 007 — assignment stability and always-valid inference."""
from __future__ import annotations

import pytest

from f2g.experiment.analysis import (
    Verdict,
    arm_stats,
    compare,
    false_positive_simulation,
    sample_size,
    sequential_z,
    stopping_verdict,
)
from f2g.experiment.assign import DEFAULT_EXPERIMENT, Arm, Experiment, assign, bucket


# -- assignment ------------------------------------------------------------

def test_assignment_is_stable():
    """SC-001: an assignment that drifts silently invalidates the experiment."""
    for uid in [f"u{i:07d}" for i in range(200)]:
        variants = {assign(uid) for _ in range(20)}
        assert len(variants) == 1


def test_arm_proportions_match_configuration():
    """SC-002: within one percentage point at 10,000 users."""
    from collections import Counter

    users = [f"u{i:07d}" for i in range(10_000)]
    counts = Counter(assign(u) for u in users)
    for arm in DEFAULT_EXPERIMENT.arms:
        observed = counts[arm.name] / len(users)
        assert abs(observed - arm.share) < 0.01, f"{arm.name}: {observed:.4f} vs {arm.share}"


def test_different_experiments_partition_independently():
    """Without an experiment salt, a user unlucky once is unlucky always."""
    a = Experiment("exp-a", (Arm("t", 0.5), Arm("c", 0.5)))
    b = Experiment("exp-b", (Arm("t", 0.5), Arm("c", 0.5)))
    users = [f"u{i:07d}" for i in range(2000)]
    same = sum(assign(u, a) == assign(u, b) for u in users) / len(users)
    assert 0.44 < same < 0.56, f"assignment correlated across experiments: {same:.3f}"


def test_arm_shares_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        Experiment("bad", (Arm("a", 0.5), Arm("b", 0.2)))


def test_bucket_is_bounded():
    assert all(0 <= bucket(f"u{i}", "e") < 10_000 for i in range(500))


# -- sequential inference --------------------------------------------------

def test_sequential_critical_value_exceeds_fixed():
    """The price of being allowed to look whenever you like."""
    for n in (500, 5_000, 50_000):
        assert sequential_z(n) > 1.96


def test_sequential_interval_is_wider_than_fixed():
    t = arm_stats("t", 5000, 850)
    c = arm_stats("c", 5000, 800)
    cmp_ = compare(t, c)
    fixed_width = cmp_.fixed_ci[1] - cmp_.fixed_ci[0]
    seq_width = cmp_.sequential_ci[1] - cmp_.sequential_ci[0]
    assert seq_width > fixed_width


def test_null_experiment_repeated_looks(capsys):
    """SC-006, the headline statistical claim.

    Under no true effect, read 200 times: the naive fixed-horizon test declares
    a winner far past its nominal alpha, the sequential bound does not.
    """
    r = false_positive_simulation(n_looks=200, n_per_look=60, trials=120, seed=1)
    assert r["fixed_horizon_false_positive_rate"] > 0.20
    assert r["sequential_false_positive_rate"] <= 0.07


def test_sample_size_is_monotone_in_effect():
    small = sample_size(0.15, 0.05)["n_per_arm_fixed"]
    large = sample_size(0.15, 0.20)["n_per_arm_fixed"]
    assert small > large


def test_sequential_sample_size_carries_a_premium():
    s = sample_size(0.15, 0.10)
    assert s["n_per_arm_sequential"] > s["n_per_arm_fixed"]


# -- stopping rules --------------------------------------------------------

def _cmp(lift: float, n: int = 20_000, rate: float = 0.15):
    t = arm_stats("t", n, int(n * (rate + lift)))
    c = arm_stats("c", n, int(n * rate))
    return compare(t, c)


def test_harm_is_checked_before_success():
    """A conversion win must never mask a retention breach."""
    conversion = _cmp(0.03)                       # a clear win
    retention = _cmp(-0.20, n=8000, rate=0.70)    # a clear breach
    v = stopping_verdict(conversion, retention, guardrail_margin=0.03)
    assert v["verdict"] == Verdict.STOP_FOR_HARM


def test_ship_requires_both_conditions():
    conversion = _cmp(0.03)
    retention = _cmp(0.0, n=8000, rate=0.70)
    assert stopping_verdict(conversion, retention)["verdict"] == Verdict.SHIP


def test_undecided_continues():
    conversion = _cmp(0.0005, n=1500)
    retention = _cmp(0.0, n=800, rate=0.70)
    assert stopping_verdict(conversion, retention)["verdict"] == Verdict.CONTINUE


def test_futility_only_at_the_horizon():
    conversion = _cmp(0.0005, n=1500)
    retention = _cmp(0.0, n=800, rate=0.70)
    v = stopping_verdict(conversion, retention, horizon_reached=True)
    assert v["verdict"] == Verdict.STOP_FOR_FUTILITY


def test_every_verdict_explains_itself():
    conversion = _cmp(0.03)
    retention = _cmp(0.0, n=8000, rate=0.70)
    v = stopping_verdict(conversion, retention)
    assert v["rule"] and v["detail"]
