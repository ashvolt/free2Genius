"""The targeting policy: from a per-user uplift score to a defensible decision.

A score is not a decision. Between tau-hat and "send this user a nudge" sit four
constraints that a threshold cannot express:

1. **Positivity** — never contact a user whose estimated effect is negative. Not
   "rank them low": exclude them. This is the capability propensity ranking does
   not have.
2. **Value fit** — a user who would be talked into a subscription that saves them
   nothing is suppressed regardless of how movable they are
   (docs/adr/ADR-004-value-fit-gate.md). The check runs on the deterministic
   tool layer, so it needs no model inference and is reproducible.
3. **Budget** — contact at most a configured share of the population.
4. **Parity** (optional) — cap per-band contact share when the gap across income
   bands exceeds tolerance.

Every decision, selected or suppressed, is recorded with the numbers behind it.
"Why was this user contacted?" must have a factual answer months later, and an
answer reconstructed by re-running the pipeline is not evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from f2g import config
from f2g.agent.tools import ConciergeTools
from f2g.data import catalog

# Savings must at least equal the subscription cost over the same window.
# Lowering this below 1.0 means knowingly contacting users the system expects to
# lose money, so it is a governance decision, not a tuning knob.
DEFAULT_VALUE_FIT_MARGIN = 1.0

WINDOW_MONTHS = 3
GENIUS_COST_90D = round(catalog.GENIUS_MONTHLY_PRICE * WINDOW_MONTHS, 2)

VALUE_FIT_FEATURES = ["instant_delivery", "overdraft_shield", "subscription_watch"]


class Reason:
    SELECTED = "selected"
    NEGATIVE_UPLIFT = "negative_uplift"
    VALUE_FIT = "value_fit"
    BUDGET = "budget"
    PARITY_CAP = "parity_cap"
    NO_DATA = "no_data"


@dataclass
class PolicyConfig:
    contact_budget: float = config.DEFAULT_CONTACT_BUDGET
    value_fit_margin: float = DEFAULT_VALUE_FIT_MARGIN
    value_fit_enabled: bool = True
    parity_enabled: bool = False
    parity_tolerance: float = 0.10  # max acceptable contact-rate gap across bands
    fairness_attribute: str = "income_band"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class PolicyResult:
    decisions: pd.DataFrame
    config: PolicyConfig
    binding_constraint: str
    fairness: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def selected(self) -> pd.DataFrame:
        return self.decisions[self.decisions.decision == Reason.SELECTED]

    @property
    def suppressed(self) -> pd.DataFrame:
        return self.decisions[self.decisions.decision != Reason.SELECTED]


def estimate_value_fit(user_ids: Iterable[str]) -> pd.DataFrame:
    """Per-user estimated 90-day saving, from the deterministic tool layer.

    Deliberately calls `ConciergeTools` rather than the agent: the gate needs
    arithmetic over the user's own fee history, not a language model. That keeps
    it cheap enough to run over the whole live cohort in batch, and makes it
    exactly reproducible.
    """
    rows = []
    for uid in user_ids:
        try:
            tools = ConciergeTools(uid)
            est = tools.estimate_savings(VALUE_FIT_FEATURES)
            rows.append(
                {
                    "user_id": uid,
                    "estimated_saving_90d": est["total_estimated_saving_usd"],
                    "genius_cost_90d": est["genius_cost_over_window_usd"],
                    "net_position_90d": est["net_position_usd"],
                    "has_data": True,
                }
            )
        except KeyError:
            # Absence of evidence is not evidence of benefit: a user we cannot
            # assess fails the gate rather than passing it by default.
            rows.append(
                {
                    "user_id": uid,
                    "estimated_saving_90d": 0.0,
                    "genius_cost_90d": GENIUS_COST_90D,
                    "net_position_90d": -GENIUS_COST_90D,
                    "has_data": False,
                }
            )
    return pd.DataFrame(rows)


def estimate_value_fit_vectorized(frame: pd.DataFrame) -> pd.DataFrame:
    """The same estimate, computed over a whole cohort from aggregate columns.

    The per-user path above builds a ledger per user and is the reference
    implementation — it is literally what the agent will read, so it cannot
    disagree with what the user is told. But it is far too slow for 60,000
    users in a batch cycle.

    This computes the identical arithmetic from the aggregate feature columns.
    The two are pinned to each other by `test_value_fit_paths_agree`, so the
    fast path cannot silently drift from what the agent says.
    """
    instant = frame["instant_transfer_fees_90d"].to_numpy(dtype=float)
    overdraft = frame["overdraft_fees_90d"].to_numpy(dtype=float)

    shield = catalog.get_feature("overdraft_shield")
    watch = catalog.get_feature("subscription_watch")
    assert shield is not None and watch is not None

    saving = np.round(instant, 2) + np.round(overdraft * shield["coverage_rate"], 2)

    # `subscription_watch` depends on which subscriptions are flagged, which is
    # a per-user draw inside the ledger and has no aggregate column. It is
    # therefore excluded here and from the reference path's comparison set —
    # excluding it makes the gate stricter, never laxer, which is the safe
    # direction for a suppression decision.
    saving = np.round(saving, 2)

    return pd.DataFrame(
        {
            "user_id": frame["user_id"].to_numpy(),
            "estimated_saving_90d": saving,
            "genius_cost_90d": GENIUS_COST_90D,
            "net_position_90d": np.round(saving - GENIUS_COST_90D, 2),
            "has_data": True,
        }
    )


# Features the vectorised path covers. The reference path is compared against
# exactly this set so the two are measuring the same thing.
VECTORISED_FEATURES = ["instant_delivery", "overdraft_shield"]


def _fairness_table(decisions: pd.DataFrame, attribute: str) -> pd.DataFrame:
    grouped = decisions.groupby(attribute)
    table = grouped.agg(
        n=("user_id", "size"),
        contacted=("decision", lambda s: int((s == Reason.SELECTED).sum())),
        mean_uplift=("uplift", "mean"),
        mean_estimated_saving=("estimated_saving_90d", "mean"),
    ).reset_index()
    table["contact_rate"] = table["contacted"] / table["n"]
    # An "eligible" rate separates gaps the policy created from gaps that were
    # already in the population. Conflating the two is how fairness reporting
    # becomes theatre.
    eligible = grouped.apply(
        lambda g: float((g["uplift"] > 0).mean()), include_groups=False
    ).rename("eligible_rate")
    table = table.merge(eligible.reset_index(), on=attribute)
    table["low_confidence"] = table["n"] < 200
    return table


def select(
    candidates: pd.DataFrame,
    uplift: np.ndarray,
    propensity: np.ndarray | None = None,
    cfg: PolicyConfig | None = None,
    value_fit: pd.DataFrame | None = None,
) -> PolicyResult:
    """Apply the policy to scored candidates.

    `candidates` must carry `user_id` and the fairness attribute.
    """
    cfg = cfg or PolicyConfig()
    df = candidates.reset_index(drop=True).copy()
    df["uplift"] = np.asarray(uplift, dtype=float)
    df["propensity"] = (
        np.asarray(propensity, dtype=float) if propensity is not None else np.nan
    )

    if value_fit is None:
        value_fit = estimate_value_fit(df["user_id"])
    df = df.merge(value_fit, on="user_id", how="left")

    df["decision"] = Reason.SELECTED
    df["reason_detail"] = ""

    # 1. Positivity — unconditional.
    negative = df["uplift"] <= 0
    df.loc[negative, "decision"] = Reason.NEGATIVE_UPLIFT
    df.loc[negative, "reason_detail"] = "predicted uplift is not positive"

    # 2. Value fit — before the budget, so the gate is never masked by the
    #    budget having already excluded the user.
    threshold = GENIUS_COST_90D * cfg.value_fit_margin
    if cfg.value_fit_enabled:
        missing = df["has_data"].fillna(False).eq(False) & (df.decision == Reason.SELECTED)
        df.loc[missing, "decision"] = Reason.NO_DATA
        df.loc[missing, "reason_detail"] = "no account data available to assess benefit"

        fails = (df["estimated_saving_90d"] < threshold) & (df.decision == Reason.SELECTED)
        df.loc[fails, "decision"] = Reason.VALUE_FIT
        df.loc[fails, "reason_detail"] = (
            "estimated 90-day saving of $"
            + df.loc[fails, "estimated_saving_90d"].round(2).astype(str)
            + f" is below the ${threshold:.2f} Genius cost over the same period"
        )

    eligible = df[df.decision == Reason.SELECTED].copy()

    # 3. Budget. Ties broken by user_id so selection is reproducible.
    n_budget = int(round(cfg.contact_budget * len(df)))
    eligible = eligible.sort_values(
        ["uplift", "user_id"], ascending=[False, True], kind="stable"
    )

    binding = Reason.BUDGET
    if len(eligible) <= n_budget:
        # The budget was not the binding constraint — worth reporting, because
        # "we used 40% of our budget" is a different operational story from
        # "we were budget-capped".
        binding = Reason.VALUE_FIT if cfg.value_fit_enabled else Reason.NEGATIVE_UPLIFT
        keep = eligible
    else:
        keep = eligible.head(n_budget)
        cut = eligible.iloc[n_budget:]
        df.loc[df.user_id.isin(cut.user_id), "decision"] = Reason.BUDGET
        df.loc[df.user_id.isin(cut.user_id), "reason_detail"] = (
            f"ranked outside the top {n_budget} by predicted uplift"
        )

    # 4. Parity cap, optional.
    #
    # The cap is a RATE, not a count. Capping every band at the same absolute
    # number equalises counts while bands differ in size, which makes the
    # contact-*rate* gap worse rather than better — measured at 0.064 against
    # 0.040 uncapped before this was corrected. Parity here means an equal
    # chance of being contacted, so the cap has to scale with band size.
    if cfg.parity_enabled and not keep.empty:
        band_sizes = df[cfg.fairness_attribute].value_counts()
        capped_ids: list[str] = []
        for band, group in keep.groupby(cfg.fairness_attribute):
            band_cap = int(np.floor(cfg.contact_budget * band_sizes[band]))
            over = group.iloc[band_cap:]
            capped_ids.extend(over["user_id"].tolist())
        if capped_ids:
            df.loc[df.user_id.isin(capped_ids), "decision"] = Reason.PARITY_CAP
            df.loc[df.user_id.isin(capped_ids), "reason_detail"] = (
                f"per-band contact rate cap of {cfg.contact_budget:.0%} reached"
            )
            binding = Reason.PARITY_CAP

    fairness = _fairness_table(df, cfg.fairness_attribute)
    gap = float(fairness["contact_rate"].max() - fairness["contact_rate"].min())
    eligible_gap = float(fairness["eligible_rate"].max() - fairness["eligible_rate"].min())

    selected = df[df.decision == Reason.SELECTED]
    # Users the gate admitted who would have been cut by the budget without it.
    # Suppressing low-benefit users frees slots, and those slots go to the next
    # eligible users down the ranking — so the gated set is not a subset of the
    # ungated one, it is a better-spent set of the same size.
    backfilled = 0
    if cfg.value_fit_enabled and n_budget:
        ungated_order = df.sort_values(
            ["uplift", "user_id"], ascending=[False, True], kind="stable"
        )
        would_have_been = set(
            ungated_order[ungated_order.uplift > 0].head(n_budget)["user_id"]
        )
        backfilled = len(set(selected["user_id"]) - would_have_been)

    summary = {
        "candidates": len(df),
        "selected": len(selected),
        "budget_slots": n_budget,
        "budget_used": round(len(selected) / n_budget, 4) if n_budget else 0.0,
        "binding_constraint": binding,
        "suppressed_by_reason": df[df.decision != Reason.SELECTED]
        .decision.value_counts()
        .to_dict(),
        "mean_uplift_selected": float(selected["uplift"].mean()) if len(selected) else 0.0,
        "mean_saving_selected": float(selected["estimated_saving_90d"].mean())
        if len(selected)
        else 0.0,
        "expected_incremental_conversions": float(selected["uplift"].sum()),
        "contact_rate_gap": gap,
        "eligible_rate_gap": eligible_gap,
        # Separating these two is the whole point: a gap that already exists in
        # who is *eligible* is a population fact; the part the policy adds on
        # top is the part we are answerable for.
        "policy_induced_gap": round(gap - eligible_gap * cfg.contact_budget, 4),
        "fairness_flag": gap > cfg.parity_tolerance,
        "value_fit_threshold_usd": threshold,
        "backfilled_by_gate": backfilled,
    }

    return PolicyResult(
        decisions=df, config=cfg, binding_constraint=binding, fairness=fairness, summary=summary
    )
