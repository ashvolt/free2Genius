# Tasks: Observability, Cost Control & AI Governance

**Feature**: `009` · **Status**: Complete · **Verify**: `pytest tests/test_governance.py -q`

## Phase 1: Audit capture (US1)
- [x] **T001** `decisions` table written at decision time with model and prompt versions
- [x] **T002** `generations` table with tool calls, evidence and per-check verdicts
- [x] **T003** `explain(user_id)` returning the complete record
- [x] **T004** `GET /audit/{user_id}`
- [x] **T005** [P] Test: the record exists and is complete

## Phase 2: Fairness (US2)
- [x] **T006** Per-band contact, conversion, uplift and saving
- [x] **T007** `eligible_rate` separating population gaps from policy-induced ones
- [x] **T008** Low-confidence marking rather than dropping small bands
- [x] **T009** Per-band model discrimination and calibration in the training report
- [x] **T010** Tolerance flag surfaced in the run output, not only in a file

## Phase 3: Telemetry (US3)
- [x] **T011** Latency percentiles, tokens, providers, prompt versions
- [x] **T012** Repair attempts and degradation reasons, bucketed
- [x] **T013** Block rate **by check**, with a threshold flag
- [x] **T014** `GET /telemetry`
- [x] **T015** [P] Tests: shape, high-block-rate flag

## Phase 4: Governance artifacts (US4)
- [x] **T016** Model card **generated** from evaluation artifacts
- [x] **T017** Staleness test stripping only the generated-on date
- [x] **T018** `ArtifactsMissing` naming the pipeline command
- [x] **T019** Risk register — 14 risks, each with a control or an acceptance
- [x] **T020** Structural test enforcing that shape
- [x] **T021** Consent and data-use note
- [x] **T022** [P] Tests: required sections, controls cite real files, synthetic provenance stated

## Phase 5: What the tests caught
- [x] **T023** Register had no risk for out-of-scope advice despite a control existing → R7a added

## Outstanding
- [ ] **T024** Retention policy on stored generations and decisions — named as a gap in the consent note
- [ ] **T025** Deletion path for a user's records — required for a real rights response

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 decision-log coverage | 100% | 100% | pass |
| SC-002 decision reconstructable from the log | yes | yes | pass |
| SC-004 card matches current output | yes | asserted by test | pass |
| SC-005 every risk has a control or acceptance | yes | asserted by test | pass |
| SC-006 latency and block rate per provider | yes | yes | pass |
