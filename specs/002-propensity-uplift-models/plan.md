# Implementation Plan: Propensity & Uplift Models

**Feature**: `002` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

## Summary

One shared feature pipeline; a propensity model trained on the control arm; three uplift
meta-learners (S, T, X) scored against each other and against an oracle built from the known
true effect; a model registry that makes the training/serving feature contract checkable;
and an evaluation suite that reports Qini, decile uplift, ground-truth recovery, a contact-
budget sweep, and income-band slices.

The production estimator is **chosen by measured Qini at training time**, not hard-coded.
That single decision is what let the codebase correct itself when the first estimator turned
out to rank worse than the baseline it was meant to beat.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: LightGBM 4.x, scikit-learn (metrics and splitting), SciPy (rank
correlation), pandas, NumPy, joblib, matplotlib
**Storage**: `artifacts/models/*.joblib` + `.meta.json` sidecars; `artifacts/reports/`;
`artifacts/charts/`
**Testing**: pytest — leakage, contract, reload determinism, metric correctness against
analytically-known cases
**Target Platform**: Linux / macOS, 4 cores, no GPU
**Project Type**: Library plus CLI entry point
**Performance Goals**: full training under 5 minutes on 4 cores (measured: ~90 s)
**Constraints**: deterministic; no network; artifacts regenerable from a clean checkout
**Scale/Scope**: 60,000 pilot users, 26 features, 5 fitted models plus one ablation

## Constitution Check

| Principle | How this feature satisfies it |
|---|---|
| III. Uplift over propensity | Uplift is the targeting signal; propensity is kept as a scored baseline and a diagnostic, never as the decision |
| V. Goal metric with counter-metric | Every model metric is also reported per income band; the oracle ceiling prevents a good-looking absolute number from passing as good |
| VI. Reproducible by default | Seeded split, `deterministic=True` in LightGBM, data fingerprint on every bundle, reload-equality test |
| IV. Guardrails as code | Leakage exclusion, feature-contract mismatch and degenerate-arm refusal are all raised exceptions with tests, not conventions |
| VII. Spec-driven | Requirements added during implementation (FR-005a–d, FR-007a–c) were written back into the spec with the reason |

**Result**: Pass.

## Technical approach

### Why the propensity model trains on the control arm only

Fitted on the pooled population it would absorb the average treatment effect and become a
blend of "will convert" and "was contacted". That is fine for a scoring service and fatal
for a baseline: the comparison in the evaluation would already contain part of the answer.

### Why three meta-learners

They fail differently, and only measurement reveals which failure is active on a given
dataset:

| estimator | mechanism | characteristic failure |
|---|---|---|
| S-learner | one model, treatment as a feature | boosting ignores one weak binary feature among 26; τ̂ collapses toward 0 while outcome accuracy stays excellent — invisible if you only look at AUC |
| T-learner | one model per arm, τ̂ = difference | variance: two independent fits subtracted, errors compound; over-dispersed τ̂ |
| X-learner | regress *imputed* effects, combine by treatment propensity | needs the treatment propensity; more moving parts |

### The split

Three-way, stratified on the **(arm, outcome) interaction** rather than the outcome alone.
Stratifying on outcome alone lets a chance imbalance in the control arm move the uplift
estimate more than any modelling choice would. Early stopping uses `valid`; `test` is not
touched until the models are frozen.

### Hyperparameters are not one set

Outcome models and uplift arm models need different settings, and conflating them is what
broke the first implementation:

```text
BASE_PARAMS         leaves 31, min_child 60,  lr 0.045, L2 1    -> fitting a ~15% outcome
UPLIFT_ARM_PARAMS   leaves  8, min_child 300, lr 0.030, L2 20   -> resolving a 1-8 pp effect
XLEARNER_STAGE2     leaves  8, min_child 400, lr 0.030, L2 30   -> regressing imputed effects
```

Stage-2 models are regularised hardest because their target is itself an estimate.

### Metric discipline

AUC is never reported for an uplift model. τ is unobservable per user, so ranking quality is
Qini plus realised decile uplift — both of which compare arms *within* score strata. An AUC
against a label that is not the target is a reassuring number about the wrong thing.

## Project Structure

```text
f2g/
├── viz.py                  # validated palette, style, label de-collision
└── ml/
    ├── features.py         # FeaturePipeline, leakage guard, contract validation
    ├── models.py           # PropensityModel, SLearner, TLearner, XLearner, param sets
    ├── evaluate.py         # classification, Qini, deciles, recovery, sweep, slices
    ├── charts.py           # qini, deciles, calibration, recovery, budget sweep
    ├── registry.py         # ModelBundle, BundleMeta, data fingerprint
    └── train.py            # orchestration + report generation

tests/
├── test_no_leakage.py  test_models.py  test_evaluate.py
artifacts/
├── models/  reports/  charts/
```

**Structure Decision**: Library plus one CLI entry point. No service boundary — training is
batch, and the serving path loads bundles directly.

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three uplift estimators, not one | They fail differently and the active failure is dataset-dependent — measured here, not assumed | Shipping one estimator is exactly how the first implementation ended up worse than its own baseline |
| Live unregularised ablation | The regularisation claim is load-bearing for the design | A sentence in a document stops being true silently; a test that runs every time does not |
| Oracle ranking as a reported ceiling | Turns "Qini 0.78" into "61% of achievable" | An absolute Qini has no natural scale, so it cannot be judged |
| Separate hyperparameter sets | Outcome fitting and effect estimation are different problems at different signal scales | One shared set produced a 3x over-dispersed estimator |
