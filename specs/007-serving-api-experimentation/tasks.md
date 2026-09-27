# Tasks: Serving API & Experimentation Platform

**Feature**: `007` · **Status**: Complete · **Verify**: `pytest tests/test_api.py tests/test_experiment.py -q`

## Phase 1: Store (US3)
- [x] **T001** Schema: assignments, events, decisions, generations
- [x] **T002** Indexes on the query paths
- [x] **T003** `INSERT OR IGNORE` idempotency for assignments and events
- [x] **T004** Reject events from unassigned users
- [x] **T005** `explain()` — the audit answer for one user
- [x] **T006** [P] Tests: idempotency, rejection, stability

## Phase 2: Assignment (US2)
- [x] **T007** `sha256(experiment_id:user_id)` bucketing, salted by experiment
- [x] **T008** Three-arm default with share validation
- [x] **T009** [P] Tests: stability, proportions, independence across experiments

## Phase 3: Analysis (US4)
- [x] **T010** Arm statistics and pooled standard error
- [x] **T011** Fixed-horizon interval and p-value
- [x] **T012** `sequential_z` — a time-uniform critical value
- [x] **T013** Fixed-horizon and sequential sample size with the stated premium
- [x] **T014** Stopping rules with **harm checked first**
- [x] **T015** `false_positive_simulation` to verify coverage rather than assert it
- [x] **T016** [P] Tests: null simulation, rule ordering, futility at the horizon

## Phase 4: Service (US1, US5)
- [x] **T017** `ScoringService` and cohort cache loaded once
- [x] **T018** Nudge cache keyed on user + provider + **prompt version**
- [x] **T019** Typed schemas for every endpoint
- [x] **T020** Lifespan startup that fails loudly on missing artifacts
- [x] **T021** Health reporting per subsystem, including provider egress
- [x] **T022** Audit and telemetry endpoints
- [x] **T023** [P] Integration tests for every endpoint

## Phase 5: Demo data
- [x] **T024** `seed_experiment.py` replaying pilot outcomes through the live pipeline
- [x] **T025** Bulk `executemany` load

## Phase 6: Corrections from measurement
- [x] **T026** `counts()` rewritten from a cross-product join to two indexed aggregations: >10 min → 125 ms
- [x] **T027** Test database isolated via `F2G_DB_PATH`, after the suite polluted demo state

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 assignment stability | 100 calls | stable | pass |
| SC-002 arm proportions | ±1 pp at 10k | within | pass |
| SC-003 scoring p95 | < 50 ms | met warm | pass |
| SC-005 duplicate events | never counted twice | never | pass |
| SC-006 sequential vs naive FPR | ≤ 0.07 vs > 0.20 | 0.03 vs 0.49 | pass |
| SC-008 endpoint coverage | every endpoint | every endpoint | pass |
