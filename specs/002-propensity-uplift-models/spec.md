# Feature Specification: Propensity & Uplift Models

**Feature ID**: `002` · **Domain**: B — Decision Intelligence
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 001
**Input**: "Predict who will convert, and separately predict whom contact actually
changes. Prove the second beats the first on the metric that matters."

## Why this feature exists

The business asks for "a model that predicts who will subscribe". Delivered literally,
that model spends the contact budget on users who were going to subscribe anyway and
reports their conversions as programme impact. It cannot express *do not contact*.

This feature therefore delivers **two** model families and a head-to-head comparison:

- a **propensity** model — `P(convert)` — as a diagnostic baseline and an explanation
  feature;
- **uplift** models — `τ̂(x)`, the conditional average treatment effect — as the signal the
  targeting policy consumes.

The deliverable is not just the models. It is the evidence that ranking by τ̂ captures more
incremental conversions per contact than ranking by propensity, on the same data, with the
ground truth available to check both. See [ADR-002](../../docs/adr/ADR-002-uplift-over-propensity.md).

## User Scenarios & Testing

### User Story 1 — A modeller trains a calibrated propensity baseline (Priority: P1)

Train `P(convert | x)` on the untreated arm and get discrimination, calibration and
feature-importance reporting.

**Why this priority**: It is the baseline every uplift claim is measured against, and it is
the model a conventional team would ship. We must be able to beat it, which means we must
first build it properly rather than as a straw man.

**Independent Test**: Train on the control arm, evaluate on a held-out split, and confirm
AUC materially exceeds 0.5 with calibration error inside tolerance. Usable on its own as a
scoring service.

**Acceptance Scenarios**:

1. **Given** the pilot control arm, **When** the propensity model is trained, **Then**
   held-out ROC AUC ≥ 0.70.
2. **Given** held-out predictions, **When** grouped into deciles, **Then** mean predicted
   probability tracks observed rate within the documented calibration tolerance.
3. **Given** a trained model, **When** it is asked to score a user, **Then** identifier,
   label and ground-truth columns are provably absent from its inputs.

### User Story 2 — A modeller trains an uplift model and recovers known τ (Priority: P1)

Train a T-learner (separate models per arm) and an S-learner (single model with treatment
as a feature), then check both against the hidden true τ.

**Why this priority**: This is the feature's reason for existing.

**Independent Test**: Correlate predicted τ̂ against true τ on held-out users. Because 001
supplies ground truth, this is a direct measurement of estimator quality — not a proxy.

**Acceptance Scenarios**:

1. **Given** a held-out split, **When** τ̂ from the T-learner is correlated with true τ,
   **Then** Spearman correlation ≥ 0.45.
2. **Given** users ranked by τ̂ and split into deciles, **When** the realised uplift of each
   decile is computed from observed outcomes, **Then** uplift decreases monotonically
   across the top five deciles.
3. **Given** the bottom decile by τ̂, **When** its realised uplift is computed, **Then** it
   is negative — the model has located the sleeping dogs.
4. **Given** both estimators, **When** their Qini coefficients are compared, **Then** both
   are reported and the better is recorded as the production estimator with a reason.

### User Story 3 — A reviewer sees uplift beat propensity, quantified (Priority: P1)

One artifact showing incremental conversions captured per contact, uplift ranking versus
propensity ranking versus random.

**Why this priority**: This is the argument. Without it, the extra complexity of uplift is
an unjustified choice.

**Independent Test**: Produce Qini curves for all three rankings on the same held-out set
and confirm the ordering uplift > propensity > random.

**Acceptance Scenarios**:

1. **Given** the held-out set at a 30% contact budget, **When** incremental conversions are
   computed for each ranking, **Then** uplift ranking captures at least 25% more than
   propensity ranking.
2. **Given** the same comparison, **When** propensity ranking is examined, **Then** the
   share of its selected users that are sure-things or sleeping dogs is reported, showing
   *where* the waste goes rather than only that it exists.

### User Story 4 — Models are reloadable and versioned (Priority: P2)

Persist models with the feature list, training metadata, metrics and data fingerprint, and
reload them for scoring without retraining.

**Why this priority**: Required before the serving API, not before evaluation.

**Independent Test**: Train, save, reload in a fresh process, score a fixed user, and get a
bit-identical prediction.

**Acceptance Scenarios**:

1. **Given** a saved bundle, **When** reloaded in a new process, **Then** predictions match
   the training-time predictions exactly.
2. **Given** a bundle whose recorded feature list disagrees with the frame presented at
   scoring time, **Then** loading fails loudly rather than scoring on misaligned columns.

### Edge Cases

- Categorical level present at scoring but unseen in training must not crash scoring.
- An arm with too few positives for a stable split must fail with a clear message rather
  than silently training a degenerate model.
- τ̂ must be permitted to be negative; no clipping at zero anywhere in the pipeline, because
  the negative region is the part we act on.
- AUC must never be reported for the uplift models. Ranking quality for τ̂ is Qini and
  decile uplift; AUC against a label that is not the target invites a misleading number.
- Users whose retention outcome is undefined (non-converters) must be excluded from
  retention modelling rather than imputed.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide one feature pipeline shared by every model and by the
  serving path, so training and serving cannot diverge.
- **FR-002**: Pipeline MUST exclude identifiers, labels, treatment assignment and all
  ground-truth columns from features, and this exclusion MUST be asserted in a test.
- **FR-003**: System MUST train a propensity model on the control arm and report held-out
  ROC AUC, PR AUC, log loss and a decile calibration table.
- **FR-004**: System MUST train a T-learner uplift estimator (one model per arm).
- **FR-005**: System MUST train an S-learner uplift estimator as a reference point.
- **FR-006**: System MUST compute, on held-out data, the Qini curve and coefficient, the
  decile uplift table, and the correlation between τ̂ and true τ.
- **FR-007**: System MUST produce a direct comparison of uplift, propensity and random
  ranking at a configurable contact budget, expressed as incremental conversions per
  contact.
- **FR-008**: System MUST persist each model with its feature list, hyperparameters,
  training-data fingerprint, metrics and library versions.
- **FR-009**: Loading a model whose feature list disagrees with the supplied frame MUST
  raise.
- **FR-010**: Training MUST be reproducible: same data and seed produce identical metrics.
- **FR-011**: System MUST report metrics sliced by income band for every model, feeding the
  fairness audit in 009.
- **FR-012**: Training MUST use early stopping on a validation split carved from training
  data only, never from the held-out test split.

### Key Entities

- **Feature matrix**: the agreed model input, with a recorded ordered column list.
- **Propensity model**: conversion-likelihood estimator trained on the control arm.
- **Uplift estimator**: τ̂ producer; T-learner in production, S-learner as reference.
- **Model bundle**: persisted estimator plus the metadata needed to serve and audit it.
- **Evaluation report**: metrics, curves and slices, written as JSON plus charts.

## Success Criteria

- **SC-001**: Propensity held-out ROC AUC ≥ 0.70.
- **SC-002**: Propensity decile calibration: mean absolute gap between predicted and
  observed ≤ 0.03.
- **SC-003**: T-learner Spearman correlation with true τ ≥ 0.45 on held-out data.
- **SC-004**: Uplift ranking captures ≥ 25% more incremental conversions than propensity
  ranking at a 30% contact budget.
- **SC-005**: Bottom τ̂ decile shows negative realised uplift.
- **SC-006**: Full training of all three models completes in under 5 minutes on 4 cores.
- **SC-007**: Reload-and-score reproduces training-time predictions exactly.
- **SC-008**: Every reported metric is also reported per income band.

## Assumptions

- The pilot's randomization is valid, so conditional exchangeability holds and τ is
  identified without adjustment for confounding. This is true by construction here and
  would require verification with real data — stated as a limitation in the model card.
- Gradient-boosted trees are sufficient; no deep model is warranted at this scale.
- A single train/test split with a validation carve-out is adequate. Cross-validated
  uplift estimation is recorded as future work rather than silently skipped.
- Class imbalance (~15% conversion) is handled by the learner's own weighting; no
  resampling, which would break calibration.
