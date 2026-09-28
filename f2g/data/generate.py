"""Synthetic Albert-like population with a known uplift data-generating process.

THIS DATA IS SYNTHETIC. No Albert data, customer data or production model was
used. The generator exists so the modelling, serving and experimentation code
can be exercised end to end, and so offline uplift metrics can be checked
against a *known* ground-truth treatment effect -- something real data never
provides.

Two cohorts, mirroring how a real programme is bootstrapped:

* A historical **pilot** cohort, randomly assigned 50/50 to receive a nudge or
  not. Randomisation is what makes the conditional average treatment effect
  identifiable, so the uplift models train on this.
* A **live** cohort of current free users with features but no outcome. That is
  what the scoring service and the console operate on.

Four latent archetypes drive the heterogeneity, which is the entire reason to
prefer uplift over plain propensity:

| segment      | baseline conversion | effect of nudging            |
|--------------|---------------------|------------------------------|
| persuadable  | low-ish             | large positive               |
| sure_thing   | high                | ~0 (they convert regardless) |
| lost_cause   | very low            | ~0 (nothing moves them)      |
| sleeping_dog | low                 | slightly negative            |

A propensity model ranks `sure_thing` users first and buys conversions that
were already coming. An uplift model ranks `persuadable` users first and
actively avoids `sleeping_dog` users.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from f2g import config
from f2g.data.schema import (
    ACQUISITION_CHANNELS,
    AGE_BANDS,
    INCOME_BANDS,
    PLATFORMS,
    UNOBSERVED,
)

SEGMENTS = ["persuadable", "sure_thing", "lost_cause", "sleeping_dog"]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _draw_segments(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.choice(SEGMENTS, size=n, p=[0.24, 0.16, 0.44, 0.16])


def _behaviour_frame(rng: np.random.Generator, segment: np.ndarray) -> pd.DataFrame:
    """Behavioural features drawn conditional on the latent segment.

    The segment is never exposed as a feature; it only shapes observable
    behaviour, so the learner has to recover the effect heterogeneity from
    signals a real product would actually log.
    """
    n = len(segment)
    is_pers = segment == "persuadable"
    is_sure = segment == "sure_thing"
    is_lost = segment == "lost_cause"
    is_dog = segment == "sleeping_dog"

    income = rng.choice(INCOME_BANDS, size=n, p=[0.22, 0.34, 0.26, 0.18])
    # Sleeping dogs skew lower-income and fee-stressed; persuadables skew
    # mid-income. Deliberate: it is what makes the fairness audit a real check
    # rather than a clean synthetic null.
    reshuffle = rng.random(n)
    income = np.where(
        is_dog & (reshuffle < 0.45),
        rng.choice(INCOME_BANDS, n, p=[0.55, 0.30, 0.10, 0.05]),
        income,
    )
    income = np.where(
        is_pers & (reshuffle < 0.35),
        rng.choice(INCOME_BANDS, n, p=[0.15, 0.40, 0.30, 0.15]),
        income,
    )

    tenure = np.clip(rng.gamma(2.0, 120.0, n), 14, 1800).round()

    dd_p = np.select([is_pers, is_sure, is_dog], [0.70, 0.78, 0.30], default=0.28)
    direct_deposit = (rng.random(n) < dd_p).astype(int)
    dd_months = np.where(direct_deposit == 1, np.clip(rng.poisson(5.0, n) + 1, 1, 36), 0)
    dd_amount = np.where(
        direct_deposit == 1,
        np.clip(rng.lognormal(7.35, 0.45, n), 300, 9000).round(2),
        0.0,
    )

    adv_lam = np.select([is_pers, is_sure, is_dog], [2.6, 1.6, 4.1], default=0.5)
    advances = rng.poisson(adv_lam, n)
    advance_amt = np.where(
        advances > 0, np.clip(rng.normal(96, 38, n), 25, 250).round(2), 0.0
    )
    repay_rate = np.where(
        advances > 0,
        np.clip(rng.beta(np.where(is_dog, 5.0, 12.0), 2.0, n), 0.2, 1.0).round(3),
        1.0,
    )

    # Fees the user pays today. Instant-transfer fees are charged per expedited
    # advance; overdraft fees come from their linked bank.
    instant_rate = np.where(is_pers, 0.62, np.where(is_dog, 0.55, 0.35))
    instant_count = rng.binomial(advances, instant_rate)
    instant_fees = (instant_count * 4.99).round(2)

    od_lam = np.select([is_pers, is_dog], [1.5, 2.2], default=0.35)
    overdraft_count = rng.poisson(od_lam, n)
    overdraft_fees = (overdraft_count * 34.0).round(2)

    budget_lam = np.select([is_pers, is_sure, is_lost], [6.0, 8.5, 0.5], default=2.0)
    budget_sessions = rng.poisson(budget_lam, n)
    categories = np.clip(rng.poisson(np.where(budget_sessions > 0, 4.0, 0.3), n), 0, 12)

    opens_lam = np.select([is_pers, is_sure, is_lost], [14.0, 20.0, 1.6], default=7.0)
    app_opens = rng.poisson(opens_lam, n)
    days_since_open = np.where(
        app_opens > 0,
        np.clip(rng.exponential(np.where(is_lost, 18.0, 3.0), n), 0, 89).round(),
        np.clip(rng.uniform(20, 89, n), 0, 89).round(),
    )

    auto_save = (
        rng.random(n) < np.where(is_sure, 0.45, np.where(is_pers, 0.28, 0.10))
    ).astype(int)
    savings_balance = np.where(
        auto_save == 1,
        np.clip(rng.lognormal(5.6, 1.0, n), 0, 12000).round(2),
        np.clip(rng.lognormal(3.4, 1.4, n), 0, 4000).round(2),
    )

    subs_count = np.clip(rng.poisson(np.where(is_lost, 2.2, 4.0), n), 0, 14)
    subs_spend = (subs_count * np.clip(rng.normal(14.5, 7.0, n), 3.5, 60.0)).round(2)

    low_balance_days = np.clip(
        rng.poisson(np.select([is_pers, is_dog], [7.0, 11.0], default=3.0), n), 0, 30
    )
    avg_balance = np.clip(
        rng.lognormal(6.1 - 0.05 * low_balance_days, 0.8), 5, 25000
    ).round(2)

    upsell_views = rng.poisson(np.where(is_sure, 5.5, np.where(is_lost, 0.4, 2.0)), n)
    support = rng.poisson(np.where(is_dog, 2.4, 0.5), n)

    return pd.DataFrame(
        {
            "tenure_days": tenure.astype(int),
            "income_band": income,
            "age_band": rng.choice(AGE_BANDS, size=n, p=[0.21, 0.36, 0.29, 0.14]),
            "platform": rng.choice(PLATFORMS, size=n, p=[0.56, 0.44]),
            "acquisition_channel": rng.choice(
                ACQUISITION_CHANNELS, size=n, p=[0.30, 0.34, 0.16, 0.20]
            ),
            "direct_deposit_active": direct_deposit,
            "dd_consecutive_months": dd_months.astype(int),
            "dd_amount_monthly": dd_amount,
            "advances_90d": advances.astype(int),
            "advance_amount_avg": advance_amt,
            "advance_repaid_on_time_rate": repay_rate,
            "instant_transfer_fees_90d": instant_fees,
            "overdraft_fees_90d": overdraft_fees,
            "budget_sessions_30d": budget_sessions.astype(int),
            "budget_categories_tracked": categories.astype(int),
            "app_opens_30d": app_opens.astype(int),
            "days_since_last_open": days_since_open.astype(int),
            "savings_auto_enabled": auto_save,
            "savings_balance": savings_balance,
            "recurring_subscriptions_count": subs_count.astype(int),
            "recurring_subscription_spend": subs_spend,
            "low_balance_days_30d": low_balance_days.astype(int),
            "avg_daily_balance": avg_balance,
            "push_enabled": (rng.random(n) < 0.62).astype(int),
            "prior_upsell_views_90d": upsell_views.astype(int),
            "support_contacts_90d": support.astype(int),
            # Not features: the ledger needs exact counts to reconcile to the cent.
            "_instant_transfer_count_90d": instant_count.astype(int),
            "_overdraft_count_90d": overdraft_count.astype(int),
        }
    )


def _baseline_and_effect(df: pd.DataFrame, segment: np.ndarray, rng: np.random.Generator):
    """Baseline conversion probability `p0` and true uplift `tau`.

    `tau` is the ground truth the uplift model tries to recover. Stored for
    evaluation only; never a model input.
    """
    n = len(df)
    z = (
        -3.05
        + 0.55 * df["direct_deposit_active"]
        + 0.030 * np.minimum(df["dd_consecutive_months"], 18)
        + 0.045 * np.minimum(df["budget_sessions_30d"], 12)
        + 0.021 * np.minimum(df["app_opens_30d"], 30)
        + 0.085 * np.minimum(df["prior_upsell_views_90d"], 8)
        - 0.030 * df["days_since_last_open"]
        + 0.0016 * np.minimum(df["overdraft_fees_90d"], 300)
        + 0.0090 * np.minimum(df["instant_transfer_fees_90d"], 80)
        + 0.30 * df["savings_auto_enabled"]
        - 0.045 * np.minimum(df["support_contacts_90d"], 6)
    )
    z += np.select(
        [segment == "sure_thing", segment == "lost_cause", segment == "sleeping_dog"],
        [1.45, -0.85, -0.25],
        default=0.0,
    )
    p0 = np.clip(_sigmoid(z + rng.normal(0, 0.25, n)), 0.002, 0.92)

    # Uplift is largest where the nudge can teach something the user does not
    # already know -- real fees being paid -- and where they are reachable
    # enough to act. The product of the two is what makes uplift learnable
    # without being trivial: neither factor alone predicts it.
    fee_pain = np.clip(
        (df["instant_transfer_fees_90d"] / 30.0) + (df["overdraft_fees_90d"] / 120.0),
        0,
        3.0,
    )
    reachable = _sigmoid(0.18 * df["app_opens_30d"] - 1.1) * np.where(
        df["push_enabled"] == 1, 1.0, 0.7
    )

    tau = np.select(
        [
            segment == "persuadable",
            segment == "sure_thing",
            segment == "lost_cause",
            segment == "sleeping_dog",
        ],
        [
            0.030 + 0.045 * fee_pain * reachable + 0.020 * df["direct_deposit_active"],
            0.004 + 0.004 * reachable,
            0.001 + 0.002 * reachable,
            -0.012 - 0.018 * np.clip(df["support_contacts_90d"] / 4.0, 0, 1.0),
        ],
        default=0.0,
    )
    tau = np.asarray(tau, dtype=float) + rng.normal(0, 0.004, n)
    # Keep the treated probability a valid probability.
    tau = np.clip(tau, -p0 * 0.9, 1.0 - p0 - 1e-6)
    return p0, tau


def _value_fit(df: pd.DataFrame) -> np.ndarray:
    """How much money Genius would actually save this user, scaled 0-1.

    Retention after conversion is driven by this. It is the mechanism behind
    the guardrail metric: converting users with poor value fit lifts the
    headline conversion rate and quietly destroys 30-day retention.
    """
    raw = (
        0.45 * np.clip(df["instant_transfer_fees_90d"] / 25.0, 0, 1)
        + 0.35 * np.clip(df["overdraft_fees_90d"] / 100.0, 0, 1)
        + 0.20 * np.clip(df["budget_sessions_30d"] / 8.0, 0, 1)
    )
    return np.clip(raw, 0.0, 1.0)


def generate_cohort(
    n_users: int,
    seed: int,
    cohort: str,
    treatment_share: float,
    id_prefix: str,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    segment = _draw_segments(rng, n_users)
    df = _behaviour_frame(rng, segment)
    p0, tau = _baseline_and_effect(df, segment, rng)

    df.insert(0, "user_id", [f"{id_prefix}{i:07d}" for i in range(n_users)])
    df["cohort"] = cohort
    df["segment"] = segment
    df["p0"] = p0.round(6)
    df["true_tau"] = tau.round(6)
    df["value_fit"] = _value_fit(df).round(4)

    if treatment_share > 0:
        treated = (rng.random(n_users) < treatment_share).astype(int)
        p_convert = np.where(treated == 1, p0 + tau, p0)
        converted = (rng.random(n_users) < p_convert).astype(int)

        # 30-day retention among converters -- the guardrail. Users pushed over
        # the line by the nudge whose fee profile does not match the product
        # retain materially worse. The interaction is the point: being pushed
        # only hurts when value fit is poor.
        pushed = (treated == 1) & (
            rng.random(n_users)
            < np.where(p_convert > 0, tau / np.maximum(p_convert, 1e-9), 0)
        )
        vf = df["value_fit"].to_numpy()
        retain_p = np.clip(
            0.58 + 0.34 * vf - 0.22 * pushed.astype(float) * (1 - vf), 0.05, 0.97
        )
        retained = np.where(
            converted == 1, (rng.random(n_users) < retain_p).astype(int), UNOBSERVED
        )
    else:
        treated = np.full(n_users, UNOBSERVED)
        converted = np.full(n_users, UNOBSERVED)
        retained = np.full(n_users, UNOBSERVED)

    df["treated"] = treated
    df["converted"] = converted
    df["retained_30d"] = retained
    return df


def build(
    n_users: int | None = None,
    seed: int | None = None,
    n_live: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the pilot (labelled) and live (unlabelled) cohorts."""
    n_users = n_users or config.N_USERS
    seed = seed if seed is not None else config.RANDOM_SEED
    n_live = n_live if n_live is not None else max(2_000, n_users // 5)

    pilot = generate_cohort(
        n_users, seed, "pilot", config.PILOT_TREATMENT_SHARE, id_prefix="u"
    )
    live = generate_cohort(n_live, seed + 977, "live", 0.0, id_prefix="l")
    return pilot, live


def main() -> None:
    config.ensure_dirs()
    pilot, live = build()
    pilot_path = config.DATA_DIR / "pilot_users.csv"
    live_path = config.DATA_DIR / "live_users.csv"
    pilot.to_csv(pilot_path, index=False)
    live.to_csv(live_path, index=False)

    treated = pilot[pilot.treated == 1]
    control = pilot[pilot.treated == 0]
    ate = treated.converted.mean() - control.converted.mean()
    print(f"pilot users      : {len(pilot):,}  -> {pilot_path}")
    print(f"live users       : {len(live):,}  -> {live_path}")
    print(f"control conv rate: {control.converted.mean():.4f}")
    print(f"treated conv rate: {treated.converted.mean():.4f}")
    print(f"observed ATE     : {ate:+.4f}  (true mean tau {pilot.true_tau.mean():+.4f})")
    print(
        "retention@30 among converters: "
        f"{pilot.loc[pilot.converted == 1, 'retained_30d'].mean():.4f}"
    )
    print("\nmean true uplift by segment:")
    print(pilot.groupby("segment").true_tau.agg(["mean", "size"]).round(4).to_string())


if __name__ == "__main__":
    main()
