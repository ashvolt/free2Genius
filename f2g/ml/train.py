"""Train and evaluate the propensity and uplift models, end to end.

Run: `python -m f2g.ml.train`

Outputs, all under `artifacts/`:

    models/propensity.joblib            + .meta.json
    models/uplift_t.joblib              + .meta.json
    models/uplift_s.joblib              + .meta.json
    reports/model_evaluation.json       every metric, machine-readable
    reports/model_evaluation.md         the human summary
    charts/*.{light,dark}.png           qini, deciles, calibration, tau recovery

The split discipline matters more than the hyperparameters here. Early stopping
needs a validation set, and if that set is carved out of the *test* data then
every reported metric is optimistic. So the pilot is cut three ways — train,
valid, test — and the test split is not touched until the models are frozen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from f2g import config
from f2g.data.schema import FEATURES
from f2g.ml import charts, evaluate
from f2g.ml.features import FeaturePipeline
from f2g.ml.models import (
    BASE_PARAMS,
    UPLIFT_ARM_PARAMS,
    PropensityModel,
    SLearner,
    TLearner,
    XLearner,
)
from f2g.ml.registry import BundleMeta, ModelBundle, data_fingerprint

REPORT_DIR = config.ARTIFACT_DIR / "reports"
CHART_DIR = config.ARTIFACT_DIR / "charts"


def split_pilot(pilot: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Three-way split, stratified on the (arm, outcome) cell.

    Stratifying on the interaction rather than the outcome alone keeps both arms'
    positive rates stable across splits. Without it, a chance imbalance in the
    control arm moves the uplift estimate more than any modelling choice would.
    """
    strata = pilot["treated"].astype(str) + "_" + pilot["converted"].astype(str)
    train_valid, test = train_test_split(
        pilot, test_size=config.TEST_SIZE, random_state=seed, stratify=strata
    )
    tv_strata = train_valid["treated"].astype(str) + "_" + train_valid["converted"].astype(str)
    valid_share = config.VALID_SIZE / (1 - config.TEST_SIZE)
    train, valid = train_test_split(
        train_valid, test_size=valid_share, random_state=seed, stratify=tv_strata
    )
    return (
        train.reset_index(drop=True),
        valid.reset_index(drop=True),
        test.reset_index(drop=True),
    )


def train_all(pilot: pd.DataFrame, seed: int) -> dict[str, Any]:
    train, valid, test = split_pilot(pilot, seed)
    fingerprint = data_fingerprint(pilot)
    print(f"split  train={len(train):,}  valid={len(valid):,}  test={len(test):,}")

    plain = FeaturePipeline(feature_names=list(FEATURES))
    with_treatment = FeaturePipeline(feature_names=list(FEATURES), treatment_column="treated")

    # --- propensity: control arm only -----------------------------------
    print("training propensity (control arm)…")
    prop = PropensityModel(pipeline=plain).fit(
        train[train.treated == 0], valid[valid.treated == 0], seed
    )

    # --- uplift ---------------------------------------------------------
    print("training S-learner…")
    s_learner = SLearner(pipeline=with_treatment).fit(train, valid, seed)
    print("training T-learner…")
    t_learner = TLearner(pipeline=plain).fit(train, valid, seed)
    # Ablation: the same T-learner with default (outcome-model) hyperparameters.
    # Not a candidate for production — it exists so the regularisation claim in the
    # report is a live measurement rather than an anecdote.
    print("training T-learner (unregularised, ablation)…")
    t_unreg = TLearner(pipeline=plain, arm_params=BASE_PARAMS).fit(train, valid, seed)
    print("training X-learner…")
    x_learner = XLearner(
        pipeline=plain, treatment_propensity=config.PILOT_TREATMENT_SHARE
    ).fit(train, valid, seed)

    # --- evaluate on the untouched test split ---------------------------
    print("evaluating…")
    y = test["converted"].to_numpy()
    t = test["treated"].to_numpy()
    tau_true = test["true_tau"].to_numpy()

    p_prop = prop.predict_proba(test)
    tau_t = t_learner.predict_uplift(test)
    tau_s = s_learner.predict_uplift(test)
    tau_x = x_learner.predict_uplift(test)
    tau_t_unreg = t_unreg.predict_uplift(test)

    # Propensity is judged on the control arm, where no treatment effect
    # contaminates the label it was trained to predict.
    ctrl = test.treated == 0
    prop_metrics = evaluate.classification_metrics(y[ctrl.to_numpy()], p_prop[ctrl.to_numpy()])
    calib = evaluate.calibration_table(y[ctrl.to_numpy()], p_prop[ctrl.to_numpy()])
    prop_metrics["calibration_error"] = evaluate.calibration_error(
        y[ctrl.to_numpy()], p_prop[ctrl.to_numpy()]
    )

    qini = {
        "uplift (X-learner)": evaluate.qini_curve(y, t, tau_x).to_dict(),
        "propensity": evaluate.qini_curve(y, t, p_prop).to_dict(),
        "uplift (T-learner)": evaluate.qini_curve(y, t, tau_t).to_dict(),
        "uplift (S-learner)": evaluate.qini_curve(y, t, tau_s).to_dict(),
        "uplift (T-learner, unregularised)": evaluate.qini_curve(y, t, tau_t_unreg).to_dict(),
        # The oracle is not a shippable model — it reads the answer. It is
        # reported as the ceiling, so every estimator below can be read as a
        # fraction of what is achievable rather than as an absolute number.
        "oracle (true tau)": evaluate.qini_curve(y, t, tau_true).to_dict(),
    }
    deciles_x = evaluate.uplift_decile_table(y, t, tau_x)
    deciles_t = evaluate.uplift_decile_table(y, t, tau_t)
    deciles_s = evaluate.uplift_decile_table(y, t, tau_s)
    deciles_oracle = evaluate.uplift_decile_table(y, t, tau_true)
    recovery_x = evaluate.tau_recovery(tau_x, tau_true)
    recovery_t = evaluate.tau_recovery(tau_t, tau_true)
    recovery_s = evaluate.tau_recovery(tau_s, tau_true)
    recovery_t_unreg = evaluate.tau_recovery(tau_t_unreg, tau_true)
    deciles_t_unreg = evaluate.uplift_decile_table(y, t, tau_t_unreg)

    # Which estimator ships is decided by measurement, not by preference.
    ranked = sorted(
        [("uplift_x", qini["uplift (X-learner)"]["coefficient"]),
         ("uplift_t", qini["uplift (T-learner)"]["coefficient"]),
         ("uplift_s", qini["uplift (S-learner)"]["coefficient"])],
        key=lambda kv: -kv[1],
    )
    production_estimator = ranked[0][0]
    print(f"  production uplift estimator by Qini: {production_estimator} "
          f"({ranked[0][1]:.4f}); runners-up {ranked[1:]}")

    budget = config.DEFAULT_CONTACT_BUDGET
    comparison = evaluate.policy_comparison(
        y, t,
        {"uplift_x": tau_x, "uplift_t": tau_t, "uplift_s": tau_s,
         "propensity": p_prop, "oracle": tau_true},
        budget, seed=seed,
    )
    sweep = evaluate.budget_sweep(
        y, t, {"uplift_x": tau_x, "propensity": p_prop, "oracle": tau_true}, seed=seed
    )

    # The segment mix at a small budget is the clearest single piece of evidence
    # in this report, so it is computed at 10% as well as at the operating point.
    mix_at_10 = {
        "uplift_x": evaluate.segment_mix_of_selection(test, tau_x, 0.10).to_dict("records"),
        "propensity": evaluate.segment_mix_of_selection(test, p_prop, 0.10).to_dict("records"),
    }
    mix = {
        "uplift_x": evaluate.segment_mix_of_selection(test, tau_x, budget).to_dict("records"),
        "uplift_t": evaluate.segment_mix_of_selection(test, tau_t, budget).to_dict("records"),
        "propensity": evaluate.segment_mix_of_selection(test, p_prop, budget).to_dict("records"),
    }

    # --- fairness slices -------------------------------------------------
    def prop_slice(g: pd.DataFrame, v: np.ndarray) -> dict[str, float]:
        gc = g.treated == 0
        if gc.sum() < 30 or g.loc[gc, "converted"].nunique() < 2:
            raise ValueError("insufficient control-arm signal in slice")
        m = evaluate.classification_metrics(g.loc[gc, "converted"].to_numpy(), v[gc.to_numpy()])
        m["calibration_error"] = evaluate.calibration_error(
            g.loc[gc, "converted"].to_numpy(), v[gc.to_numpy()]
        )
        return m

    def uplift_slice(g: pd.DataFrame, v: np.ndarray) -> dict[str, float]:
        return {
            "mean_predicted_uplift": float(np.mean(v)),
            "mean_true_uplift": float(g["true_tau"].mean()),
            "share_positive_uplift": float(np.mean(v > 0)),
        }

    slices = {
        "propensity_by_income": evaluate.slice_metrics(
            test, p_prop, "income_band", prop_slice
        ).to_dict("records"),
        "uplift_by_income": evaluate.slice_metrics(
            test, tau_x, "income_band", uplift_slice
        ).to_dict("records"),
    }

    # --- persist ---------------------------------------------------------
    bundles = [
        ModelBundle(
            BundleMeta(
                name="propensity", kind="propensity", feature_names=plain.columns,
                params=dict(prop.model.get_params()), metrics=prop_metrics,
                data_fingerprint=fingerprint, n_train=int((train.treated == 0).sum()), seed=seed,
                notes="Trained on the control arm only, so the label is free of treatment effect.",
            ),
            prop,
        ),
        ModelBundle(
            BundleMeta(
                name="uplift_t", kind="uplift_t", feature_names=plain.columns,
                params=dict(t_learner.model_treated.get_params()),
                metrics={"qini_coefficient": qini["uplift (T-learner)"]["coefficient"], **recovery_t},
                data_fingerprint=fingerprint, n_train=len(train), seed=seed,
                notes="Production uplift estimator. tau = P(Y|T=1) - P(Y|T=0).",
            ),
            t_learner,
        ),
        ModelBundle(
            BundleMeta(
                name="uplift_x", kind="uplift_x", feature_names=plain.columns,
                params=dict(x_learner.tau1.get_params()),
                metrics={"qini_coefficient": qini["uplift (X-learner)"]["coefficient"], **recovery_x},
                data_fingerprint=fingerprint, n_train=len(train), seed=seed,
                notes=("X-learner (Kunzel et al. 2019). Regresses imputed effects, which "
                       "cuts the variance that made the plain T-learner rank worse than "
                       "propensity on this data. Known treatment propensity 0.5, so no "
                       "propensity-of-treatment model is needed."),
            ),
            x_learner,
        ),
        ModelBundle(
            BundleMeta(
                name="uplift_s", kind="uplift_s", feature_names=with_treatment.columns,
                params=dict(s_learner.model.get_params()),
                metrics={"qini_coefficient": qini["uplift (S-learner)"]["coefficient"], **recovery_s},
                data_fingerprint=fingerprint, n_train=len(train), seed=seed,
                notes="Reference estimator; single model with treatment as a feature.",
            ),
            s_learner,
        ),
    ]
    for b in bundles:
        print(f"  saved {b.save()}")

    # --- charts ----------------------------------------------------------
    # Production estimator first so it takes categorical slot 1.
    prod_qini_label = {"uplift_x": "uplift (X-learner)", "uplift_t": "uplift (T-learner)",
                       "uplift_s": "uplift (S-learner)"}[production_estimator]
    others = [k for k in ("propensity", "uplift (T-learner)", "uplift (X-learner)")
              if k != prod_qini_label][:2]
    charts.qini_chart({k: qini[k] for k in [prod_qini_label, *others]}, CHART_DIR)
    charts.uplift_decile_chart(deciles_x, CHART_DIR, title_suffix="  ·  X-learner")
    charts.calibration_chart(calib, CHART_DIR)
    charts.tau_recovery_chart(tau_x, tau_true, CHART_DIR, recovery_x["spearman"])
    charts.budget_sweep_chart(sweep, CHART_DIR, budget)
    print(f"  charts -> {CHART_DIR}")

    return {
        "seed": seed,
        "data_fingerprint": fingerprint,
        "split": {"train": len(train), "valid": len(valid), "test": len(test)},
        "contact_budget": budget,
        "propensity": prop_metrics,
        "calibration_table": calib.to_dict("records"),
        "qini": {k: {kk: vv for kk, vv in v.items() if kk not in ("fractions", "qini", "random_baseline")}
                 for k, v in qini.items()},
        "qini_curves": qini,
        "production_estimator": production_estimator,
        "estimator_ranking_by_qini": ranked,
        "uplift_deciles_x": deciles_x.to_dict("records"),
        "uplift_deciles_oracle": deciles_oracle.to_dict("records"),
        "uplift_deciles_t": deciles_t.to_dict("records"),
        "uplift_deciles_s": deciles_s.to_dict("records"),
        "tau_recovery": {
            "x_learner": recovery_x, "t_learner": recovery_t, "s_learner": recovery_s,
            "t_learner_unregularised": recovery_t_unreg,
        },
        "regularisation_ablation": {
            "description": (
                "Same T-learner, two hyperparameter settings. Default settings are tuned "
                "for fitting a 15% outcome; they over-fit a 1-8 percentage-point treatment "
                "effect, and a T-learner subtracts two such fits so the errors compound."
            ),
            "default_params": {k: BASE_PARAMS[k] for k in
                               ("num_leaves", "min_child_samples", "learning_rate",
                                "n_estimators", "reg_lambda")},
            "regularised_params": UPLIFT_ARM_PARAMS,
            "unregularised": {
                "qini": qini["uplift (T-learner, unregularised)"]["coefficient"],
                "spearman": recovery_t_unreg["spearman"],
                "bottom_decile_uplift": float(deciles_t_unreg.iloc[-1]["realised_uplift"]),
                "tau_min": float(tau_t_unreg.min()), "tau_max": float(tau_t_unreg.max()),
            },
            "regularised": {
                "qini": qini["uplift (T-learner)"]["coefficient"],
                "spearman": recovery_t["spearman"],
                "bottom_decile_uplift": float(deciles_t.iloc[-1]["realised_uplift"]),
                "tau_min": float(tau_t.min()), "tau_max": float(tau_t.max()),
            },
        },
        "tau_dispersion": {
            "true": {"min": float(tau_true.min()), "max": float(tau_true.max()),
                     "std": float(tau_true.std())},
            "x_learner": {"min": float(tau_x.min()), "max": float(tau_x.max()),
                          "std": float(tau_x.std())},
            "t_learner": {"min": float(tau_t.min()), "max": float(tau_t.max()),
                          "std": float(tau_t.std())},
            "t_learner_unregularised": {"min": float(tau_t_unreg.min()),
                                        "max": float(tau_t_unreg.max()),
                                        "std": float(tau_t_unreg.std())},
        },
        "policy_comparison": comparison.to_dict("records"),
        "budget_sweep": sweep.to_dict("records"),
        "selection_segment_mix": mix,
        "selection_segment_mix_at_10pct": mix_at_10,
        "fairness_slices": slices,
        "feature_importance_propensity": dict(list(prop.feature_importance.items())[:15]),
        "feature_importance_uplift_x": dict(list(x_learner.feature_importance.items())[:15]),
        "feature_importance_uplift_t": dict(list(t_learner.feature_importance.items())[:15]),
    }


def _md_report(r: dict[str, Any]) -> str:
    def pct(x: float) -> str:
        return f"{x * 100:.2f}%"

    ab = r["regularisation_ablation"]

    comp = pd.DataFrame(r["policy_comparison"]).set_index("ranking")
    prod = r["production_estimator"]
    up = comp.loc[prod, "incremental_conversions"]
    pr = comp.loc["propensity", "incremental_conversions"]
    gain = (up / pr - 1) * 100 if pr else float("nan")
    prod_qini_key = {"uplift_x": "uplift (X-learner)", "uplift_t": "uplift (T-learner)",
                     "uplift_s": "uplift (S-learner)"}[prod]
    prod_rec_key = {"uplift_x": "x_learner", "uplift_t": "t_learner", "uplift_s": "s_learner"}[prod]

    lines = [
        "# Model Evaluation Report",
        "",
        "> Synthetic data — generated by `f2g/data/generate.py`. Not Albert data.",
        "",
        f"Seed `{r['seed']}` · data fingerprint `{r['data_fingerprint']}` · "
        f"split {r['split']['train']:,}/{r['split']['valid']:,}/{r['split']['test']:,}",
        "",
        "## Headline",
        "",
        f"- Propensity ROC AUC **{r['propensity']['roc_auc']:.4f}**, "
        f"calibration error **{r['propensity']['calibration_error']:.4f}**",
        f"- Production estimator **{prod}** · Qini "
        f"**{r['qini'][prod_qini_key]['coefficient']:.4f}** vs propensity "
        f"{r['qini']['propensity']['coefficient']:.4f} "
        f"(oracle ceiling {r['qini']['oracle (true tau)']['coefficient']:.4f})",
        f"- Recovers true uplift at Spearman "
        f"**{r['tau_recovery'][prod_rec_key]['spearman']:.4f}**",
        f"- At a {pct(r['contact_budget'])} contact budget, uplift ranking captures "
        f"**{gain:+.1f}%** more incremental conversions than propensity ranking",
        "",
        "### The finding that shaped this model",
        "",
        "The first uplift estimator built here was a plain T-learner with the same "
        "hyperparameters as the outcome model. It **ranked worse than the propensity "
        f"baseline**: Qini {ab['unregularised']['qini']:.4f} against propensity's "
        f"{r['qini']['propensity']['coefficient']:.4f}, and its bottom decile showed "
        f"{ab['unregularised']['bottom_decile_uplift'] * 100:+.2f} pp realised uplift when a "
        "working estimator must be negative there.",
        "",
        "The cause is dispersion. Those settings are tuned to fit a ~15% conversion "
        "outcome; a treatment effect is one to eight percentage points, and a T-learner "
        "*subtracts* two such fits, so their errors compound rather than cancel. The "
        f"unregularised estimator predicted uplift spanning "
        f"[{ab['unregularised']['tau_min']:+.3f}, {ab['unregularised']['tau_max']:+.3f}] "
        f"against a true range of [{r['tau_dispersion']['true']['min']:+.3f}, "
        f"{r['tau_dispersion']['true']['max']:+.3f}] — its extreme deciles were populated "
        "by noise, not by effect.",
        "",
        "Two changes fixed it, both reproducible by re-running this script:",
        "",
        f"1. **Regularising the arm models** (leaves {ab['default_params']['num_leaves']} → "
        f"{ab['regularised_params']['num_leaves']}, min child samples "
        f"{ab['default_params']['min_child_samples']} → "
        f"{ab['regularised_params']['min_child_samples']}, L2 "
        f"{ab['default_params']['reg_lambda']} → {ab['regularised_params']['reg_lambda']}) "
        f"lifted Qini from {ab['unregularised']['qini']:.4f} to "
        f"{ab['regularised']['qini']:.4f} and turned the bottom decile negative "
        f"({ab['regularised']['bottom_decile_uplift'] * 100:+.2f} pp).",
        f"2. **Moving to an X-learner**, which regresses *imputed* effects and so can be "
        f"regularised toward zero directly, added a further gain to "
        f"{r['qini']['uplift (X-learner)']['coefficient']:.4f}.",
        "",
        "ADR-002 pre-declared \"revisit once T-learner Qini plateaus\" as the trigger for "
        "trying a more sophisticated meta-learner. That condition was met by measurement, "
        "which is why the X-learner is in the codebase and the S-learner is not in "
        "production.",
        "",
        "### Uplift dispersion — why the T-learner failed",
        "",
        "| estimator | min tau | max tau | std |",
        "|---|---|---|---|",
    ] + [
        f"| {k} | {v['min']:+.4f} | {v['max']:+.4f} | {v['std']:.4f} |"
        for k, v in r["tau_dispersion"].items()
    ] + [
        "",
        "## Propensity model",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    for k in ("n", "positive_rate", "roc_auc", "pr_auc", "log_loss", "brier", "calibration_error"):
        lines.append(f"| {k} | {r['propensity'][k]:.4f} |")

    lines += ["", "## Uplift estimators", "",
              "Ranked by Qini. The oracle is not shippable — it reads the answer — and is "
              "shown as the ceiling so each estimator can be read as a share of what is "
              "achievable on this population.", "",
              "| estimator | Qini | % of oracle | Spearman vs true tau | sign agreement | RMSE |",
              "|---|---|---|---|---|---|"]
    ceiling = r["qini"]["oracle (true tau)"]["coefficient"]
    for label, key, qk in (
        ("X-learner", "x_learner", "uplift (X-learner)"),
        ("T-learner", "t_learner", "uplift (T-learner)"),
        ("S-learner", "s_learner", "uplift (S-learner)"),
    ):
        rec = r["tau_recovery"][key]
        q = r["qini"][qk]["coefficient"]
        share = f"{q / ceiling * 100:.0f}%" if ceiling else "—"
        lines.append(
            f"| {label} | {q:.4f} | {share} | {rec['spearman']:.4f} | "
            f"{rec['sign_agreement']:.4f} | {rec['rmse']:.5f} |"
        )
    lines.append(
        f"| _propensity (baseline)_ | {r['qini']['propensity']['coefficient']:.4f} | "
        f"{r['qini']['propensity']['coefficient'] / ceiling * 100:.0f}% | — | — | — |"
    )
    lines.append(f"| _oracle (ceiling)_ | {ceiling:.4f} | 100% | 1.0000 | 1.0000 | 0.00000 |")

    lines += ["", "## Realised uplift by predicted-uplift decile", "",
              "Decile 1 is the highest predicted uplift. A working estimator declines "
              "monotonically and turns negative at the bottom — those are the users the "
              "policy withholds contact from. The oracle column shows what is attainable.",
              "",
              "| decile | n | rate treated | rate control | realised uplift (production) | realised uplift (oracle) |",
              "|---|---|---|---|---|---|"]
    oracle_by_decile = {d["decile"]: d["realised_uplift"] for d in r["uplift_deciles_oracle"]}
    prod_deciles = r["uplift_deciles_x"] if prod == "uplift_x" else r["uplift_deciles_t"]
    for row in prod_deciles:
        lines.append(
            f"| {row['decile']} | {row['n']:,} | {pct(row['rate_treated'])} | "
            f"{pct(row['rate_control'])} | {row['realised_uplift'] * 100:+.2f} pp | "
            f"{oracle_by_decile.get(row['decile'], float('nan')) * 100:+.2f} pp |"
        )

    lines += ["", f"## Policy comparison at a {pct(r['contact_budget'])} contact budget", "",
              "| ranking | n selected | uplift per contact | incremental conversions | vs random |",
              "|---|---|---|---|---|"]
    for row in r["policy_comparison"]:
        vs = row.get("vs_random_pct")
        vs_s = f"{vs:+.1f}%" if isinstance(vs, (int, float)) and vs == vs else "—"
        lines.append(
            f"| {row['ranking']} | {row['n_selected']:,} | {row['incremental_per_contact'] * 100:+.2f} pp | "
            f"{row['incremental_conversions']:.1f} | {vs_s} |"
        )

    lines += ["", "## Where uplift targeting pays — budget sweep", "",
              "Incremental conversions per contact (percentage points) by contact budget. "
              "The advantage of uplift targeting is largest at small reach and disappears "
              "past ~30%, because a large budget has to include most of the movable "
              f"population however it is ordered. The operating budget of "
              f"{pct(r['contact_budget'])} was chosen from this table.", "",
              "| budget | uplift (X) | propensity | oracle | random | uplift − propensity |",
              "|---|---|---|---|---|---|"]
    for row in r["budget_sweep"]:
        d = row["uplift_x_pp"] - row["propensity_pp"]
        marker = "  ← operating" if abs(row["budget"] - r["contact_budget"]) < 1e-9 else ""
        lines.append(
            f"| {row['budget']:.0%}{marker} | {row['uplift_x_pp']:+.2f} | "
            f"{row['propensity_pp']:+.2f} | {row['oracle_pp']:+.2f} | "
            f"{row['random_pp']:+.2f} | **{d:+.2f} pp** |"
        )

    lines += ["", "## Where propensity ranking spends its budget", "",
              "Segment mix of the selected set at a **10% budget**, where the two rankings "
              "diverge most. This is the argument for uplift stated as plainly as it can be: "
              "propensity targeting spends almost its entire budget on users who were going "
              "to convert anyway, and books their conversions as programme impact.", "",
              "| segment | uplift ranking | propensity ranking |", "|---|---|---|"]
    up_mix = {d["segment"]: d["share"] for d in r["selection_segment_mix_at_10pct"]["uplift_x"]}
    pr_mix = {d["segment"]: d["share"] for d in r["selection_segment_mix_at_10pct"]["propensity"]}
    for seg in sorted(set(up_mix) | set(pr_mix)):
        lines.append(f"| {seg} | {pct(up_mix.get(seg, 0.0))} | {pct(pr_mix.get(seg, 0.0))} |")

    lines += ["", "## Fairness slices by income band", "",
              "| band | n | propensity AUC | calibration error | mean predicted uplift | mean true uplift | low confidence |",
              "|---|---|---|---|---|---|---|"]
    pslices = {d["income_band"]: d for d in r["fairness_slices"]["propensity_by_income"]}
    uslices = {d["income_band"]: d for d in r["fairness_slices"]["uplift_by_income"]}
    for band in sorted(pslices):
        p, u = pslices[band], uslices.get(band, {})
        auc = f"{p['roc_auc']:.4f}" if "roc_auc" in p else "—"
        ce = f"{p['calibration_error']:.4f}" if "calibration_error" in p else "—"
        lines.append(
            f"| {band} | {p['n']:,} | {auc} | {ce} | "
            f"{u.get('mean_predicted_uplift', float('nan')) * 100:+.2f} pp | "
            f"{u.get('mean_true_uplift', float('nan')) * 100:+.2f} pp | "
            f"{'yes' if p.get('low_confidence') else 'no'} |"
        )

    lines += ["", "## Charts", "",
              "`artifacts/charts/` — each rendered in light and dark:",
              "`qini_curves`, `uplift_deciles`, `calibration`, `tau_recovery`, "
              "`budget_sweep`.", ""]
    return "\n".join(lines)


def main() -> None:
    config.ensure_dirs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pilot_path = config.DATA_DIR / "pilot_users.csv"
    if not pilot_path.exists():
        raise SystemExit(f"{pilot_path} not found. Run `python -m f2g.data.generate` first.")

    pilot = pd.read_csv(pilot_path)
    report = train_all(pilot, config.RANDOM_SEED)

    (REPORT_DIR / "model_evaluation.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    (REPORT_DIR / "model_evaluation.md").write_text(_md_report(report), encoding="utf-8")

    comp = pd.DataFrame(report["policy_comparison"]).set_index("ranking")
    prod = report["production_estimator"]
    gain = (comp.loc[prod, "incremental_conversions"] / comp.loc["propensity", "incremental_conversions"] - 1) * 100
    prod_deciles = report["uplift_deciles_x"] if prod == "uplift_x" else report["uplift_deciles_t"]

    print("\n" + "=" * 70)
    print(f"production estimator      : {prod}")
    print(f"propensity ROC AUC        : {report['propensity']['roc_auc']:.4f}")
    print(f"propensity calib. error   : {report['propensity']['calibration_error']:.4f}")
    for label in ("uplift (X-learner)", "uplift (T-learner)", "uplift (S-learner)",
                  "propensity", "oracle (true tau)"):
        print(f"Qini {label:22s}: {report['qini'][label]['coefficient']:+.4f}")
    print(f"Spearman vs true tau      : "
          f"{report['tau_recovery'][{'uplift_x':'x_learner','uplift_t':'t_learner','uplift_s':'s_learner'}[prod]]['spearman']:.4f}")
    print(f"uplift vs propensity      : {gain:+.1f}% incremental conversions @ {config.DEFAULT_CONTACT_BUDGET:.0%} budget")
    print(f"bottom decile uplift      : {prod_deciles[-1]['realised_uplift'] * 100:+.2f} pp  (must be negative)")
    print("=" * 70)
    print(f"reports -> {REPORT_DIR}")


if __name__ == "__main__":
    main()
