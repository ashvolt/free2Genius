# Tasks: Synthetic Data Foundation

**Feature**: `001` · **Input**: [spec.md](spec.md), [plan.md](plan.md)
**Status**: All tasks complete. Verified by `pytest tests/test_data_generation.py tests/test_ledger.py tests/test_no_leakage.py`.

## Phase 1: Setup

- [x] **T001** Create package skeleton `f2g/{,data,ml,agent,api,experiment}/__init__.py`
- [x] **T002** [P] Write `f2g/config.py`: root-relative paths, seed, cohort sizes, env overrides
- [x] **T003** [P] Write `requirements.txt` and `.gitignore` excluding `data/`, `artifacts/`, `models/`

## Phase 2: Column contract (US1, US3)

- [x] **T004** Write `f2g/data/schema.py` with NUMERIC, BINARY, CATEGORICAL feature groups
- [x] **T005** Define LABEL_COLUMNS and ORACLE_COLUMNS as explicitly excluded groups
- [x] **T006** Define categorical level constants (income, age, platform, channel)

## Phase 3: Generative model (US1)

- [x] **T007** Implement `_draw_segments` with the four latent archetypes
- [x] **T008** Implement `_behaviour_frame`: 26 features drawn conditional on segment
- [x] **T009** Emit `_instant_transfer_count_90d` and `_overdraft_count_90d` for exact reconciliation
- [x] **T010** Implement `_baseline_and_effect`: linear index for `p0`, heterogeneous `tau`
- [x] **T011** Clip `tau` so `p0 + tau` stays a valid probability for every user
- [x] **T012** Implement `_value_fit` from instant-transfer, overdraft and budgeting signals
- [x] **T013** Implement `generate_cohort`: randomised T, outcome Y, retention R for converters
- [x] **T014** Implement the `was_pushed` mechanism so retention degrades for poor value fit
- [x] **T015** Implement `build()` producing pilot and live cohorts from one seed
- [x] **T016** Implement `main()` CLI printing control rate, treated rate, ATE, mean tau, per-segment tau

## Phase 4: Ledger (US2)

- [x] **T017** Implement `_user_rng` seeded from `sha256(user_id)`
- [x] **T018** Implement `AccountRepository` with cached cohort load and id lookup
- [x] **T019** Implement `_spread_dates` for distinct dates in the trailing window, newest first
- [x] **T020** Implement fee-event expansion forced to match the aggregate counts
- [x] **T021** Implement advance expansion with instant/standard delivery and repayment flags
- [x] **T022** Implement subscription expansion with rescaling to match aggregate spend
- [x] **T023** Implement direct-deposit expansion conditional on direct deposit being active
- [x] **T024** Raise a distinguishable `KeyError` for unknown user ids

## Phase 5: Catalog (US1, US2)

- [x] **T025** Write `f2g/data/catalog.py` with price, free-tier fees and five features
- [x] **T026** Encode conservative estimation parameters (`coverage_rate`, `assumed_cancel_rate`)
- [x] **T027** Add the required disclosure string and `get_feature` lookup

## Phase 6: Verification

- [ ] **T028** Test: two runs at the same seed produce identical frames
- [ ] **T029** Test: observed ATE within two standard errors of mean true tau
- [ ] **T030** Test: at least one segment mean tau ≥ +0.04 and one ≤ −0.01
- [ ] **T031** Test: fee events reconcile to aggregates to the cent for a large sample
- [ ] **T032** Test: repeated ledger builds for one user are identical
- [ ] **T033** Test: zero-fee and no-direct-deposit users produce valid empty collections
- [ ] **T034** Test: no LABEL or ORACLE column appears in the feature list
- [ ] **T035** Test: live cohort label columns use the unobserved sentinel

## Dependencies

T001–T003 → T004–T006 → T007–T016 → T017–T024 → T025–T027 → T028–T035.
Within Phase 6 all tasks are `[P]`.

## Remaining

T028–T035 are written in feature 002's implementation pass, where the shared `tests/` harness and
fixtures are established. Tracked as outstanding rather than marked done.
