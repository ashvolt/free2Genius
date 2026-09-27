# Feature Specification: Synthetic Data Foundation

**Feature ID**: `001` · **Domain**: A — Data Foundation
**Created**: 2026-09-27 · **Status**: Implemented
**Input**: "We need a population to model against, and we have no real data. It must be
honest about being synthetic, reproducible, and rich enough that uplift modelling is a
real exercise rather than a demo."

## Why this feature exists at all

Every downstream claim in this project — that uplift beats propensity, that the value-fit
gate suppresses the right users, that the agent never invents a fee — is only as credible
as the population it is demonstrated on.

A synthetic generator is usually a liability in a portfolio project: it lets you prove
whatever you want. Here it is deliberately the opposite. Because we control the
data-generating process, we know each user's **true treatment effect τ**, which real data
never gives you. That turns uplift evaluation from "the curve looks plausible" into "the
estimator recovers a known quantity to within a stated tolerance." No production dataset
can support that claim.

## User Scenarios & Testing

### User Story 1 — A modeller gets a population with known ground truth (Priority: P1)

A modeller runs one command and receives a labelled cohort where every user has observed
behaviour, a randomized treatment assignment, an observed outcome, and the hidden true
treatment effect that produced it.

**Why this priority**: Nothing else in the repository can be built or validated without
it. It is the only feature with no dependencies.

**Independent Test**: Run the generator, then verify the observed average treatment effect
(treated conversion rate minus control conversion rate) matches the mean of the hidden τ
within sampling error. If it does, the simulation is internally consistent and every
uplift metric computed on it is interpretable.

**Acceptance Scenarios**:

1. **Given** a fixed seed, **When** the generator runs twice, **Then** both runs produce
   byte-identical output.
2. **Given** the generated pilot cohort, **When** the observed ATE is compared to mean τ,
   **Then** the two agree within two standard errors.
3. **Given** the generated cohort, **When** users are grouped by latent segment, **Then**
   at least one segment has mean τ clearly positive and at least one clearly negative.
4. **Given** the frame handed to a model, **When** its columns are inspected, **Then** no
   ground-truth or identifier column is present among the features.

### User Story 2 — The agent gets specific, dated facts to cite (Priority: P1)

The concierge agent must say "three express-delivery fees of $4.99 on 12 Jul, 28 Jul and
14 Aug", not "you pay some fees". That requires event-level detail, not aggregates.

**Why this priority**: Equal to US1. Without event detail the agent can only produce vague
copy, and vague copy is what this entire project exists to replace.

**Independent Test**: For any user id, request their ledger and confirm it contains dated
fee events, advances, subscriptions and deposits, and that the events sum exactly to the
aggregate features the model sees for that same user.

**Acceptance Scenarios**:

1. **Given** any user, **When** their fee events are summed, **Then** the total equals
   their aggregate fee features to the cent.
2. **Given** the same user id requested twice, **Then** the ledger is identical.
3. **Given** a user with zero fees, **When** their ledger is built, **Then** it returns
   empty collections rather than failing.

### User Story 3 — A reviewer can score users who have no outcome yet (Priority: P2)

The serving path needs current free users with features but no label — otherwise scoring
is indistinguishable from reading the answer.

**Why this priority**: Needed before the API is built, not before models are trained.

**Independent Test**: Load the live cohort and confirm outcome columns are absent or
explicitly null, while every feature the model requires is present.

**Acceptance Scenarios**:

1. **Given** the live cohort, **When** label columns are read, **Then** they are marked
   unobserved rather than zero — a sentinel that cannot be silently averaged.
2. **Given** the live cohort, **When** the trained feature pipeline is applied, **Then**
   it succeeds without imputation warnings.

### Edge Cases

- A user with no direct deposit must still produce a valid ledger (no deposits, not an
  error).
- A user whose subscription detail cannot be rescaled to match their aggregate (zero
  subscriptions, non-zero spend) must not silently disagree; the generator must make this
  state unreachable.
- Treatment probability plus effect must remain a valid probability for every user; τ is
  clipped so that `p0 + τ ∈ (0, 1)`.
- Requesting a ledger for an unknown user id must raise a distinguishable error, not
  return an empty ledger that reads as "this user has no fees".

## Requirements

### Functional Requirements

- **FR-001**: System MUST generate a *pilot* cohort with randomized binary treatment
  assignment, an observed conversion outcome, and an observed 30-day retention outcome for
  converters only.
- **FR-002**: System MUST generate a *live* cohort with identical features and no
  outcomes.
- **FR-003**: System MUST record, per user, the hidden baseline conversion probability and
  the hidden true treatment effect, stored separately from model features and never
  exposed to training.
- **FR-004**: The population MUST contain at least one sub-population with materially
  negative treatment effect, so that do-no-harm targeting is testable rather than
  hypothetical.
- **FR-005**: System MUST expand any user's aggregate features into dated event-level
  records — fee events, cash advances, recurring subscriptions, direct deposits — that
  reconcile exactly with those aggregates.
- **FR-006**: Ledger expansion MUST be deterministic in the user identifier, so repeated
  reads are stable without storage.
- **FR-007**: System MUST expose a single catalog of subscription pricing and free-tier fee
  amounts, as the only sanctioned source of pricing facts for any downstream component.
- **FR-008**: Outcome columns in the live cohort MUST use a sentinel that cannot be
  mistaken for a real value in an aggregation.
- **FR-009**: 30-day retention among converters MUST depend on whether the subscription
  genuinely fits that user's fee profile, so that a conversion-maximising policy is
  detectably worse on retention.
- **FR-010**: Generation MUST be reproducible from a seed and MUST print a summary
  including control rate, treated rate, observed ATE, mean true τ, and mean τ per segment.

### Key Entities

- **User**: one free-tier account. Behavioural features over a trailing 90-day window,
  plus demographic bands used only for fairness slicing.
- **Latent segment**: hidden archetype (persuadable, sure thing, lost cause, sleeping dog)
  that shapes observable behaviour and determines effect sign. Never a feature.
- **Treatment assignment**: randomized pilot arm, the basis of causal identification.
- **Outcome**: conversion, and retention at 30 days conditional on conversion.
- **Ledger**: dated events for one user, reconciling to that user's aggregates.
- **Catalog**: features, monthly price, and free-tier fee amounts.

## Success Criteria

- **SC-001**: Observed ATE agrees with mean true τ within two standard errors.
- **SC-002**: Per-user fee events reconcile to aggregate fee features to the cent, for
  100% of users.
- **SC-003**: At least one segment has mean τ ≥ +4 percentage points and at least one has
  mean τ ≤ −1 percentage point.
- **SC-004**: Two runs at the same seed produce identical output.
- **SC-005**: Full generation of 60,000 pilot and 12,000 live users completes in under 60
  seconds on a 4-core machine.
- **SC-006**: Retention among converters differs by at least 10 percentage points between
  the best and worst value-fit quartile, making the guardrail informative.

## Assumptions

- A 90-day observation window is the behavioural horizon; a 30-day post-conversion window
  is the retention horizon.
- Treatment share in the pilot is 50/50. A real programme would justify a smaller holdout;
  50/50 maximises power for the demonstration.
- Fee amounts are flat per event ($4.99 express delivery, $34.00 overdraft), which is
  realistic for these fee types and keeps reconciliation exact.
- Income band is correlated with segment. This is deliberate: it gives the fairness audit
  a real signal to find rather than a clean synthetic null.
- Demographic bands are used for slicing and are available to the model. Whether they
  *should* be is a governance question addressed in feature 009, not here.
