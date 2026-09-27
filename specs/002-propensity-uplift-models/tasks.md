# Tasks: Propensity & Uplift Models

**Feature**: `002` · **Input**: [spec.md](spec.md), [plan.md](plan.md) · **Status**: Complete
**Verification**: `python -m f2g.ml.train` then `pytest tests/ -q` (46 passed)

## Phase 1: Feature contract (US1, US4)

- [x] **T001** Write `f2g/ml/features.py` with `FeaturePipeline` over the schema column groups
- [x] **T002** Declare fixed categorical levels so an unseen level becomes NaN rather than shifting codes
- [x] **T003** Raise `FeatureError` when any label/oracle column is passed as a feature
- [x] **T004** Admit `treated` only via an explicit `treatment_column` argument (S-learner only)
- [x] **T005** Implement `validate_against` so a saved model's column order is checked on load
- [x] **T006** [P] Test: features disjoint from labels and oracles
- [x] **T007** [P] Test: pipeline refuses each forbidden column individually

## Phase 2: Registry (US4)

- [x] **T008** Write `BundleMeta` capturing features, params, metrics, fingerprint, seed, versions
- [x] **T009** Implement `data_fingerprint` — shape, columns and a content sample
- [x] **T010** Implement save/load with a JSON sidecar so metadata is greppable without unpickling
- [x] **T011** Missing-bundle error names the command that creates it
- [x] **T012** [P] Test: reload reproduces training-time predictions exactly (SC-007)
- [x] **T013** [P] Test: feature-contract mismatch raises

## Phase 3: Estimators (US1, US2)

- [x] **T014** Implement `PropensityModel`, fitted on the control arm only
- [x] **T015** Implement `SLearner` with counterfactual treatment toggle
- [x] **T016** Implement `TLearner` with per-arm models and a degenerate-arm guard
- [x] **T017** Set LightGBM determinism flags so repeated runs are bit-identical
- [x] **T018** [P] Test: uplift predictions may be negative and are not clipped

## Phase 4: Evaluation (US2, US3)

- [x] **T019** Implement classification metrics and the decile calibration table
- [x] **T020** Implement `qini_curve` with arm rescaling at every prefix
- [x] **T021** Implement `uplift_decile_table` with per-arm rates inside each stratum
- [x] **T022** Implement `tau_recovery` against the known true effect
- [x] **T023** Implement `incremental_conversions_at_budget` and `policy_comparison`
- [x] **T024** Implement `segment_mix_of_selection` to show *where* budget is wasted
- [x] **T025** Implement `slice_metrics` with low-confidence marking rather than dropping
- [x] **T026** [P] Test: Qini orders oracle above random and scores an inverted ranking negative
- [x] **T027** [P] Test: calibration error near zero for honest predictions, large for biased

## Phase 5: Orchestration and reporting

- [x] **T028** Three-way split stratified on the (arm, outcome) interaction
- [x] **T029** Wire training of all estimators, persist bundles
- [x] **T030** Generate the machine-readable JSON report and the human markdown report
- [x] **T031** Implement charts against the validated palette, light and dark

## Phase 6: Correction pass — findings from the first full run

*These tasks did not exist at planning time. They were created by measurement.*

- [x] **T032** Diagnose T-learner underperformance against the propensity baseline
- [x] **T033** Add `UPLIFT_ARM_PARAMS`; confirm Qini 0.5596 → 0.7533
- [x] **T034** Implement `XLearner` (Künzel et al. 2019); confirm Qini → 0.7822
- [x] **T035** Select the production estimator by measured Qini instead of hard-coding
- [x] **T036** Add the oracle ranking as a reported ceiling
- [x] **T037** Add a live unregularised-T-learner ablation so the claim is recomputed each run
- [x] **T038** Implement `budget_sweep`; move the operating budget 30% → 20% on the evidence
- [x] **T039** Suppress ratio reporting near a zero denominator (the "−2577%" artifact)
- [x] **T040** Fix right-edge label collision; give the production estimator the prime colour slot
- [x] **T041** Write the findings back into ADR-002 and spec 002 with revised criteria
- [x] **T042** [P] Test: X-learner is less dispersed than the unregularised T-learner
- [x] **T043** [P] Test: near-zero denominator suppresses the ratio

## Dependencies

T001–T007 → T008–T013 → T014–T018 → T019–T027 → T028–T031 → T032–T043.
Phase 6 is strictly sequential from T032 to T041; T042–T043 are `[P]`.

## Outcome against success criteria

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 propensity ROC AUC | ≥ 0.70 | 0.8598 | pass |
| SC-002 calibration error | ≤ 0.03 | 0.0100 | pass |
| SC-003 Spearman vs true τ | ≥ 0.45 | 0.6330 | pass |
| SC-004 vs propensity @ operating budget | ≥ +25% | +32.9% | pass (criterion re-anchored, see spec) |
| SC-005 bottom decile uplift | negative | −2.39 pp | pass (failed at +3.07 pp before T032–T034) |
| SC-006 training time | < 5 min | ~90 s | pass |
| SC-007 reload reproduces | exact | exact | pass |
| SC-008 metrics per income band | all | all | pass |
