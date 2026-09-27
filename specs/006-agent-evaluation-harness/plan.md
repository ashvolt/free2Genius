# Implementation Plan: Agent Evaluation Harness

**Feature**: `006` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/006-agent-evaluation-harness.md)** · **[LLD](../../docs/architecture/lld/006-agent-evaluation-harness.md)**

## Summary

Thirty golden cases selected by criteria, run through the agent, scored by deterministic checks
that gate the build and an LLM judge that does not, with a comparison across providers.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: the 004 runtime and the 005 agent
**Storage**: `artifacts/evals/latest.json`, `baseline.json`, per-provider comparisons
**Testing**: pytest — coverage contract, gate behaviour, scope policy, judge calibration
**Performance**: the full suite on the deterministic provider in under a second; under 10 minutes
on the fast tier, keeping it viable as a per-commit gate
**Constraints**: must run offline; must exit non-zero on a safety failure

## Constitution Check

| Principle | Satisfied by |
|---|---|
| IV. Guardrails as code | The gate is the enforcement mechanism for Principle I |
| V. Goal metric with counter-metric | Helpfulness is judged against the deterministic floor as a control arm |
| II. Local-first | Zero marginal cost is what makes an absolute rather than sampled gate affordable |
| VI. Reproducible | Cases selected deterministically; temperature zero; seeded |

**Result**: Pass.

## Technical approach

Cases declare a **property** and the builder finds a matching user, so the set survives a seed
change by finding different users with the same property. Hard-coded ids would let the set
silently stop covering what it claims to.

The judge is grammar-constrained and its failures are recorded as unavailable rather than
coerced into a score. Judge-versus-ledger disagreement is reported as a finding about the judge.

## Project Structure

```text
f2g/evals/cases.py     criteria-driven construction
f2g/evals/judge.py     rubric, grammar, calibration disagreement
f2g/evals/harness.py   execution, metrics, gate
f2g/evals/run.py       CLI and exit codes
tests/test_evals.py
```

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Criteria-driven selection | Case sets must not silently stop covering their categories | Hardcoded ids break on a seed change, or worse, keep passing while testing nothing |
| Two tiers with different authority | Safety is absolute; quality is relative | Letting the judge gate makes a model's opinion a release blocker |
| A live provider comparison | "Why this model?" deserves evidence | Asserting a tier is good enough is unfalsifiable |
