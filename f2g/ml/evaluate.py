"""Offline evaluation for propensity and uplift models.

The central discipline here: **classification metrics and uplift metrics are not
interchangeable.** A propensity model is judged on discrimination (ROC AUC) and
calibration. An uplift model cannot be judged that way at all, because the
quantity it estimates — tau — is never observed for any individual user. We only
ever see one arm per user.

So uplift is judged on *ranking-with-a-counterfactual*: Qini, and realised uplift
by decile, both of which compare treated and control outcomes within score
strata. Reporting AUC for an uplift model is a category error that produces a
reassuring number about the wrong thing.

Because feature 001 gives us the true tau, this module can additionally report
the direct correlation between tau-hat and tau — a validation of the estimator
that is impossible with real data and is the strongest single piece of evidence
in the project.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


# --------------------------------------------------------------------------
# Propensity: discrimination and calibration
# --------------------------------------------------------------------------

def classification_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return {
        "n": int(len(y)),
        "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "log_loss": float(log_loss(y, p)),
        "brier": float(brier_score_loss(y, p)),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Predicted vs observed rate by predicted-probability decile.

    Calibration is what makes a probability usable in a decision. A model with
    excellent AUC and predictions biased 2x high ranks users correctly and makes
    every expected-value calculation downstream wrong.
    """
    df = pd.DataFrame({"y": np.asarray(y).astype(int), "p": np.asarray(p, dtype=float)})
    # `duplicates="drop"` because a model with many tied predictions produces
    # non-unique bin edges, which would otherwise raise.
    df["bin"] = pd.qcut(df["p"], q=bins, labels=False, duplicates="drop")
    out = (
        df.groupby("bin")
        .agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
        .reset_index()
    )
    out["gap"] = out["observed"] - out["predicted"]
    return out


def calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Sample-weighted mean absolute calibration gap (expected calibration error)."""
    t = calibration_table(y, p, bins)
    return float((t["gap"].abs() * t["n"]).sum() / t["n"].sum())


# --------------------------------------------------------------------------
# Uplift: Qini and decile uplift
# --------------------------------------------------------------------------

@dataclass
class QiniResult:
    fractions: list[float]
    qini: list[float]
    random_baseline: list[float]
    coefficient: float
    max_qini: float
    max_qini_at_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def qini_curve(y: np.ndarray, t: np.ndarray, score: np.ndarray, steps: int = 100) -> QiniResult:
    """Qini curve for a targeting score on randomised data.

    At each prefix of the score-ordered population:

        Qini(n) = Y_t(n) − Y_c(n) · N_t(n) / N_c(n)

    Read plainly: conversions among treated users in the prefix, minus what the
    control users in the same prefix would have contributed had there been as
    many of them. The rescaling is what makes the two arms comparable at every
    prefix, including early prefixes where the arm split is uneven by chance.

    The coefficient is the area between this curve and the straight line you
    would get from random targeting, normalised by the total incremental
    conversions available. It is bounded above by 1 for a perfect ranking and is
    negative for a ranking worse than random.
    """
    y = np.asarray(y).astype(float)
    t = np.asarray(t).astype(int)
    s = np.asarray(score, dtype=float)

    order = np.argsort(-s, kind="stable")
    y, t = y[order], t[order]

    cum_t = np.cumsum(t)
    cum_c = np.cumsum(1 - t)
    cum_yt = np.cumsum(y * t)
    cum_yc = np.cumsum(y * (1 - t))

    n = len(y)
    idx = np.unique(np.linspace(0, n, num=min(steps, n) + 1).astype(int))
    idx = idx[idx > 0]

    fractions, qini_vals = [], []
    for i in idx:
        nt, nc = cum_t[i - 1], cum_c[i - 1]
        # Until both arms are represented the quantity is undefined, not zero.
        q = 0.0 if nc == 0 or nt == 0 else cum_yt[i - 1] - cum_yc[i - 1] * (nt / nc)
        fractions.append(i / n)
        qini_vals.append(float(q))

    total_t, total_c = cum_t[-1], cum_c[-1]
    total_incremental = float(cum_yt[-1] - cum_yc[-1] * (total_t / total_c))

    # Random targeting yields incremental conversions proportional to reach.
    baseline = [f * total_incremental for f in fractions]

    area_model = float(np.trapezoid(qini_vals, fractions))
    area_random = float(np.trapezoid(baseline, fractions))
    denom = abs(total_incremental) * 0.5
    coefficient = (area_model - area_random) / denom if denom > 0 else 0.0

    best = int(np.argmax(qini_vals)) if qini_vals else 0
    return QiniResult(
        fractions=[float(f) for f in fractions],
        qini=qini_vals,
        random_baseline=[float(b) for b in baseline],
        coefficient=float(coefficient),
        max_qini=float(qini_vals[best]) if qini_vals else 0.0,
        max_qini_at_fraction=float(fractions[best]) if fractions else 0.0,
    )


def uplift_decile_table(
    y: np.ndarray, t: np.ndarray, score: np.ndarray, k: int = 10
) -> pd.DataFrame:
    """Realised uplift per score decile, decile 1 = highest score.

    This is the table that makes an uplift model believable or not. A working
    model shows a monotone decline across the top deciles and a *negative*
    bottom decile — the sleeping dogs it has located and would withhold contact
    from.
    """
    df = pd.DataFrame(
        {
            "y": np.asarray(y).astype(float),
            "t": np.asarray(t).astype(int),
            "s": np.asarray(score, dtype=float),
        }
    )
    df = df.sort_values("s", ascending=False, kind="stable").reset_index(drop=True)
    df["decile"] = (np.arange(len(df)) * k // len(df)) + 1

    rows = []
    for d, g in df.groupby("decile"):
        gt, gc = g[g.t == 1], g[g.t == 0]
        rt = float(gt.y.mean()) if len(gt) else float("nan")
        rc = float(gc.y.mean()) if len(gc) else float("nan")
        rows.append(
            {
                "decile": int(d),
                "n": int(len(g)),
                "n_treated": int(len(gt)),
                "n_control": int(len(gc)),
                "rate_treated": rt,
                "rate_control": rc,
                "realised_uplift": rt - rc,
                "mean_score": float(g.s.mean()),
            }
        )
    return pd.DataFrame(rows)


def tau_recovery(tau_hat: np.ndarray, tau_true: np.ndarray) -> dict[str, float]:
    """How well tau-hat recovers the known true tau.

    Only possible because the population is synthetic. Spearman is the headline
    because targeting only needs the *ordering* to be right; Pearson and RMSE are
    reported too, since a policy that thresholds on magnitude also cares about
    level.
    """
    a = np.asarray(tau_hat, dtype=float)
    b = np.asarray(tau_true, dtype=float)
    return {
        "spearman": float(stats.spearmanr(a, b).statistic),
        "pearson": float(stats.pearsonr(a, b).statistic),
        "rmse": float(np.sqrt(np.mean((a - b) ** 2))),
        "mean_tau_hat": float(a.mean()),
        "mean_tau_true": float(b.mean()),
        "sign_agreement": float(np.mean(np.sign(a) == np.sign(b))),
    }


# --------------------------------------------------------------------------
# Policy comparison: the argument for uplift over propensity
# --------------------------------------------------------------------------

def incremental_conversions_at_budget(
    y: np.ndarray, t: np.ndarray, score: np.ndarray, budget: float
) -> dict[str, float]:
    """Incremental conversions captured by contacting the top `budget` share.

    Computed from observed outcomes on randomised data, so it is a real estimate
    rather than a model-on-model projection: within the selected set, compare the
    treated conversion rate to the control conversion rate.
    """
    y = np.asarray(y).astype(float)
    t = np.asarray(t).astype(int)
    s = np.asarray(score, dtype=float)

    n_select = max(1, int(round(budget * len(y))))
    sel = np.argsort(-s, kind="stable")[:n_select]
    ys, ts = y[sel], t[sel]

    n_t, n_c = int(ts.sum()), int((1 - ts).sum())
    if n_t == 0 or n_c == 0:
        return {"budget": budget, "n_selected": n_select, "incremental_conversions": float("nan"),
                "incremental_per_contact": float("nan"), "rate_treated": float("nan"),
                "rate_control": float("nan")}

    rate_t = float(ys[ts == 1].mean())
    rate_c = float(ys[ts == 0].mean())
    uplift = rate_t - rate_c
    return {
        "budget": float(budget),
        "n_selected": int(n_select),
        "rate_treated": rate_t,
        "rate_control": rate_c,
        "uplift": float(uplift),
        # Scale the per-user uplift up to the whole selected set: this is what we
        # would gain by contacting all of them.
        "incremental_conversions": float(uplift * n_select),
        "incremental_per_contact": float(uplift),
    }


def policy_comparison(
    y: np.ndarray,
    t: np.ndarray,
    scores: dict[str, np.ndarray],
    budget: float,
    seed: int = 0,
) -> pd.DataFrame:
    """Compare rankings head to head at one contact budget, plus a random arm."""
    rng = np.random.default_rng(seed)
    all_scores = dict(scores)
    all_scores["random"] = rng.random(len(y))

    rows = []
    for name, s in all_scores.items():
        r = incremental_conversions_at_budget(y, t, s, budget)
        r["ranking"] = name
        rows.append(r)
    out = pd.DataFrame(rows).set_index("ranking")

    # Differences in percentage points are the primary comparison. Ratios are
    # reported only when the denominator is safely away from zero: a baseline
    # whose uplift is near zero makes the ratio explode into a meaningless
    # number (-2577% was observed during development), which is worse than no
    # number at all.
    if "random" in out.index:
        base_rand = float(out.loc["random", "incremental_per_contact"])
        out["vs_random_pp"] = (out["incremental_per_contact"] - base_rand) * 100
        out["vs_random_pct"] = np.where(
            abs(base_rand) >= MIN_RATIO_DENOMINATOR,
            (out["incremental_per_contact"] / base_rand - 1.0) * 100,
            np.nan,
        )
    if "propensity" in out.index:
        base_prop = float(out.loc["propensity", "incremental_per_contact"])
        out["vs_propensity_pp"] = (out["incremental_per_contact"] - base_prop) * 100
        out["vs_propensity_pct"] = np.where(
            abs(base_prop) >= MIN_RATIO_DENOMINATOR,
            (out["incremental_per_contact"] / base_prop - 1.0) * 100,
            np.nan,
        )
    return out.reset_index()


# Below this per-contact uplift, a ratio against the value is not reported.
# 0.005 = half a percentage point.
MIN_RATIO_DENOMINATOR = 0.005


def budget_sweep(
    y: np.ndarray,
    t: np.ndarray,
    scores: dict[str, np.ndarray],
    budgets: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50),
    seed: int = 0,
) -> pd.DataFrame:
    """Uplift per contact for each ranking across contact budgets.

    This is the table that should be read before choosing an operating point.
    A single number at one budget hides the fact that the advantage of uplift
    targeting is largest at small reach and disappears entirely at large reach —
    which is the finding that sets the budget, rather than the budget being
    picked first and the number reported afterwards.
    """
    rng = np.random.default_rng(seed)
    random_score = rng.random(len(y))
    rows = []
    for b in budgets:
        row: dict[str, Any] = {"budget": b}
        for name, s in scores.items():
            row[f"{name}_pp"] = incremental_conversions_at_budget(y, t, s, b)["incremental_per_contact"] * 100
        row["random_pp"] = incremental_conversions_at_budget(y, t, random_score, b)["incremental_per_contact"] * 100
        rows.append(row)
    return pd.DataFrame(rows)


def segment_mix_of_selection(
    df: pd.DataFrame, score: np.ndarray, budget: float
) -> pd.DataFrame:
    """Which latent segments a ranking actually selects.

    This is the diagnostic that shows *where* propensity ranking wastes budget,
    rather than only that it does: its selection is dense in `sure_thing` users
    who were converting anyway.
    """
    n_select = max(1, int(round(budget * len(df))))
    sel = np.argsort(-np.asarray(score, dtype=float), kind="stable")[:n_select]
    mix = df.iloc[sel]["segment"].value_counts(normalize=True).rename("share")
    return mix.reset_index().rename(columns={"index": "segment"})


# --------------------------------------------------------------------------
# Fairness slices
# --------------------------------------------------------------------------

def slice_metrics(
    df: pd.DataFrame,
    values: np.ndarray,
    by: str,
    metric_fn: Callable[[pd.DataFrame, np.ndarray], dict[str, float]],
    min_count: int = 200,
) -> pd.DataFrame:
    """Apply a metric function within each level of `by`.

    Slices below `min_count` are still reported but flagged low-confidence.
    Dropping them would hide exactly the small groups a fairness review cares
    about; presenting their noisy rates as comparable would be misleading. So:
    report, and mark.
    """
    rows = []
    v = np.asarray(values)
    for level, idx in df.groupby(by).groups.items():
        pos = df.index.get_indexer(idx)
        g = df.loc[idx]
        row: dict[str, Any] = {by: level, "n": len(g)}
        try:
            row.update(metric_fn(g, v[pos]))
        except (ValueError, ZeroDivisionError) as exc:
            row["error"] = str(exc)
        row["low_confidence"] = len(g) < min_count
        rows.append(row)
    return pd.DataFrame(rows).sort_values(by).reset_index(drop=True)
