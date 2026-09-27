"""Offline policy evaluation: what would this policy have achieved?

Before spending an experiment cycle we should be able to say what a candidate
targeting policy would have done on data we already hold. That is an off-policy
question — each user was observed under one arm only — so it needs an estimator
rather than a spreadsheet.

Three estimators, because they trade bias against variance differently:

* **IPS** — unbiased under known propensities, high variance when the policy and
  the logging distribution disagree.
* **SNIPS** — self-normalised IPS. Slightly biased, much lower variance, and it
  cannot produce the absurd values IPS occasionally does.
* **DR** — doubly robust. Consistent if *either* the outcome model or the
  propensity model is right. Usually the one to quote.

And an **oracle**, which only exists because the population is synthetic:
V = mean(p0 + tau * pi). It is not an estimator — it reads the answer — but it
lets us validate the estimators themselves. If the DR interval covers the oracle
value, the estimator is working. No real dataset can give you that check, and it
is the strongest argument that the numbers here mean something.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

import numpy as np
import pandas as pd

# Importance weights are clipped to stop a single user dominating the estimate.
# The clipped fraction is always reported: an unreported clip silently biases
# the result, which is worse than the variance it was meant to fix.
DEFAULT_WEIGHT_CLIP = 20.0


@dataclass
class PolicyValue:
    estimator: str
    value: float
    ci_low: float
    ci_high: float
    n: int
    clipped_fraction: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bootstrap_ci(
    fn: Callable[[np.ndarray], float],
    n: int,
    *,
    draws: int = 400,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    stats = np.empty(draws)
    for i in range(draws):
        stats[i] = fn(rng.integers(0, n, n))
    return float(np.quantile(stats, alpha / 2)), float(np.quantile(stats, 1 - alpha / 2))


def ips(
    y: np.ndarray, t: np.ndarray, pi: np.ndarray, e: np.ndarray | float = 0.5,
    *, clip: float = DEFAULT_WEIGHT_CLIP, seed: int = 0,
) -> PolicyValue:
    y, t, pi = np.asarray(y, float), np.asarray(t, int), np.asarray(pi, int)
    e_arr = np.full_like(y, float(e), dtype=float) if np.isscalar(e) else np.asarray(e, float)
    # Probability the logging policy assigned the action our policy would take.
    prob_taken = np.where(pi == 1, e_arr, 1.0 - e_arr)
    raw_w = np.where(t == pi, 1.0 / np.maximum(prob_taken, 1e-9), 0.0)
    w = np.minimum(raw_w, clip)
    clipped = float(np.mean(raw_w > clip))

    def stat(idx: np.ndarray) -> float:
        return float(np.mean(w[idx] * y[idx]))

    lo, hi = _bootstrap_ci(stat, len(y), seed=seed)
    return PolicyValue("IPS", float(np.mean(w * y)), lo, hi, len(y), clipped)


def snips(
    y: np.ndarray, t: np.ndarray, pi: np.ndarray, e: np.ndarray | float = 0.5,
    *, clip: float = DEFAULT_WEIGHT_CLIP, seed: int = 0,
) -> PolicyValue:
    y, t, pi = np.asarray(y, float), np.asarray(t, int), np.asarray(pi, int)
    e_arr = np.full_like(y, float(e), dtype=float) if np.isscalar(e) else np.asarray(e, float)
    prob_taken = np.where(pi == 1, e_arr, 1.0 - e_arr)
    raw_w = np.where(t == pi, 1.0 / np.maximum(prob_taken, 1e-9), 0.0)
    w = np.minimum(raw_w, clip)
    clipped = float(np.mean(raw_w > clip))

    def stat(idx: np.ndarray) -> float:
        denom = w[idx].sum()
        return float((w[idx] * y[idx]).sum() / denom) if denom else 0.0

    lo, hi = _bootstrap_ci(stat, len(y), seed=seed)
    total_w = w.sum()
    return PolicyValue(
        "SNIPS", float((w * y).sum() / total_w) if total_w else 0.0, lo, hi, len(y), clipped
    )


def doubly_robust(
    y: np.ndarray, t: np.ndarray, pi: np.ndarray,
    mu0: np.ndarray, mu1: np.ndarray, e: np.ndarray | float = 0.5,
    *, clip: float = DEFAULT_WEIGHT_CLIP, seed: int = 0,
) -> PolicyValue:
    y, t, pi = np.asarray(y, float), np.asarray(t, int), np.asarray(pi, int)
    mu0, mu1 = np.asarray(mu0, float), np.asarray(mu1, float)
    e_arr = np.full_like(y, float(e), dtype=float) if np.isscalar(e) else np.asarray(e, float)

    mu_pi = np.where(pi == 1, mu1, mu0)          # model's guess under our policy
    mu_obs = np.where(t == 1, mu1, mu0)          # model's guess under what happened
    prob_taken = np.where(pi == 1, e_arr, 1.0 - e_arr)
    raw_w = np.where(t == pi, 1.0 / np.maximum(prob_taken, 1e-9), 0.0)
    w = np.minimum(raw_w, clip)
    clipped = float(np.mean(raw_w > clip))

    contributions = mu_pi + w * (y - mu_obs)

    def stat(idx: np.ndarray) -> float:
        return float(np.mean(contributions[idx]))

    lo, hi = _bootstrap_ci(stat, len(y), seed=seed)
    return PolicyValue(
        "DR", float(np.mean(contributions)), lo, hi, len(y), clipped,
        note="consistent if either the outcome model or the propensity model is correct",
    )


def oracle_value(p0: np.ndarray, tau: np.ndarray, pi: np.ndarray) -> PolicyValue:
    """Ground truth. Available only because the population is simulated."""
    p0, tau, pi = np.asarray(p0, float), np.asarray(tau, float), np.asarray(pi, int)
    v = p0 + tau * pi
    se = float(v.std(ddof=1) / np.sqrt(len(v)))
    mean = float(v.mean())
    return PolicyValue(
        "oracle", mean, mean - 1.96 * se, mean + 1.96 * se, len(v),
        note="not an estimator — reads the true effect; used to validate the estimators",
    )


def evaluate_policy(
    frame: pd.DataFrame, pi: np.ndarray,
    mu0: np.ndarray | None = None, mu1: np.ndarray | None = None,
    *, treatment_propensity: float = 0.5, seed: int = 0,
) -> pd.DataFrame:
    """Run every applicable estimator against one policy."""
    y = frame["converted"].to_numpy()
    t = frame["treated"].to_numpy()

    results = [
        ips(y, t, pi, treatment_propensity, seed=seed),
        snips(y, t, pi, treatment_propensity, seed=seed),
    ]
    if mu0 is not None and mu1 is not None:
        results.append(doubly_robust(y, t, pi, mu0, mu1, treatment_propensity, seed=seed))
    if {"p0", "true_tau"}.issubset(frame.columns):
        results.append(oracle_value(frame["p0"], frame["true_tau"], pi))

    return pd.DataFrame([r.to_dict() for r in results])


def oracle_within_interval(table: pd.DataFrame, estimator: str = "DR") -> bool | None:
    """Whether the named estimator's interval covers the oracle value.

    This is the validation that synthetic data uniquely permits: it checks the
    *estimator*, not the policy.
    """
    if "oracle" not in set(table.estimator) or estimator not in set(table.estimator):
        return None
    o = table[table.estimator == "oracle"].iloc[0]
    e = table[table.estimator == estimator].iloc[0]
    return bool(e.ci_low <= o.value <= e.ci_high)
