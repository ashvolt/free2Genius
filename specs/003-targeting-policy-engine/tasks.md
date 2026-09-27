# Tasks: Targeting Policy Engine & Offline Policy Evaluation

**Feature**: `003` · **Status**: Complete · **Verify**: `python -m f2g.ml.run_policy && pytest tests/test_policy.py tests/test_ope.py -q`

## Phase 1: Value fit (US2)
- [x] **T001** `PolicyConfig` with budget, margin, gate toggle, parity settings
- [x] **T002** `estimate_value_fit` — reference path through `ConciergeTools`
- [x] **T003** `estimate_value_fit_vectorized` — batch path from aggregate columns
- [x] **T004** Declare `VECTORISED_FEATURES` so the equivalence test compares like with like
- [x] **T005** [P] Test: both paths agree to the cent on 60 users

## Phase 2: Selection (US1, US2)
- [x] **T006** Exclude non-positive uplift unconditionally
- [x] **T007** Apply the value-fit gate **before** the budget so the log records the true reason
- [x] **T008** Treat missing account data as failing the gate, not passing by default
- [x] **T009** Rank by uplift, break ties by `user_id`, apply the budget
- [x] **T010** Report which constraint actually bound
- [x] **T011** Record `backfilled_by_gate` — users admitted into slots the gate freed
- [x] **T012** [P] Tests: positivity, budget, determinism, empty-eligible, zero budget

## Phase 3: Fairness (US3)
- [x] **T013** Per-band contact rate, mean uplift, mean saving
- [x] **T014** Add `eligible_rate` to separate population gaps from policy-induced ones
- [x] **T015** Mark bands below the minimum count as low-confidence rather than dropping them
- [x] **T016** Optional parity cap
- [x] **T017** [P] Tests: table shape, parity reduces the gap

## Phase 4: Offline policy evaluation (US4)
- [x] **T018** IPS with weight clipping and a reported clipped fraction
- [x] **T019** SNIPS
- [x] **T020** Doubly robust using the X-learner's existing arm models
- [x] **T021** Oracle value from the known true effect
- [x] **T022** Bootstrap intervals; `oracle_within_interval` to validate the estimator
- [x] **T023** [P] Tests: DR covers the oracle, policies rank correctly, clipping is visible

## Phase 5: Orchestration
- [x] **T024** `run_policy` — decide on live, evaluate candidates on pilot
- [x] **T025** Decision log, contact list and fairness CSVs
- [x] **T026** Report both sides of the gate's cost
- [x] **T027** `policy_value` and `policy_suppression` charts

## Phase 6: Corrections from measurement
- [x] **T028** Parity cap corrected from an equal-count to an equal-**rate** cap (gap 0.064 → within tolerance)
- [x] **T029** Corrected the spec's superset invariant; the gate backfills rather than shrinking

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 non-positive uplift contacted | 0 | 0 | pass |
| SC-002 decisions with a reason | 100% | 100% | pass |
| SC-003 mean value fit uplift from the gate | ≥ +30% | +102% ($34.75 → $70.21) | pass |
| SC-004 DR interval covers the oracle | yes | yes, all 5 policies | pass |
| SC-006 selection time | < 30 s | ~6 s | pass |
| SC-007 fairness gap reported | every run | 0.021 vs 0.10 tolerance | pass |
| SC-008 repeat runs identical | yes | yes | pass |
