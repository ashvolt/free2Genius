"""Feature 003 — the targeting policy and the value-fit gate."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f2g.agent.tools import ConciergeTools
from f2g.ml.policy import (
    GENIUS_COST_90D,
    VECTORISED_FEATURES,
    PolicyConfig,
    Reason,
    estimate_value_fit_vectorized,
    select,
)


@pytest.fixture(scope="module")
def live():
    from f2g import config

    path = config.DATA_DIR / "live_users.csv"
    if not path.exists():
        pytest.skip("run `python -m f2g.data.generate` first")
    return pd.read_csv(path).head(2500).reset_index(drop=True)


@pytest.fixture(scope="module")
def scored(live):
    rng = np.random.default_rng(0)
    # Uplift correlated with fee burden, so the gate and the ranking interact
    # the way they do in production rather than being independent noise.
    tau = 0.002 + 0.0006 * live["instant_transfer_fees_90d"] + rng.normal(0, 0.01, len(live))
    return live, tau.to_numpy(), rng.random(len(live))


def test_never_contacts_negative_uplift(scored):
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig())
    assert (res.selected["uplift"] > 0).all()


def test_budget_is_respected(scored):
    live, tau, p = scored
    cfg = PolicyConfig(contact_budget=0.10, value_fit_enabled=False)
    res = select(live, tau, p, cfg)
    assert len(res.selected) <= int(round(0.10 * len(live)))


def test_every_decision_has_a_reason(scored):
    """SC-002: 100% of decisions, selected and suppressed, are explained."""
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig())
    assert res.decisions["decision"].notna().all()
    suppressed = res.suppressed
    assert (suppressed["reason_detail"].str.len() > 0).all()


def test_value_fit_gate_suppresses_low_benefit_users(scored):
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig(value_fit_enabled=True))
    gated_out = res.decisions[res.decisions.decision == Reason.VALUE_FIT]
    assert len(gated_out) > 0
    assert (gated_out["estimated_saving_90d"] < GENIUS_COST_90D).all()


def test_gate_raises_mean_benefit_of_the_contacted(scored):
    """SC-003: mean value fit of selected is materially higher with the gate."""
    live, tau, p = scored
    on = select(live, tau, p, PolicyConfig(value_fit_enabled=True))
    off = select(live, tau, p, PolicyConfig(value_fit_enabled=False))
    assert on.summary["mean_saving_selected"] > off.summary["mean_saving_selected"] * 1.3


def test_gate_backfills_freed_budget_rather_than_shrinking(scored):
    """The gate is not a subset filter, and that is correct.

    The original spec (US2, scenario 3) asserted that the ungated selection is a
    strict superset of the gated one. It is not, and it should not be:
    suppressing a low-benefit user frees a budget slot, which goes to the next
    eligible user down the uplift ranking. The right invariants are that every
    selected user passes the gate, and that nobody the gate rejected is
    contacted.
    """
    live, tau, p = scored
    on = select(live, tau, p, PolicyConfig(value_fit_enabled=True))

    rejected = set(on.decisions[on.decisions.decision == Reason.VALUE_FIT].user_id)
    assert not (set(on.selected.user_id) & rejected)
    assert (on.selected["estimated_saving_90d"] >= GENIUS_COST_90D).all()


def test_high_uplift_zero_fee_user_is_suppressed(live):
    """The headline claim: movable but would not benefit, so not contacted."""
    quiet = live[(live.instant_transfer_fees_90d == 0) & (live.overdraft_fees_90d == 0)]
    if quiet.empty:
        pytest.skip("no zero-fee users in this slice")
    target = quiet.iloc[0]["user_id"]
    frame = live.copy()
    tau = np.full(len(frame), 0.001)
    tau[frame.index[frame.user_id == target][0]] = 0.99  # top of the ranking
    res = select(frame, tau, None, PolicyConfig())
    row = res.decisions[res.decisions.user_id == target].iloc[0]
    assert row["decision"] == Reason.VALUE_FIT
    assert "below" in row["reason_detail"]


def test_missing_data_fails_the_gate_rather_than_passing(scored):
    """Absence of evidence is not evidence of benefit."""
    live, tau, p = scored
    vf = estimate_value_fit_vectorized(live)
    vf.loc[vf.index[:20], "has_data"] = False
    res = select(live, tau, p, PolicyConfig(), value_fit=vf)
    affected = res.decisions[res.decisions.user_id.isin(vf.user_id[:20])]
    assert (affected["decision"] != Reason.SELECTED).all()


def test_selection_is_deterministic(scored):
    live, tau, p = scored
    a = select(live, tau, p, PolicyConfig())
    b = select(live, tau, p, PolicyConfig())
    assert list(a.selected.user_id) == list(b.selected.user_id)


def test_all_negative_uplift_returns_empty_not_least_bad(live):
    tau = np.full(len(live), -0.01)
    res = select(live, tau, None, PolicyConfig())
    assert len(res.selected) == 0


def test_zero_budget_is_valid(scored):
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig(contact_budget=0.0, value_fit_enabled=False))
    assert len(res.selected) == 0


def test_binding_constraint_is_reported(scored):
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig(contact_budget=0.99))
    assert res.binding_constraint in {Reason.VALUE_FIT, Reason.BUDGET,
                                      Reason.NEGATIVE_UPLIFT, Reason.PARITY_CAP}


def test_fairness_table_separates_eligibility_from_policy(scored):
    live, tau, p = scored
    res = select(live, tau, p, PolicyConfig())
    assert {"contact_rate", "eligible_rate", "low_confidence"} <= set(res.fairness.columns)
    assert "policy_induced_gap" in res.summary


def test_parity_cap_reduces_the_gap(scored):
    live, tau, p = scored
    plain = select(live, tau, p, PolicyConfig(value_fit_enabled=False))
    capped = select(live, tau, p, PolicyConfig(value_fit_enabled=False, parity_enabled=True))
    assert capped.summary["contact_rate_gap"] <= plain.summary["contact_rate_gap"] + 1e-9


def test_value_fit_paths_agree():
    """The fast batch path must not drift from what the agent will tell the user."""
    from f2g import config

    live = pd.read_csv(config.DATA_DIR / "live_users.csv").sample(60, random_state=3)
    fast = estimate_value_fit_vectorized(live).set_index("user_id")
    for uid in live.user_id:
        reference = ConciergeTools(uid).estimate_savings(VECTORISED_FEATURES)
        assert abs(
            reference["total_estimated_saving_usd"] - float(fast.loc[uid, "estimated_saving_90d"])
        ) < 0.011, uid
