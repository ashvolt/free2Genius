# Tasks: Agent Evaluation Harness & CI Gate

**Feature**: `006` · **Status**: Complete · **Verify**: `python -m f2g.evals.run && pytest tests/test_evals.py -q`

## Phase 1: Cases (US1)
- [x] **T001** `EvalCase` declaring expected features, refusal, not-worth-it, tools, injection
- [x] **T002** Criteria-driven selection — filter, sort by id, take the first n
- [x] **T003** Cases for fee-heavy, zero-fee, below-cost, dormant and advance-heavy users
- [x] **T004** Probe sets: 5 advice, 4 injection, 2 off-topic
- [x] **T005** [P] Tests: ≥30 cases, all 8 categories, determinism, every case asserts something

## Phase 2: Programmatic metrics (US1)
- [x] **T006** Grounding violations — anything ungrounded *reaching output*
- [x] **T007** Refusal detection by explicit, reviewable phrase markers
- [x] **T008** Injection resistance, including a prompt-leak check
- [x] **T009** Tool selection accuracy against each case's expected set
- [x] **T010** Forced-evidence rate — under-investigation as a number
- [x] **T011** Block, degradation and latency aggregates

## Phase 3: Judge (US4)
- [x] **T012** Five-dimension rubric graded against tool evidence, not plausibility
- [x] **T013** Grammar-constrained output, one rule per line
- [x] **T014** Unparseable output → unavailable, never coerced into a score
- [x] **T015** `calibration_disagreement` — a finding about the judge
- [x] **T016** [P] Tests: mean, unavailability, calibration flags

## Phase 4: Gate (US1, US2)
- [x] **T017** Absolute failures: grounding, injection, refusal
- [x] **T018** Advisory judge regression against a recorded baseline
- [x] **T019** Empty case set raises rather than passing
- [x] **T020** `--record-baseline` refuses to record a failing run
- [x] **T021** [P] Tests: gate fires on each absolute failure

## Phase 5: CLI and comparison (US3)
- [x] **T022** `run.py` with exit codes and a readable summary
- [x] **T023** `--compare` across deterministic, fast and quality tiers
- [x] **T024** Machine-readable report per provider

## Phase 6: What the gate caught
- [x] **T025** Refusal rate 0.00 on the first run → scope moved into the agent (feature 005, T029)

## Outcome — deterministic provider

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 grounding violation rate | 0.00 | 0.00 | pass |
| SC-002 advice refusal | ≥ 0.98 | 1.00 | pass |
| SC-003 injection resistance | 1.00 | 1.00 | pass |
| SC-004 disclosure presence | 1.00 | 1.00 | pass |
| SC-005 not-worth-it rate | ≥ 0.95 | 1.00 | pass |
| SC-007 suite runtime | < 10 min | < 1 s | pass |
| SC-008 coverage | ≥ 30 cases, 8 categories | 30, 8/8 | pass |
