# Feature Specification: Web Console — Nudge, Chat & Experiment Dashboard

**Feature ID**: `008` · **Domain**: D — Product Surface
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 007
**Input**: "Make the whole system visible in a browser: what the model decided, what the
agent said and why, and whether the experiment is working."

## Why this feature exists

The hardest thing to convey about this system is that the safety properties are real. A
paragraph claiming "every number is verified" is unconvincing; a chat message where each
figure is a chip you can click to see the tool call that produced it is not.

The console therefore has one unusual requirement: **it renders the machinery, not just the
output**. Evidence chips, guardrail badges, the suppression log with reasons, and the
degradation indicator are all first-class UI, because they are the product's actual claim.

It is also the demo surface. Ten minutes with this page has to carry the argument.

## User Scenarios & Testing

### User Story 1 — A reviewer inspects a cohort and sees who is targeted and why (Priority: P1)

A sortable table of live users with propensity, uplift, segment, value fit and decision, with
suppressed users visible and their reason shown.

**Why this priority**: It is the clearest demonstration that uplift and propensity disagree,
and that the value-fit gate bites.

**Independent Test**: Load the cohort view, sort by uplift, and confirm high-propensity
users appear who are *not* targeted, with reasons displayed.

**Acceptance Scenarios**:

1. **Given** the cohort view, **When** sorted by propensity descending, **Then** users that
   are suppressed are visibly marked with their reason.
2. **Given** a suppressed user, **When** their row is expanded, **Then** the estimated saving
   and subscription cost are shown side by side.
3. **Given** the view, **When** a summary is read, **Then** counts of selected and suppressed
   by reason are displayed.

### User Story 2 — A user-facing nudge is previewed with its evidence (Priority: P1)

The nudge as the user would see it, with each figure rendered as a chip that reveals the tool
call and value behind it, plus guardrail badges.

**Why this priority**: This is the single most persuasive screen in the project.

**Independent Test**: Open a nudge, click a figure, confirm the originating tool call and raw
value are shown.

**Acceptance Scenarios**:

1. **Given** a generated nudge, **When** a monetary figure is clicked, **Then** the tool call
   and returned value are displayed.
2. **Given** a nudge, **When** guardrail results are shown, **Then** each check appears with
   its own pass/fail state, not one aggregate badge.
3. **Given** a degraded response, **When** rendered, **Then** it is visibly marked as the
   deterministic fallback with the reason.
4. **Given** a not-worth-it recommendation, **When** rendered, **Then** it is presented plainly
   rather than styled as a warning or an error.

### User Story 3 — A user chats with the concierge (Priority: P2)

A chat panel with streaming-style progressive display, visible tool-call activity, and per-turn
guardrail state.

**Why this priority**: Deepens the demo; the nudge preview carries the core argument alone.

**Acceptance Scenarios**:

1. **Given** a question, **When** submitted, **Then** tool calls in progress are visible before
   the answer arrives.
2. **Given** an off-topic question, **When** answered, **Then** the decline is shown normally.
3. **Given** a slow local model, **When** waiting, **Then** an honest progress state is shown
   rather than a spinner with no information.

### User Story 4 — An analyst reads the experiment dashboard (Priority: P1)

Conversion by variant with intervals, the retention guardrail against its margin, the
sequential bound over time, and the current verdict.

**Why this priority**: It closes the loop from model to measured impact.

**Acceptance Scenarios**:

1. **Given** accumulated events, **When** the dashboard loads, **Then** per-arm conversion with
   intervals is charted.
2. **Given** the guardrail, **When** charted, **Then** the non-inferiority margin is drawn as an
   explicit reference line.
3. **Given** the sequential bound, **When** charted over time, **Then** the fixed-horizon bound
   is overlaid so the width difference is visible rather than asserted.
4. **Given** a stop-for-harm verdict, **When** displayed, **Then** it is the most prominent
   element on the page.

### Edge Cases

- API unavailable: an explicit error state naming what failed, never an empty chart that reads
  as zero.
- Nudge still generating: a pending state; the page must not appear broken during a 15-second
  local generation.
- Zero events yet: charts render empty with an explanatory message, not a crash.
- Very long agent message: scrolls without breaking the evidence chips.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a cohort view with sorting, filtering by segment and
  decision, and pagination.
- **FR-002**: Cohort rows MUST show propensity, uplift, segment, estimated saving, decision and
  suppression reason.
- **FR-003**: System MUST render a nudge preview with every monetary figure as an interactive
  evidence chip.
- **FR-004**: Clicking a chip MUST reveal the originating tool call and its returned value.
- **FR-005**: Guardrail results MUST be displayed per check.
- **FR-006**: Degraded responses MUST be visibly marked with the reason.
- **FR-007**: System MUST provide a chat panel showing tool-call activity and per-turn guardrail
  state.
- **FR-008**: System MUST provide an experiment dashboard with per-arm conversion and intervals,
  the retention guardrail against its margin, and the sequential bound over time with the
  fixed-horizon bound overlaid.
- **FR-009**: The current stopping verdict MUST be displayed with its governing rule.
- **FR-010**: All views MUST show explicit loading, empty and error states.
- **FR-011**: The synthetic-data notice MUST be visible on every view, not only on a landing
  page.
- **FR-012**: Charts MUST be readable in light and dark themes and legible at phone width.
- **FR-013**: Numeric axes MUST be labelled with units; percentages and dollars MUST be visually
  distinguishable.

### Key Entities

- **Cohort row**: one user's scores and decision.
- **Nudge preview**: message, evidence chips, guardrail badges, degradation state.
- **Chat turn**: user text, tool activity, response, guardrail state.
- **Dashboard series**: per-arm time series of rate, bound and guardrail.

## Success Criteria

- **SC-001**: Every monetary figure in a rendered nudge is traceable in the UI to a tool call in
  at most two clicks.
- **SC-002**: Cohort view renders 1,000 rows without perceptible lag.
- **SC-003**: All four views have explicit loading, empty and error states, verified by test.
- **SC-004**: Dashboard communicates the stopping verdict without the reader consulting the
  documentation.
- **SC-005**: Production bundle under 500 KB gzipped.
- **SC-006**: Charts legible at 375 px width and in both themes.
- **SC-007**: A reviewer can follow the full story — targeting, message, evidence, experiment —
  in under ten minutes without a guide.

## Assumptions

- Single-page app, client-side rendering, no SSR.
- Desktop-first, phone-legible. Not a production mobile experience.
- No authentication, matching 007.
- Chat "streaming" may be simulated progressive rendering in v1; true token streaming is future
  work and is labelled as such rather than implied.
