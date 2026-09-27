"""Figures for the model evaluation report.

Each figure is rendered in both light and dark, from the same ramps, because a
dark chart is a selected design rather than an inverted light one.

Form choices, and why:

* **Qini curves** — change over a reach axis, three competing rankings. Lines,
  one axis, direct labels at the right edge so identity never depends on colour.
* **Decile uplift** — polarity. The point of the chart is that the bottom decile
  is *negative*, so it uses the diverging pair (blue positive, red negative)
  around a zero baseline, not a single-hue ramp.
* **Calibration** — one series against an identity reference. No legend: the
  title names the series, and the reference line is labelled in place.
* **Tau recovery** — one series, binned, with a reference line. Same treatment.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from f2g.viz import (
    SYNTHETIC_NOTE,
    THEMES,
    Theme,
    apply_style,
    caption,
    direct_label,
    end_labels,
    rounded_bars,
)


def _save(fig, out_dir: Path, stem: str, theme: Theme) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.{theme.name}.png"
    fig.savefig(path, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return path


def qini_chart(curves: dict[str, dict], out_dir: Path) -> list[Path]:
    """`curves` maps ranking name -> {'fractions', 'qini', 'random_baseline', 'coefficient'}."""
    paths = []
    for theme in THEMES.values():
        apply_style(theme)
        fig, ax = plt.subplots(figsize=(7.2, 4.6))

        # Caller ordering wins: slot 1 (the strongest, highest-contrast hue) must
        # go to the production estimator. Re-sorting here once handed the prime
        # slot to a superseded model and pushed the shipped one onto the slot
        # that carries a light-mode contrast warning.
        names = list(curves)[:3]  # three-series cap: a fourth slot fails the colour gates

        # Random targeting is a reference, not a series — it gets reference ink.
        any_curve = curves[names[0]]
        ax.plot(
            any_curve["fractions"],
            any_curve["random_baseline"],
            color=theme.reference,
            linewidth=1.4,
            linestyle=(0, (4, 3)),
            zorder=2,
        )
        label_items = [
            (any_curve["random_baseline"][-1], "random", theme.text_muted),
        ]

        for slot, name in enumerate(names):
            c = curves[name]
            color = theme.series[slot]
            ax.plot(c["fractions"], c["qini"], color=color, linewidth=2.0, zorder=4, solid_capstyle="round")
            label_items.append((c["qini"][-1], f"{name}  (Q={c['coefficient']:.3f})", color))

        ax.set_xlabel("Share of population contacted")
        ax.set_ylabel("Cumulative incremental conversions")
        ax.set_title("Qini curves — incremental conversions captured by reach")
        ax.axhline(0, color=theme.grid, linewidth=1.0, zorder=1)
        ax.set_xlim(0, 1.0)
        ax.margins(x=0.02)
        # Room on the right for the direct labels that replace a legend.
        ax.set_xlim(0, 1.34)
        ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_xticklabels(["0%", "20%", "40%", "60%", "80%", "100%"])
        end_labels(ax, label_items, theme, x=1.0)
        caption(fig, SYNTHETIC_NOTE, theme)
        paths.append(_save(fig, out_dir, "qini_curves", theme))
    return paths


def uplift_decile_chart(table: pd.DataFrame, out_dir: Path, title_suffix: str = "") -> list[Path]:
    paths = []
    for theme in THEMES.values():
        apply_style(theme)
        fig, ax = plt.subplots(figsize=(7.2, 4.4))

        xs = table["decile"].to_numpy()
        hs = table["realised_uplift"].to_numpy() * 100  # percentage points
        colors = [theme.diverge_pos if h >= 0 else theme.diverge_neg for h in hs]

        ax.set_xlim(xs.min() - 0.7, xs.max() + 0.7)
        lo, hi = min(hs.min(), 0), max(hs.max(), 0)
        pad = (hi - lo) * 0.22 or 1.0
        ax.set_ylim(lo - pad, hi + pad)
        fig.canvas.draw()  # bars need a realised axes box to size the 2px gap

        rounded_bars(ax, xs, hs, colors=colors, width=0.78)
        ax.axhline(0, color=theme.text_muted, linewidth=1.2, zorder=4)

        for x, h in zip(xs, hs):
            ax.annotate(
                f"{h:+.1f}",
                xy=(x, h),
                xytext=(0, 5 if h >= 0 else -13),
                textcoords="offset points",
                ha="center",
                color=theme.text_secondary,
                fontsize=8,
                fontweight="600",
            )

        ax.set_xticks(xs)
        ax.set_xlabel("Decile of predicted uplift  (1 = highest)")
        ax.set_ylabel("Realised uplift (percentage points)")
        ax.set_title(f"Realised uplift by predicted-uplift decile{title_suffix}")
        ax.grid(axis="y")
        caption(
            fig,
            f"{SYNTHETIC_NOTE}  Negative bottom deciles are the users the policy withholds contact from.",
            theme,
        )
        paths.append(_save(fig, out_dir, "uplift_deciles", theme))
    return paths


def calibration_chart(table: pd.DataFrame, out_dir: Path) -> list[Path]:
    paths = []
    for theme in THEMES.values():
        apply_style(theme)
        fig, ax = plt.subplots(figsize=(5.4, 5.0))

        lim = float(max(table["predicted"].max(), table["observed"].max())) * 1.12
        ax.plot([0, lim], [0, lim], color=theme.reference, linewidth=1.4, linestyle=(0, (4, 3)), zorder=2)
        ax.annotate(
            "perfect calibration",
            xy=(lim * 0.62, lim * 0.62),
            xytext=(4, -12),
            textcoords="offset points",
            color=theme.text_muted,
            fontsize=8,
            rotation=38,
            rotation_mode="anchor",
        )

        ax.plot(
            table["predicted"],
            table["observed"],
            color=theme.series[0],
            marker="o",
            markersize=5.5,
            markeredgecolor=theme.surface,
            markeredgewidth=2.0,  # 2px surface ring on overlapping marks
            linewidth=2.0,
            zorder=4,
        )

        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.set_aspect("equal")
        ax.grid(axis="both")
        ax.set_xlabel("Mean predicted conversion probability")
        ax.set_ylabel("Observed conversion rate")
        ax.set_title("Propensity calibration by predicted decile")
        caption(fig, SYNTHETIC_NOTE, theme)
        paths.append(_save(fig, out_dir, "calibration", theme))
    return paths


def tau_recovery_chart(tau_hat: np.ndarray, tau_true: np.ndarray, out_dir: Path,
                       spearman: float, bins: int = 20) -> list[Path]:
    """Binned mean true tau against predicted tau.

    A raw scatter of 15,000 noisy points hides the relationship in overplotting.
    Binning by prediction and plotting the mean truth per bin shows whether the
    estimator is right *on average at each level*, which is what a threshold
    policy depends on.
    """
    df = pd.DataFrame({"hat": np.asarray(tau_hat, float), "true": np.asarray(tau_true, float)})
    df["bin"] = pd.qcut(df["hat"], q=bins, labels=False, duplicates="drop")
    g = df.groupby("bin").agg(hat=("hat", "mean"), true=("true", "mean"), n=("true", "size"))

    paths = []
    for theme in THEMES.values():
        apply_style(theme)
        fig, ax = plt.subplots(figsize=(5.6, 5.0))

        lo = float(min(g["hat"].min(), g["true"].min()))
        hi = float(max(g["hat"].max(), g["true"].max()))
        pad = (hi - lo) * 0.1
        lo, hi = lo - pad, hi + pad

        ax.plot([lo, hi], [lo, hi], color=theme.reference, linewidth=1.4, linestyle=(0, (4, 3)), zorder=2)
        ax.axhline(0, color=theme.grid, linewidth=1.0, zorder=1)
        ax.axvline(0, color=theme.grid, linewidth=1.0, zorder=1)
        ax.plot(
            g["hat"], g["true"],
            color=theme.series[0], marker="o", markersize=5.5,
            markeredgecolor=theme.surface, markeredgewidth=2.0, linewidth=2.0, zorder=4,
        )

        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_aspect("equal")
        ax.grid(axis="both")
        ax.set_xlabel("Predicted uplift  (binned mean)")
        ax.set_ylabel("True uplift  (mean within bin)")
        ax.set_title(f"Uplift recovery against ground truth  ·  Spearman {spearman:.3f}")
        caption(
            fig,
            f"{SYNTHETIC_NOTE}  True uplift is knowable only because the population is simulated.",
            theme,
        )
        paths.append(_save(fig, out_dir, "tau_recovery", theme))
    return paths


def budget_sweep_chart(sweep: pd.DataFrame, out_dir: Path, chosen_budget: float) -> list[Path]:
    """Uplift per contact against contact budget, for each ranking.

    Two series carry identity (the production estimator and the propensity
    baseline); the oracle and random rankings are references and wear reference
    ink rather than a categorical slot. The chosen operating budget is marked,
    because the decision the chart supports is *where to stand on this axis*.
    """
    paths = []
    series_cols = [c for c in ("uplift_x_pp", "propensity_pp") if c in sweep.columns]
    labels = {"uplift_x_pp": "uplift (X-learner)", "propensity_pp": "propensity"}

    for theme in THEMES.values():
        apply_style(theme)
        fig, ax = plt.subplots(figsize=(7.4, 4.6))
        x = sweep["budget"].to_numpy()

        label_items = []
        for col, ink, label in (
            ("oracle_pp", theme.reference, "oracle ceiling"),
            ("random_pp", theme.text_muted, "random"),
        ):
            if col in sweep.columns:
                ax.plot(x, sweep[col], color=ink, linewidth=1.4, linestyle=(0, (4, 3)), zorder=2)
                label_items.append((float(sweep[col].iloc[-1]), label, ink))

        for slot, col in enumerate(series_cols):
            color = theme.series[slot]
            ax.plot(x, sweep[col], color=color, linewidth=2.0, marker="o", markersize=5.0,
                    markeredgecolor=theme.surface, markeredgewidth=2.0, zorder=4)
            label_items.append((float(sweep[col].iloc[-1]), labels[col], color))

        ax.axhline(0, color=theme.text_muted, linewidth=1.0, zorder=1)
        ax.axvline(chosen_budget, color=theme.diverge_pos, linewidth=1.2,
                   linestyle=(0, (2, 2)), alpha=0.6, zorder=1)
        ax.annotate(
            f"operating budget {chosen_budget:.0%}",
            xy=(chosen_budget, 0.985), xycoords=("data", "axes fraction"),
            xytext=(5, 0), textcoords="offset points",
            color=theme.text_secondary, fontsize=8, fontweight="600",
            ha="left", va="top",
        )

        ax.set_xlabel("Contact budget (share of population contacted)")
        ax.set_ylabel("Incremental conversions per contact (pp)")
        ax.set_title("Where uplift targeting pays — advantage by reach")
        ax.set_xlim(0, float(x[-1]) * 1.42)
        ax.set_xticks(list(x))
        ax.set_xticklabels([f"{v:.0%}" for v in x])
        end_labels(ax, label_items, theme, x=float(x[-1]))
        caption(
            fig,
            f"{SYNTHETIC_NOTE}  Past ~30% reach the rankings converge: a large budget must "
            f"include most movable users regardless of how they are ordered.",
            theme,
        )
        paths.append(_save(fig, out_dir, "budget_sweep", theme))
    return paths
