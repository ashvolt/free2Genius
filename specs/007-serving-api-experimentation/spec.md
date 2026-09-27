# Feature Specification: Serving API & Experimentation Platform

**Feature ID**: `007` · **Domain**: D — Product Surface
**Created**: 2026-09-27 · **Status**: Implemented · **Converged**: 2026-09-27
**Depends on**: 003 (policy), 005 (agent)
**Input**: "Expose scoring and agent generation over HTTP, assign users to variants, capture
the funnel, and analyse the result in a way that survives being looked at daily."

## Why this feature exists

A model in a notebook has produced zero dollars. This feature is where the system becomes
something a product team can run: an HTTP surface, a variant assignment that is stable and
auditable, event capture for the funnel, and an analysis that is valid when read at any
moment ([ADR-005](../../docs/adr/ADR-005-sequential-testing.md)).

The experimentation half exists because the easiest way to report a conversion win is to
measure it badly. Three arms, a pre-declared guardrail, and always-valid inference are what
make the reported number mean something.

## User Scenarios & Testing

### User Story 1 — A client scores a user and gets a decision with its reasoning (Priority: P1)

One request returns propensity, uplift, the targeting verdict, the binding constraint, and
the value-fit assessment.

**Why this priority**: Every other surface consumes it.

**Independent Test**: Request a score for a known user and confirm the response contains all
decision components and that suppression carries a reason.

**Acceptance Scenarios**:

1. **Given** a valid user id, **When** scored, **Then** the response contains propensity,
   uplift, decision, binding constraint and value-fit figures.
2. **Given** an unknown user id, **When** scored, **Then** a 404 is returned with a message,
   not a default score.
3. **Given** a user suppressed by value fit, **When** scored, **Then** the response states the
   reason and the two figures behind it.
4. **Given** models are absent from disk, **When** the service starts, **Then** it fails at
   startup naming the command that trains them, rather than serving wrong numbers.

### User Story 2 — A user opens the app and is assigned a variant (Priority: P1)

Assignment is deterministic in user id and experiment id, stable across requests, and
recorded once.

**Why this priority**: An unstable assignment invalidates the whole experiment.

**Independent Test**: Assign the same user 100 times and confirm one variant; assign 10,000
users and confirm arm proportions match the configured split within tolerance.

**Acceptance Scenarios**:

1. **Given** a user and experiment, **When** assigned repeatedly, **Then** the variant never
   changes.
2. **Given** 10,000 users, **When** assigned, **Then** each arm is within one percentage
   point of its configured share.
3. **Given** a changed experiment id, **When** the same users are assigned, **Then** the
   partition differs — so successive experiments are not correlated by construction.
4. **Given** a user assigned to holdout, **When** a nudge is requested, **Then** none is
   produced and the holdout impression is still recorded.

### User Story 3 — The funnel is captured (Priority: P1)

Impressions, clicks, conversions and 30-day retention are recorded against user, variant and
timestamp, idempotently.

**Why this priority**: No events, no experiment.

**Independent Test**: Post the same conversion event twice and confirm it is counted once.

**Acceptance Scenarios**:

1. **Given** a duplicate event with the same idempotency key, **When** posted, **Then** it is
   stored once.
2. **Given** an event for an unassigned user, **When** posted, **Then** it is rejected —
   events outside the experiment frame would bias the analysis.
3. **Given** a conversion, **When** stored, **Then** it carries the variant that was active at
   assignment, not at conversion time.

### User Story 4 — Results are valid whenever they are read (Priority: P1)

Conversion by variant, lift with a sequential confidence sequence, the retention guardrail
with its non-inferiority bound, and the current stopping-rule verdict.

**Why this priority**: The analysis is the deliverable of the experiment.

**Independent Test**: Simulate a null experiment with 200 sequential looks and confirm the
false-positive rate of the sequential bound stays near α, while the naive fixed-horizon test
inflates well past it.

**Acceptance Scenarios**:

1. **Given** accumulated events, **When** the summary is requested, **Then** per-arm rates,
   lift, sequential bounds and fixed-horizon bounds are all returned.
2. **Given** a retention breach, **When** the summary is computed, **Then** the verdict is
   `stop_for_harm` and it is evaluated before any ship verdict.
3. **Given** a null simulation with repeated looks, **When** sequential and fixed-horizon
   error rates are compared, **Then** sequential stays near α and the difference is reported.
4. **Given** insufficient data, **When** the summary is requested, **Then** the verdict is
   `continue` with the projected remaining duration.

### User Story 5 — A concierge message is served (Priority: P2)

Generate or retrieve a cached grounded nudge, and hold a chat turn, returning citations and
guardrail verdicts.

**Why this priority**: The agent is specified in 005; this exposes it.

**Acceptance Scenarios**:

1. **Given** a user in the agent arm, **When** a nudge is requested, **Then** the message,
   citations and guardrail verdicts are returned.
2. **Given** a repeat request within the cache window, **Then** the cached message is served
   and marked as cached.
3. **Given** the model is unavailable, **Then** the deterministic message is served and marked
   degraded, with a 200 status.

### Edge Cases

- Concurrent identical nudge requests: generated once, not twice.
- Clock skew on retention windows: retention evaluated on stored timestamps, not request time.
- Experiment configuration changed mid-flight: rejected; a new experiment id is required.
- Event arriving after the experiment closes: stored, flagged out-of-window, excluded from the
  primary analysis.

## Requirements

### Functional Requirements

- **FR-001**: System MUST expose scoring for a single user and for a batch.
- **FR-002**: System MUST expose the current contact list for a cycle, with suppression counts
  by reason.
- **FR-003**: System MUST expose nudge generation and multi-turn chat, returning citations,
  guardrail verdicts and degradation status.
- **FR-004**: Variant assignment MUST be a pure function of user id and experiment id.
- **FR-005**: System MUST support at least three arms: agent concierge, generic upsell, and
  holdout.
- **FR-006**: System MUST record impression, click, conversion and retention events with an
  idempotency key.
- **FR-007**: Events MUST be rejected for users with no assignment in the named experiment.
- **FR-008**: System MUST compute per-arm conversion rate, absolute and relative lift, a
  fixed-horizon interval, and an always-valid sequential confidence sequence.
- **FR-009**: System MUST compute the 30-day retention guardrail per arm with a
  non-inferiority bound.
- **FR-010**: System MUST return a stopping verdict from pre-declared rules, evaluating harm
  before ship.
- **FR-011**: System MUST expose a fixed-horizon sample-size calculation given baseline rate,
  minimum detectable effect, power and α.
- **FR-012**: System MUST cache generated nudges with a configurable TTL and report cache
  status.
- **FR-013**: Startup MUST fail loudly when required model artifacts are missing.
- **FR-014**: All endpoints MUST use typed request and response models with a published schema.
- **FR-015**: System MUST expose a health endpoint reporting model, provider and data status.

### Key Entities

- **Experiment**: id, arms with shares, start, planned horizon, primary metric, guardrail.
- **Assignment**: user, experiment, variant, timestamp.
- **Event**: user, experiment, variant, type, value, timestamp, idempotency key.
- **Score response**: propensity, uplift, decision, constraint, value-fit assessment.
- **Experiment summary**: per-arm counts and rates, lift with bounds, guardrail, verdict.

## Success Criteria

- **SC-001**: Assignment is stable across 100 repeated calls for 1,000 users.
- **SC-002**: Arm proportions within one percentage point of configuration at 10,000 users.
- **SC-003**: Single-user scoring p95 under 50 ms with models warm.
- **SC-004**: Cached nudge retrieval p95 under 20 ms.
- **SC-005**: Duplicate events never double-count.
- **SC-006**: In a null simulation with 200 looks, sequential false-positive rate ≤ 0.07 at
  α = 0.05 while the naive repeated fixed-horizon test exceeds 0.20.
  Measured: sequential **0.03**, naive **0.49**.
- **SC-007**: Service starts in under 10 seconds with models and data present.
- **SC-008**: Every endpoint is covered by an integration test.

## Assumptions

- SQLite is sufficient at demonstration scale; the store is behind an interface so Postgres is
  a swap, and this is recorded rather than pretended away.
- A single process serves all traffic; no horizontal scaling in v1.
- Retention at 30 days is simulated from the generated cohort rather than waiting 30 days.
- No authentication in v1. This is a demonstration service and the omission is stated loudly
  in the README rather than left for a reviewer to discover.
