# Feature Specification: Observability, Cost Control & AI Governance

**Feature ID**: `009` · **Domain**: E — Trust & Operations
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 002–008
**Input**: "Make every automated decision explainable after the fact, and produce the
artifacts a risk reviewer would ask for before this touched a real customer."

## Why this feature exists

Two questions decide whether a system like this ships in a regulated environment, and neither
is about model quality:

1. *"A customer complains they were pushed into a subscription. Show me exactly why your system
   contacted them."*
2. *"Show me this does not systematically treat lower-income users differently."*

Both require artifacts that exist **before** the incident. A decision log written after the
fact is not evidence. This feature builds the audit trail, the fairness monitoring, and the
governance documents — and treats them as engineering deliverables with tests, not as a
write-up appended at the end.

## User Scenarios & Testing

### User Story 1 — Any decision can be explained after the fact (Priority: P1)

For any user and cycle, retrieve the complete decision record: scores, constraints, binding
constraint, value-fit figures, variant, the message shown, and the guardrail verdicts it
passed.

**Why this priority**: It is the answer to the complaint scenario, and it is unrecoverable if
not captured at decision time.

**Independent Test**: Run a cycle, pick a contacted user and a suppressed user, and retrieve a
complete record for each.

**Acceptance Scenarios**:

1. **Given** a contacted user, **When** their record is retrieved, **Then** it contains scores,
   the binding constraint, the message, and per-check guardrail verdicts.
2. **Given** a suppressed user, **When** retrieved, **Then** the suppression reason and the
   figures behind it are present.
3. **Given** a record, **When** inspected, **Then** it names the model versions and prompt
   version that produced it — a decision is not explainable without knowing what decided it.
4. **Given** any decision, **When** the log is queried, **Then** a record exists. Coverage is
   100%, not sampled.

### User Story 2 — Fairness is monitored continuously (Priority: P1)

A report of contact rate, conversion rate, retention, mean uplift and mean estimated saving per
income band, with declared tolerances and flags.

**Why this priority**: The correlation between income band and segment is deliberate in 001, so
there is a real signal to detect. A fairness report that always passes tests nothing.

**Acceptance Scenarios**:

1. **Given** a completed cycle, **When** the report is generated, **Then** every metric is
   broken down by income band with the max-min gap.
2. **Given** a gap beyond tolerance, **When** generated, **Then** it is flagged with the bands
   named.
3. **Given** the report, **When** read, **Then** it distinguishes gaps arising from underlying
   behaviour from gaps introduced by the policy — conflating the two is how fairness reporting
   becomes theatre.
4. **Given** model-quality metrics, **When** sliced by band, **Then** AUC and calibration are
   reported per band so unequal *accuracy* is visible, not only unequal treatment.

### User Story 3 — Agent behaviour is observable in aggregate (Priority: P2)

Telemetry over time: latency by provider and tier, tool-call counts, repair attempts, guardrail
block rate by check, degradation rate, tokens per nudge and inferred cost per nudge.

**Why this priority**: It is how prompt drift and model regressions are noticed in production
rather than in an eval run.

**Acceptance Scenarios**:

1. **Given** a period of generations, **When** telemetry is summarised, **Then** latency
   percentiles, block rate by check and degradation rate are reported.
2. **Given** a rising guardrail block rate, **When** it crosses the configured threshold,
   **Then** it is flagged as a prompt-quality regression.
3. **Given** a provider comparison, **When** cost per nudge is computed, **Then** local
   inference reports compute cost and any hosted provider reports token cost, on the same axis
   so the comparison is honest.

### User Story 4 — Governance artifacts exist and stay current (Priority: P1)

A model card, a risk register with mitigations and owners, a fairness audit, and a consent and
data-use note — each referencing the code and tests that enforce them.

**Why this priority**: These are what a risk reviewer reads, and they are the deliverables most
portfolio projects omit entirely.

**Acceptance Scenarios**:

1. **Given** the model card, **When** read, **Then** it covers intended use, out-of-scope use,
   training data, metrics with slices, limitations and known failure modes.
2. **Given** the risk register, **When** read, **Then** each risk has a severity, a mitigation,
   and a pointer to the test or control that implements it — a mitigation with no control is
   recorded as accepted risk, not as mitigated.
3. **Given** a model retrain, **When** the card is regenerated, **Then** its metrics match the
   current evaluation output, verified by test rather than by discipline.
4. **Given** the consent note, **When** read, **Then** it states what data is used, on what
   basis, and how a user would opt out.

### Edge Cases

- A decision made while models were mid-reload: the record must name the versions actually used.
- An income band with too few users for a stable rate: reported with its count and marked
  low-confidence rather than presented as a comparable rate.
- Fairness gap arising entirely from underlying behaviour: reported as such, with the
  counterfactual parity-constrained selection alongside it.
- Telemetry loss: gaps are visible in the series, never interpolated.

## Requirements

### Functional Requirements

- **FR-001**: System MUST persist a decision record for every targeting decision, containing
  user, cycle, scores, constraints evaluated, binding constraint, value-fit figures, variant,
  and model and prompt versions.
- **FR-002**: System MUST persist, per generated message, the tool calls, evidence, per-check
  guardrail verdicts, provider telemetry and degradation status.
- **FR-003**: System MUST expose retrieval of the complete record for one user and cycle.
- **FR-004**: System MUST generate a fairness report over income bands covering contact rate,
  conversion, retention, mean uplift, mean estimated saving, AUC and calibration.
- **FR-005**: The fairness report MUST distinguish behavioural gaps from policy-induced gaps.
- **FR-006**: The fairness report MUST flag tolerance breaches and name the bands.
- **FR-007**: Bands with fewer than a configured minimum count MUST be marked low-confidence.
- **FR-008**: System MUST summarise agent telemetry with latency percentiles, tool-call counts,
  repair attempts, block rate by check, degradation rate and cost per nudge.
- **FR-009**: System MUST flag a guardrail block rate above a configured threshold.
- **FR-010**: System MUST produce a model card generated from current evaluation output, not
  hand-maintained.
- **FR-011**: System MUST maintain a risk register in which every risk names either a control or
  an explicit acceptance.
- **FR-012**: System MUST maintain a consent and data-use note.
- **FR-013**: Logs MUST be structured and machine-queryable.
- **FR-014**: A test MUST assert that model-card metrics match current evaluation output.
- **FR-015**: Decision-log coverage MUST be 100% of decisions, asserted by test.

### Key Entities

- **Decision record**: the full auditable context of one targeting decision.
- **Generation record**: the full auditable context of one agent message.
- **Fairness report**: sliced metrics, gaps, tolerances, flags, confidence markers.
- **Telemetry summary**: aggregate agent operational metrics for a period.
- **Governance artifact**: model card, risk register, fairness audit, consent note.

## Success Criteria

- **SC-001**: Decision-log coverage is 100%.
- **SC-002**: Any user's decision is reconstructable from the log alone, without rerunning the
  pipeline.
- **SC-003**: The fairness report is regenerated on every training run and is part of the merge
  gate.
- **SC-004**: Model-card metrics match current evaluation output, verified by test.
- **SC-005**: Every risk in the register names a control or an explicit acceptance.
- **SC-006**: Telemetry reports latency percentiles and block rate per check for every provider
  in use.
- **SC-007**: A reader with no prior context can determine, from the governance documents alone,
  what the system does, what it must not do, and how that is enforced.

## Assumptions

- Income band is the available fairness axis in this synthetic population. A real programme
  would consult legal on which attributes may be monitored versus used, and the report says so.
- Structured logs to SQLite and JSON files are sufficient at this scale; a metrics backend is a
  later swap.
- Cost for local inference is approximated from wall-clock compute rather than metered.
- Governance documents here are portfolio-grade. They are modelled on what a real review would
  ask for and do not claim to be a completed regulatory filing.
