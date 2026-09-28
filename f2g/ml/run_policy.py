"""Run the targeting policy and evaluate it off-policy.

Run: `python -m f2g.ml.run_policy`

Two halves:

1. **Decide** — score the live cohort, apply the policy, write a contact list
   and a suppression log where every excluded user has a reason and the figures
   behind it.
2. **Evaluate** — on the *pilot* cohort, where outcomes are observed, estimate
   what several candidate policies would have achieved, and check the
   doubly-robust interval against the oracle value.

The second half is what justifies going to an A/B test rather than replacing
it. Arriving at an experiment with no prior estimate wastes a cycle.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from f2g import config
from f2g.ml import ope
from f2g.ml.policy import PolicyConfig, Reason, estimate_value_fit_vectorized, select
from f2g.ml.registry import ModelBundle
from f2g.ml.train import CHART_DIR, REPORT_DIR, split_pilot


def _load_models():
    prop = ModelBundle.load("propensity").estimator
    uplift = ModelBundle.load("uplift_x").estimator
    return prop, uplift


def decide_for_live(cfg: PolicyConfig) -> dict[str, Any]:
    live = pd.read_csv(config.DATA_DIR / "live_users.csv")
    prop_model, uplift_model = _load_models()

    tau = uplift_model.predict_uplift(live)
    p = prop_model.predict_proba(live)
    value_fit = estimate_value_fit_vectorized(live)

    gated = select(live, tau, p, cfg, value_fit=value_fit)

    ungated_cfg = PolicyConfig(**{**cfg.to_dict(), "value_fit_enabled": False})
    ungated = select(live, tau, p, ungated_cfg, value_fit=value_fit)

    out_dir = config.ARTIFACT_DIR / "policy"
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = [
        "user_id", "segment", "income_band", "uplift", "propensity",
        "estimated_saving_90d", "genius_cost_90d", "net_position_90d",
        "decision", "reason_detail",
    ]
    gated.decisions[cols].to_csv(out_dir / "decision_log.csv", index=False)
    gated.selected[cols].to_csv(out_dir / "contact_list.csv", index=False)
    gated.fairness.to_csv(out_dir / "fairness_by_income.csv", index=False)

    only_ungated = set(ungated.selected.user_id) - set(gated.selected.user_id)
    cost_of_gate = ungated.decisions[ungated.decisions.user_id.isin(only_ungated)]

    return {
        "config": cfg.to_dict(),
        "summary": gated.summary,
        "fairness": gated.fairness.to_dict("records"),
        "gate_cost": {
            "users_suppressed_by_gate": len(only_ungated),
            "expected_conversions_forgone": float(cost_of_gate["uplift"].sum()),
            "mean_saving_of_suppressed": float(
                cost_of_gate["estimated_saving_90d"].mean()
            ) if len(cost_of_gate) else 0.0,
            "mean_saving_selected_gated": gated.summary["mean_saving_selected"],
            "mean_saving_selected_ungated": float(
                ungated.selected["estimated_saving_90d"].mean()
            ) if len(ungated.selected) else 0.0,
        },
        "selected_segment_mix": gated.selected.segment.value_counts(normalize=True).to_dict(),
    }


def evaluate_candidates(cfg: PolicyConfig) -> dict[str, Any]:
    """Off-policy value of several candidate policies on the pilot cohort."""
    pilot = pd.read_csv(config.DATA_DIR / "pilot_users.csv")
    _, _, test = split_pilot(pilot, config.RANDOM_SEED)

    prop_model, uplift_model = _load_models()
    tau = uplift_model.predict_uplift(test)
    p = prop_model.predict_proba(test)
    mu0 = uplift_model.predict_proba_control(test)
    mu1 = uplift_model.predict_proba_treated(test)
    value_fit = estimate_value_fit_vectorized(test)

    n_budget = int(round(cfg.contact_budget * len(test)))

    def top_k(score: np.ndarray) -> np.ndarray:
        pi = np.zeros(len(test), dtype=int)
        pi[np.argsort(-score, kind="stable")[:n_budget]] = 1
        return pi

    gated = select(test, tau, p, cfg, value_fit=value_fit)
    pi_gated = (gated.decisions.decision == Reason.SELECTED).astype(int).to_numpy()

    policies = {
        "uplift + value-fit gate": pi_gated,
        "uplift, no gate": top_k(tau),
        "propensity": top_k(p),
        "contact everyone": np.ones(len(test), dtype=int),
        "contact nobody": np.zeros(len(test), dtype=int),
    }

    rows = []
    for name, pi in policies.items():
        table = ope.evaluate_policy(test, pi, mu0, mu1,
                                    treatment_propensity=config.PILOT_TREATMENT_SHARE)
        for r in table.to_dict("records"):
            r["policy"] = name
            r["contacted"] = int(pi.sum())
            rows.append(r)
    frame = pd.DataFrame(rows)

    validation = {
        name: ope.oracle_within_interval(
            frame[frame.policy == name].drop(columns=["policy"]), "DR"
        )
        for name in policies
    }
    return {"estimates": frame.to_dict("records"), "dr_covers_oracle": validation,
            "n_test": len(test), "budget_slots": n_budget}


def _report(decide: dict[str, Any], evaluate: dict[str, Any], cfg: PolicyConfig) -> str:
    s = decide["summary"]
    gate = decide["gate_cost"]
    est = pd.DataFrame(evaluate["estimates"])
    dr = est[est.estimator == "DR"].set_index("policy")
    oracle = est[est.estimator == "oracle"].set_index("policy")

    lines = [
        "# Targeting Policy Report",
        "",
        "> Synthetic data — generated by `f2g/data/generate.py`. Not Albert data.",
        "",
        f"Contact budget {cfg.contact_budget:.0%} · value-fit gate "
        f"{'on' if cfg.value_fit_enabled else 'off'} · margin {cfg.value_fit_margin:.2f}",
        "",
        "## Decision summary (live cohort)",
        "",
        "| | |",
        "|---|---|",
        f"| candidates | {s['candidates']:,} |",
        f"| selected for contact | {s['selected']:,} |",
        f"| budget slots | {s['budget_slots']:,} |",
        f"| budget used | {s['budget_used']:.1%} |",
        f"| **binding constraint** | **{s['binding_constraint']}** |",
        f"| expected incremental conversions | {s['expected_incremental_conversions']:.1f} |",
        f"| mean predicted uplift of selected | {s['mean_uplift_selected'] * 100:.2f} pp |",
        f"| mean estimated 90-day saving of selected | ${s['mean_saving_selected']:.2f} |",
        "",
        "### Why users were suppressed",
        "",
        "| reason | users |",
        "|---|---|",
    ]
    for reason, n in sorted(s["suppressed_by_reason"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {reason} | {n:,} |")

    lines += [
        "",
        "## What the value-fit gate costs, and buys",
        "",
        "The gate suppresses users the uplift model would happily contact. That is the "
        "trade it exists to make, so both sides are stated.",
        "",
        "| | |",
        "|---|---|",
        f"| users suppressed by the gate alone | {gate['users_suppressed_by_gate']:,} |",
        f"| expected conversions forgone | {gate['expected_conversions_forgone']:.1f} |",
        f"| mean estimated saving of those suppressed | ${gate['mean_saving_of_suppressed']:.2f} |",
        f"| mean saving of selected, gate **on** | ${gate['mean_saving_selected_gated']:.2f} |",
        f"| mean saving of selected, gate **off** | ${gate['mean_saving_selected_ungated']:.2f} |",
        "",
        "## Offline policy evaluation (pilot cohort)",
        "",
        f"Doubly-robust estimates on {evaluate['n_test']:,} held-out pilot users. The oracle "
        "column is computed from the known true effect and is not an estimator — it is how "
        "the estimators themselves are validated.",
        "",
        "| policy | contacted | DR value | 95% CI | oracle | DR covers oracle |",
        "|---|---|---|---|---|---|",
    ]
    for policy in dr.index:
        d = dr.loc[policy]
        o = oracle.loc[policy] if policy in oracle.index else None
        covers = evaluate["dr_covers_oracle"].get(policy)
        lines.append(
            f"| {policy} | {int(d['contacted']):,} | {d['value']:.4f} | "
            f"[{d['ci_low']:.4f}, {d['ci_high']:.4f}] | "
            f"{o['value']:.4f} | {'yes' if covers else 'no'} |"
        )

    lines += [
        "",
        "## Fairness by income band",
        "",
        "`eligible rate` is the share with positive predicted uplift — a property of the "
        "population. `contact rate` is what the policy did. Reporting both separates a gap "
        "we inherited from a gap we created.",
        "",
        "| band | n | eligible rate | contact rate | mean uplift | mean saving | low confidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in decide["fairness"]:
        lines.append(
            f"| {row['income_band']} | {row['n']:,} | {row['eligible_rate']:.3f} | "
            f"{row['contact_rate']:.3f} | {row['mean_uplift'] * 100:+.2f} pp | "
            f"${row['mean_estimated_saving']:.2f} | "
            f"{'yes' if row['low_confidence'] else 'no'} |"
        )
    lines += [
        "",
        f"Contact-rate gap **{s['contact_rate_gap']:.3f}** against a tolerance of "
        f"{cfg.parity_tolerance:.3f} — "
        f"{'**FLAGGED**' if s['fairness_flag'] else 'within tolerance'}. "
        f"Eligible-rate gap {s['eligible_rate_gap']:.3f}.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    config.ensure_dirs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = PolicyConfig()

    print("deciding on the live cohort…")
    decide = decide_for_live(cfg)
    print("evaluating candidate policies off-policy…")
    evaluate = evaluate_candidates(cfg)

    payload = {"config": cfg.to_dict(), "decide": decide, "evaluate": evaluate}
    (REPORT_DIR / "policy_report.json").write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    (REPORT_DIR / "policy_report.md").write_text(_report(decide, evaluate, cfg), encoding="utf-8")

    from f2g.ml import charts

    charts.policy_value_chart(pd.DataFrame(evaluate["estimates"]), CHART_DIR)
    charts.suppression_chart(decide["summary"]["suppressed_by_reason"],
                             decide["summary"]["selected"], CHART_DIR)

    s = decide["summary"]
    print("\n" + "=" * 70)
    print(f"selected              : {s['selected']:,} / {s['candidates']:,} candidates")
    print(f"binding constraint    : {s['binding_constraint']}")
    print(f"suppressed            : {s['suppressed_by_reason']}")
    print(f"gate cost             : {decide['gate_cost']['users_suppressed_by_gate']:,} users, "
          f"{decide['gate_cost']['expected_conversions_forgone']:.1f} expected conversions")
    print(f"mean saving selected  : ${s['mean_saving_selected']:.2f} "
          f"(gate off: ${decide['gate_cost']['mean_saving_selected_ungated']:.2f})")
    print(f"contact-rate gap      : {s['contact_rate_gap']:.3f} "
          f"({'FLAGGED' if s['fairness_flag'] else 'ok'})")
    print(f"DR covers oracle      : {evaluate['dr_covers_oracle']}")
    print("=" * 70)
    print(f"reports -> {REPORT_DIR}")


if __name__ == "__main__":
    main()
