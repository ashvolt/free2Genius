# Implementation Plan: Targeting Policy Engine

**Feature**: `003` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/003-targeting-policy-engine.md)** · **[LLD](../../docs/architecture/lld/003-targeting-policy-engine.md)**

## Summary

Apply four constraints in a fixed order — positivity, value fit, budget, optional parity — and
record every decision with its reason. Then estimate, on the pilot cohort where outcomes are
observed, what the resulting policy would have achieved, using estimators validated against an
oracle that only synthetic data can provide.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: NumPy, pandas, SciPy
**Storage**: CSV decision log under `artifacts/policy/`, JSON + markdown reports
**Testing**: pytest — invariants, the corrected superset invariant, path equivalence
**Performance**: selection over 12,000 candidates including value fit in under 30 s (measured ~6 s)
**Constraints**: deterministic; no model inference in the eligibility path

## Constitution Check

| Principle | Satisfied by |
|---|---|
| I. Evidence over persuasion | The value-fit gate is this principle expressed as a constraint |
| III. Uplift over propensity | Non-positive uplift excluded unconditionally; propensity never decides |
| V. Goal metric with counter-metric | Gate cost reported in both directions; fairness gap on every run |
| IV. Guardrails as code | Every invariant is a test, including ones that failed and corrected the spec |
| VI. Reproducible | Ties broken by user id; identical input produces an identical list |

**Result**: Pass.

## Technical approach

Constraint ordering is the design (see HLD). Value fit runs before the budget so the decision
log records the true reason rather than whichever constraint happened to fire first.

Two value-fit implementations exist deliberately: a per-user reference path through
`ConciergeTools` — literally what the agent will read, so the decision and the explanation
cannot disagree — and a vectorised batch path, pinned to it by test.

Offline evaluation uses three estimators because they trade bias against variance differently,
plus an oracle that validates the estimators rather than the policy.

## Project Structure

```text
f2g/ml/policy.py       PolicyConfig, select, value fit, fairness table
f2g/ml/ope.py          IPS, SNIPS, doubly robust, oracle
f2g/ml/run_policy.py   batch orchestration, reports, charts
tests/test_policy.py  tests/test_ope.py
```

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Two value-fit paths | Batch speed vs exactness against what the agent says | One path is either too slow for 12k users or diverges from the user-facing figure |
| Three OPE estimators | IPS is unbiased but high variance; SNIPS is stable; DR is the one to quote | A single estimator gives no way to notice when its assumptions fail |
| Oracle reported alongside | Validates the estimator itself | Without it, an OPE number is unfalsifiable |
