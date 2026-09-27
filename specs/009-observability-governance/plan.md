# Implementation Plan: Observability Governance

**Feature**: `009` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/009-observability-governance.md)** · **[LLD](../../docs/architecture/lld/009-observability-governance.md)**

## Summary

Capture a complete decision and generation record at decision time, derive audit, telemetry and
fairness views from it, and generate the model card from evaluation output so it cannot go stale.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: SQLite, NumPy
**Storage**: `decisions` and `generations` tables; markdown under `docs/governance/`
**Testing**: pytest — card staleness, register structure, telemetry shape
**Constraints**: 100% decision-log coverage; no sampling

## Constitution Check

| Principle | Satisfied by |
|---|---|
| VI. Reproducible | The card regenerates from artifacts; a test asserts the committed copy matches |
| V. Goal metric with counter-metric | Fairness separates population gaps from policy-induced ones |
| IV. Guardrails as code | Register structure is enforced by test, which caught a missing risk |
| VIII. Synthetic data stated | Asserted for every governance document |

**Result**: Pass.

## Technical approach

The card is generated, not written. Its inputs are the JSON artifacts the pipeline produces, and
the staleness test strips only the generated-on date before comparing — so everything
substantive must match or the build fails.

The risk register is prose, but its *structure* is testable: every risk must name a control or
an explicit acceptance, and controls must cite real files.

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Generated model card | Hand-maintained cards drift silently | A written card is true once and nothing checks it afterwards |
| Structural test over prose | A register of hand-waved mitigations is worse than none | Review catches this only if someone reviews it |
| Cost on one axis for both provider types | Otherwise the comparison flatters whichever is being defended | Reporting only tokens hides local compute cost entirely |
