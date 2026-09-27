# Feature Specification: Targeting Policy Engine & Offline Policy Evaluation

**Feature ID**: `003` · **Domain**: B — Decision Intelligence
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 002 (uplift estimates), 001 (tool layer for the value-fit gate)
**Input**: "Turn a per-user uplift score into a defensible decision about who gets
contacted, under a budget, without harming anyone, and estimate what that decision would
have achieved before we ship it."

## Why this feature exists

A score is not a decision. Between `τ̂(x)` and "send this user a nudge" sit four constraints
that a threshold cannot express:

1. **Budget** — we can only contact a bounded share of users per cycle.
2. **Do no harm** — users with negative τ̂ must be actively excluded, not merely ranked low.
3. **Value fit** — a user who would be talked into a subscription that saves them nothing
   must be suppressed regardless of how movable they are
   ([ADR-004](../../docs/adr/ADR-004-value-fit-gate.md)).
4. **Fairness** — contact rates across income bands must stay inside a declared band, and
   any gap must be explained rather than discovered later.

And before any of it ships, we must be able to answer: *what would this policy have
achieved on the pilot data?* That is an off-policy question — we observe each user under
one arm only — so it needs an estimator, not a spreadsheet.

This feature is the one most likely to be missing from a comparable project, and it is
where the product judgment lives.

## User Scenarios & Testing

### User Story 1 — A growth analyst gets a ranked, budgeted contact list (Priority: P1)

Given scored live users and a contact budget, return the users to contact, ordered, with
the expected incremental conversions the list represents.

**Why this priority**: It is the feature's core output; everything else constrains it.

**Independent Test**: Run selection at a 30% budget and confirm the selected count matches
the budget, that no selected user has negative τ̂, and that expected incremental conversions
exceed those of a random list of the same size.

**Acceptance Scenarios**:

1. **Given** a budget of 30% and 12,000 candidates, **When** selection runs, **Then** at
   most 3,600 users are selected.
2. **Given** any selected user, **When** their τ̂ is read, **Then** it is strictly positive.
3. **Given** the selected list, **When** expected incremental conversions are summed,
   **Then** the total exceeds a random list of equal size by a reported margin.
4. **Given** fewer eligible users than the budget allows, **When** selection runs, **Then**
   it returns only the eligible ones and reports budget underuse rather than padding the
   list to fill quota.

### User Story 2 — A user who would not benefit is suppressed and the reason is recorded (Priority: P1)

For every candidate, the deterministic tool layer computes estimated 90-day savings and the
subscription cost over the same window. Where savings do not clear cost, the user is
suppressed — even with high τ̂ — and the decision is logged with its numbers.

**Why this priority**: It is the project's central ethical claim, and the one an interviewer
will press on. It must be a constraint with a test, not a principle in a document.

**Independent Test**: Construct a user with high τ̂ and zero fee history, run selection, and
confirm they are absent from the contact list and present in the suppression log with a
`value_fit` reason and the two figures that produced it.

**Acceptance Scenarios**:

1. **Given** a user with top-decile τ̂ and no fees, **When** selection runs, **Then** they
   are suppressed with reason `value_fit`.
2. **Given** any suppressed user, **When** their log entry is read, **Then** it contains
   estimated saving, subscription cost over the window, and the margin applied.
3. **Given** the value-fit gate is disabled by configuration, **When** selection runs,
   **Then** the selected set is a strict superset of the gated set, and the difference is
   reported — so the cost of the gate is always visible.
4. **Given** the gate is active, **When** mean value fit of selected users is compared to
   ungated selection, **Then** it is higher.

### User Story 3 — Contact rates are checked across income bands (Priority: P2)

Report contact rate, mean τ̂ and mean estimated saving per income band, and flag when the
gap between the highest and lowest contacted band exceeds a declared tolerance.

**Why this priority**: Needed before rollout, not before the first ranked list exists.

**Independent Test**: Run selection and confirm the per-band report is produced and the
flag fires when the configured tolerance is breached.

**Acceptance Scenarios**:

1. **Given** a completed selection, **When** the fairness report is generated, **Then** it
   contains contact rate per income band and the max-min gap.
2. **Given** a gap exceeding tolerance, **When** the report is generated, **Then** it is
   flagged and the affected bands are named.
3. **Given** a flagged gap, **When** the analyst requests it, **Then** a parity-constrained
   selection is available that caps per-band contact share, with its cost in expected
   incremental conversions stated.

### User Story 4 — The policy's value is estimated before it ships (Priority: P1)

Estimate what the candidate policy would have achieved had it been running during the
pilot, using off-policy estimators with confidence intervals.

**Why this priority**: This is what justifies the A/B test rather than replacing it. Going
to an experiment without an offline estimate wastes a cycle.

**Independent Test**: Run inverse-propensity-weighted, self-normalised and doubly-robust
estimators of policy value on the pilot cohort, and confirm they bracket the value computed
directly from ground-truth τ — which 001 uniquely makes available.

**Acceptance Scenarios**:

1. **Given** the pilot cohort and a candidate policy, **When** IPS, SNIPS and DR estimates
   are computed, **Then** each is reported with a confidence interval.
2. **Given** the known-τ oracle value, **When** compared to the DR estimate, **Then** the
   oracle lies inside the DR interval — validating the estimator itself, which is an
   opportunity real data never offers.
3. **Given** a policy that contacts everyone, **When** its value is estimated, **Then** it
   is lower than the budgeted policy, demonstrating the estimator distinguishes policies.
4. **Given** extreme importance weights, **When** estimation runs, **Then** weights are
   clipped at a recorded threshold and the clipped fraction is reported, because an
   unreported clip silently biases the estimate.

### Edge Cases

- All candidates have negative τ̂: return an empty contact list and say so. Never contact
  the "least bad" users to fill a budget.
- Value-fit gate suppresses more than the budget: budget is not the binding constraint;
  report which constraint bound.
- A user is missing fee data entirely: treated as failing value fit, not as passing by
  default. Absence of evidence is not evidence of benefit.
- Contact budget of zero: valid, returns empty, useful as a holdout configuration.
- Ties in τ̂ at the budget boundary: broken deterministically by user id so selection is
  reproducible.

## Requirements

### Functional Requirements

- **FR-001**: System MUST rank candidates by estimated uplift and select the top users
  subject to a configurable contact budget expressed as a share of the eligible population.
- **FR-002**: System MUST exclude any candidate with non-positive estimated uplift,
  unconditionally.
- **FR-003**: System MUST compute, for every candidate, an estimated 90-day saving from the
  deterministic tool layer, requiring no model inference.
- **FR-004**: System MUST suppress candidates whose estimated saving is below the
  subscription cost over the same window times a configurable margin, regardless of uplift.
- **FR-005**: Every decision — selected or suppressed — MUST be written to a decision log
  with the user id, uplift, propensity, estimated saving, cost, binding constraint and
  reason.
- **FR-006**: System MUST report contact rate, mean uplift and mean estimated saving per
  income band, and flag when the contact-rate gap exceeds a configured tolerance.
- **FR-007**: System MUST offer an optional parity-constrained mode that caps per-band
  contact share, reporting its cost in expected incremental conversions.
- **FR-008**: System MUST estimate candidate-policy value on the pilot cohort using IPS,
  SNIPS and doubly-robust estimators, each with a confidence interval.
- **FR-009**: System MUST report the oracle policy value computed from true τ alongside the
  off-policy estimates, as a validation of the estimators.
- **FR-010**: Importance weights MUST be clipped at a recorded threshold, with the clipped
  fraction reported.
- **FR-011**: System MUST report expected incremental conversions for the selected policy,
  a propensity-ranked policy, a contact-all policy and a random policy of equal size.
- **FR-012**: Selection MUST be deterministic: identical inputs and configuration produce
  an identical list, with ties broken by user id.
- **FR-013**: System MUST report which constraint bound the final selection — budget,
  value fit, positivity or parity.

### Key Entities

- **Candidate**: a live user with τ̂, propensity, and features.
- **Value-fit assessment**: estimated saving, subscription cost, margin, verdict.
- **Decision record**: the auditable per-user outcome with its binding constraint.
- **Policy**: a deterministic map from candidate set and configuration to a contact set.
- **Policy value estimate**: an estimator name, a point estimate, an interval, and
  diagnostics including the clipped-weight fraction.

## Success Criteria

- **SC-001**: Zero users with non-positive τ̂ appear in any contact list.
- **SC-002**: 100% of decisions, selected and suppressed, have a logged reason.
- **SC-003**: Mean value fit among selected users is at least 30% higher with the gate on
  than off.
- **SC-004**: The oracle policy value falls inside the doubly-robust confidence interval.
- **SC-005**: Expected incremental conversions per contact for the uplift policy exceed the
  propensity policy by ≥ 25% at a 30% budget.
- **SC-006**: Selection over 12,000 candidates including value-fit evaluation completes in
  under 30 seconds.
- **SC-007**: Contact-rate gap across income bands is reported for every run, and any
  breach of tolerance is flagged in the run output, not only in a file.
- **SC-008**: Repeated runs at identical configuration produce identical contact lists.

## Assumptions

- The pilot's treatment probability is known exactly (0.5 by construction), so IPS weights
  need no propensity-of-treatment model. With real data this would itself be estimated, and
  that is stated as a limitation.
- Estimated savings from the tool layer are a reasonable proxy for realised savings. The
  estimate is deliberately conservative (overdraft coverage below 1.0) so the gate errs
  toward suppression.
- A 90-day window is the appropriate horizon for comparing savings to cost.
- The default value-fit margin is 1.0 — savings must at least equal cost. Raising it is a
  product decision; lowering it below 1.0 is a governance event requiring sign-off.
- Income band is an acceptable fairness axis for this exercise. A real programme would
  consult legal on which attributes may be used for monitoring versus decisions.
