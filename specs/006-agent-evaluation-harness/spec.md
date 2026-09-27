# Feature Specification: Agent Evaluation Harness & CI Gate

**Feature ID**: `006` · **Domain**: C — Agentic Layer
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 005
**Input**: "Prove the agent is safe and useful, on every commit, with numbers rather than
anecdotes — and block the build when it is not."

## Why this feature exists

An agent demo is a screenshot. An agent product is a number that moves when you change the
prompt.

Most LLM projects stop at "here is a nice output". That is unfalsifiable, and it is the
first thing a serious reviewer probes: *how do you know it works? what happens when you
change the prompt? how would you notice a regression?*

This feature answers those questions with a two-tier evaluation:

1. **Programmatic checks** — deterministic, cheap, absolute. Grounding violations, refusal
   of prohibited advice, injection resistance, required disclosure, tool-selection accuracy.
   These are pass/fail and they gate the build.
2. **LLM-as-judge** — a graded rubric for the things a regex cannot see: is the explanation
   accurate, relevant, appropriately hedged, and readable. These are scores, tracked over
   time, with a regression threshold.

Local inference is what makes this affordable. Zero marginal cost per run is the reason the
grounding gate can be absolute over the whole case set rather than sampled — and a sampled
safety gate is not a gate ([ADR-001](../../docs/adr/ADR-001-local-first-inference.md)).

## User Scenarios & Testing

### User Story 1 — A CI run blocks a grounding regression (Priority: P1)

The harness runs the golden case set and fails the build on any grounding violation.

**Why this priority**: It is the enforcement mechanism for the project's central safety
claim. Without it, the claim is aspirational.

**Independent Test**: Deliberately weaken the grounding guardrail, run the harness, and
confirm a non-zero exit with the violating case and span named.

**Acceptance Scenarios**:

1. **Given** the golden case set, **When** the harness runs with guardrails intact, **Then**
   it exits zero and reports zero violations.
2. **Given** a deliberately introduced violation, **When** the harness runs, **Then** it
   exits non-zero and names the case, the offending number, and the check that caught it.
3. **Given** a run, **When** it completes, **Then** a machine-readable report is written with
   per-case verdicts and aggregate rates.

### User Story 2 — A prompt change is measured, not guessed (Priority: P1)

Change the system prompt, re-run, and see every metric move with a diff against the recorded
baseline.

**Why this priority**: This is the difference between engineering an agent and tinkering
with one.

**Independent Test**: Run twice with a modified prompt and confirm a comparison report
showing per-metric deltas and a verdict.

**Acceptance Scenarios**:

1. **Given** a recorded baseline, **When** a new run completes, **Then** per-metric deltas
   are reported.
2. **Given** a judge score drop beyond the regression threshold, **When** compared, **Then**
   the run is flagged as a regression.
3. **Given** a run, **When** cost and latency are reported, **Then** they are attributed per
   provider and model tier, so quality gains can be weighed against their price.

### User Story 3 — Model tiers are compared honestly (Priority: P2)

Run the same cases across the 1.5B tier, the 3B tier and the deterministic provider, and
report a comparison.

**Why this priority**: It answers "why this model?" with evidence, and it establishes that
the deterministic floor is a real baseline rather than a mock.

**Independent Test**: Run across three providers and confirm a table of safety and quality
metrics per provider.

**Acceptance Scenarios**:

1. **Given** three providers, **When** the suite runs against each, **Then** tool-selection
   accuracy, grounding violations, judge scores and latency are reported per provider.
2. **Given** the deterministic provider, **When** it is evaluated, **Then** it records zero
   grounding violations by construction — establishing the floor.
3. **Given** the comparison, **When** a model tier fails to beat the deterministic provider
   on judge-scored helpfulness, **Then** that is reported prominently as the finding it is.

### User Story 4 — A judge scores what regexes cannot (Priority: P2)

An LLM judge scores each response against a rubric with structured output, returning
per-dimension scores and a rationale.

**Why this priority**: Needed for quality tracking; safety is already covered
programmatically and does not depend on it.

**Independent Test**: Score a known-good and a known-poor response and confirm the judge
separates them, then confirm score stability across repeated runs.

**Acceptance Scenarios**:

1. **Given** a response and its tool-result context, **When** judged, **Then** per-dimension
   scores and a written rationale are returned in a validated structure.
2. **Given** the same response judged three times at temperature zero, **Then** scores are
   identical.
3. **Given** a response containing a fabricated figure, **When** judged, **Then** accuracy
   scores lowest — the judge must agree with the programmatic check, and disagreement is
   itself reported as a judge-calibration finding.
4. **Given** the judge is unavailable, **When** the harness runs, **Then** programmatic
   checks still run and gate, and judge metrics are marked unavailable rather than skipped
   silently.

### Edge Cases

- Judge model returning malformed structure: retried, then recorded as unavailable for that
  case; never coerced into a score.
- Case set containing a user who no longer exists: fails loudly as a fixture error, not as
  an agent failure. Confusing the two would poison the metric.
- A judge that systematically disagrees with programmatic grounding checks: reported as a
  judge-calibration problem, and the programmatic check always wins.
- Non-determinism from an unseeded provider: harness asserts seeding and refuses to record a
  baseline from an unseeded run.
- Empty case set: fails; an empty gate that passes is worse than no gate.

## Requirements

### Functional Requirements

- **FR-001**: System MUST maintain a versioned golden case set covering: fee-heavy users,
  zero-fee users, savings-below-cost users, dormant users, missing-data users, prohibited-
  advice probes, injection probes, and off-topic probes.
- **FR-002**: Each case MUST declare its expected properties — features that should be
  mentioned, whether a decline is required, whether a not-worth-it statement is required.
- **FR-003**: System MUST compute grounding violation count and rate.
- **FR-004**: System MUST compute prohibited-advice refusal rate.
- **FR-005**: System MUST compute injection resistance rate.
- **FR-006**: System MUST compute tool-selection accuracy against each case's expected tool
  set.
- **FR-007**: System MUST compute required-disclosure presence rate.
- **FR-008**: System MUST compute a not-worth-it statement rate over cases where savings fall
  below cost.
- **FR-009**: System MUST run an LLM judge scoring accuracy, relevance, appropriate hedging,
  clarity and absence of pressure, using validated structured output.
- **FR-010**: System MUST exit non-zero on any grounding violation, regardless of other
  metrics.
- **FR-011**: System MUST exit non-zero when judge-scored quality falls below the recorded
  baseline by more than the configured threshold.
- **FR-012**: System MUST write a machine-readable report and a human-readable summary.
- **FR-013**: System MUST support running against multiple providers and produce a
  comparison.
- **FR-014**: System MUST record latency and token counts per case and per provider.
- **FR-015**: System MUST support recording a run as the new baseline, as an explicit
  operation and never automatically.

### Key Entities

- **Evaluation case**: user id, input, expected properties, rationale for inclusion.
- **Case result**: generated output, guardrail verdicts, judge scores, telemetry.
- **Metric set**: aggregate safety and quality rates for one run and one provider.
- **Baseline**: a recorded metric set with the commit and configuration that produced it.
- **Judge rubric**: dimensions, scales, and the instructions given to the judge.

## Success Criteria

- **SC-001**: Grounding violation rate is 0.00 across the case set, for every provider.
- **SC-002**: Prohibited-advice refusal rate ≥ 0.98.
- **SC-003**: Injection resistance rate is 1.00.
- **SC-004**: Required-disclosure presence is 1.00.
- **SC-005**: Not-worth-it statement rate ≥ 0.95 on applicable cases.
- **SC-006**: Judge score variance across repeated identical runs is zero.
- **SC-007**: Full suite on the fast tier completes in under 10 minutes on 4 CPU cores,
  keeping it viable as a per-commit gate.
- **SC-008**: The case set covers at least 30 cases with every listed category represented.

## Assumptions

- A local model can serve as its own judge for quality dimensions. This is a real limitation
  — self-judging correlates errors — and is stated in the report rather than hidden. The
  programmatic checks are the ones that gate, precisely because they do not depend on a
  model's opinion.
- Golden cases are drawn from the synthetic population, so they are stable and
  redistributable.
- Judge scores are for tracking relative change over time, not for absolute claims of
  quality.
- Human review of a sample remains necessary before any real deployment; the harness reduces
  how much is needed, it does not replace it.
