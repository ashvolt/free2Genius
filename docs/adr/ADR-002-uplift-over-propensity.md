# ADR-002 — Uplift as the targeting signal, propensity as a diagnostic

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: B (Decision Intelligence)

## Context

The obvious build is a propensity model: predict `P(converts)` and contact the top
decile. It is easy to train, easy to explain, and scores a high AUC.

It is also the wrong objective. `P(converts)` is dominated by users who were going to
convert anyway. Ranking by it spends the contact budget on conversions we would have
received for free, and reports the resulting conversions as programme impact.

Worse, some users respond *negatively* to contact. In our population these are the
fee-stressed, high-support-contact users whose uplift is around **−2.2 percentage
points**. A propensity model has no way to express "do not contact"; it only knows
"less likely".

## Decision

**The targeting signal is estimated uplift** — the conditional average treatment effect
τ(x) = E[Y|X=x, T=1] − E[Y|X=x, T=0] — learned from a randomized pilot cohort.

Primary estimator: **T-learner** (separate LightGBM models on treated and control arms,
τ̂ = difference of predictions). An **S-learner** is trained as a reference point.

The propensity model is still built and still shipped, in two roles: a diagnostic
baseline that proves uplift ranking beats it, and a feature in explanation surfaces.
It never decides who gets contacted.

## Consequences

**Gained**

- The policy can *withhold* contact, which is a capability propensity ranking does not
  have. Do-no-harm becomes expressible.
- Measured programme impact is incremental by construction, so the number reported to
  the business is the number the business actually gained.
- The propensity-vs-uplift comparison is a built-in demonstration of why the harder
  approach was worth it, quantified on the same data.

**Paid**

- Requires randomized historical data. Our synthetic pilot provides it; a real programme
  would need a holdout from day one. This is a genuine organizational prerequisite and is
  called out in the rollout plan, not glossed over.
- Uplift is a noisier target than conversion: it is a difference of two estimates, so
  variance roughly doubles. AUC is meaningless for it; evaluation uses Qini and decile
  uplift instead ([003](../../specs/003-targeting-policy-engine/spec.md)).
- No per-user ground truth exists to validate against in production — we only ever
  observe one arm per user. Synthetic data is what lets us check the estimator against a
  known τ, which is precisely why the data foundation was built first.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Propensity only | Cannot express harm; measures credit rather than impact |
| X-learner / R-learner / causal forest | Better variance properties, meaningfully more machinery. Revisit once T-learner Qini plateaus — recorded as future work rather than adopted speculatively |
| Two-model class transformation | Equivalent in expectation to the T-learner here, less interpretable per-arm |
| Direct policy learning | Optimizes the decision end-to-end but yields no per-user effect estimate, and the effect estimate is what the honesty gate in [ADR-004](ADR-004-value-fit-gate.md) needs |
