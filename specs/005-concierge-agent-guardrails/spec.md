# Feature Specification: Genius Concierge Agent & Safety Guardrails

**Feature ID**: `005` · **Domain**: C — Agentic Layer
**Created**: 2026-09-27 · **Status**: Specified
**Depends on**: 001 (account data, catalog), 004 (LLM runtime)
**Input**: "An agent that explains, in plain language, which Genius features would save
this specific user money — grounded in their own data, incapable of inventing a fee, and
willing to say the subscription is not worth it."

## Why this feature exists

Generic upsell copy fails because it is generic. "Upgrade to Genius and save!" tells a user
nothing about their own situation, and users correctly ignore it.

What changes the decision is specificity: *"You paid $44.91 in express-delivery fees across
nine advances since July. Genius removes that fee. Over the same period Genius would have
cost $44.97 — so for you this is roughly break-even, and worth it only if you also want the
overdraft shield."*

That message is persuasive precisely because it is true, checkable, and not always a sell.
Producing it safely is the whole problem: the same capability that writes it can invent a
fee that was never charged. So the agent is built with the assumption that **the model will
occasionally be confidently wrong**, and the system is designed so that being wrong cannot
reach the user.

## User Scenarios & Testing

### User Story 1 — A user receives a specific, grounded explanation (Priority: P1)

For a given user, the agent investigates their account through tools and produces a short
explanation naming the features relevant to them, the evidence, and the estimated saving.

**Why this priority**: It is the product.

**Independent Test**: Generate for a user with known fee history and confirm the output
names the correct features, cites the right figures, and that every figure appears in the
session's tool-result value ledger.

**Acceptance Scenarios**:

1. **Given** a user with express-delivery fees, **When** generation runs, **Then** the
   output references instant delivery and states a saving equal to the tool-computed value.
2. **Given** any generated message, **When** each numeric token is extracted, **Then** every
   one is present in the value ledger or derivable from the catalog.
3. **Given** a user with no fees at all, **When** generation runs, **Then** the output says
   the fee-based features would not save them money — it does not manufacture a reason.
4. **Given** generation completes, **When** the result is inspected, **Then** it carries the
   tool calls made, the evidence cited, and the guardrail verdicts.

### User Story 2 — The agent recommends against buying when that is the truth (Priority: P1)

Where estimated savings do not clear the subscription price, the agent says so plainly.

**Why this priority**: It is the constitutional principle that makes everything else
defensible, and it is what distinguishes this from a conversion optimiser.

**Independent Test**: Generate for a user whose savings fall below cost and confirm the
output states the subscription is unlikely to pay for itself, and does not close.

**Acceptance Scenarios**:

1. **Given** estimated saving below cost, **When** generation runs, **Then** the output
   contains an explicit statement that it may not be worth it.
2. **Given** the same case, **When** the output is checked for urgency or scarcity language,
   **Then** none is present.
3. **Given** a negative net position, **When** the message is generated, **Then** the net
   figure is stated rather than omitted.

### User Story 3 — A user can ask follow-up questions (Priority: P2)

A multi-turn chat where the agent answers from the same tool surface, under the same
guardrails, with conversation context retained.

**Why this priority**: The nudge is the primary surface; chat deepens it. Independently
valuable but not required for the first slice.

**Independent Test**: Hold a three-turn conversation, confirm later turns reuse earlier tool
results where appropriate and that guardrails run on every turn.

**Acceptance Scenarios**:

1. **Given** a prior turn that fetched fees, **When** the user asks a follow-up about those
   fees, **Then** the agent answers without redundant identical tool calls.
2. **Given** any turn, **When** it is produced, **Then** guardrails run on it.
3. **Given** a question outside scope (investment, tax, credit repair), **When** asked,
   **Then** the agent declines and redirects, in one sentence, without moralising.

### User Story 4 — Prompt injection cannot redirect the agent (Priority: P1)

User-supplied text attempting to change the agent's identity, target another user, or
extract the system prompt fails.

**Why this priority**: The agent reads a text field a user controls and holds financial
data. This is the security boundary.

**Independent Test**: Run an injection corpus and confirm no tool call is made outside the
bound user and no system-prompt content is emitted.

**Acceptance Scenarios**:

1. **Given** input requesting another user's data, **When** processed, **Then** every tool
   call still resolves to the session's bound user — the model cannot express otherwise.
2. **Given** input requesting the system prompt, **When** processed, **Then** it is not
   reproduced.
3. **Given** input instructing the agent to state a fee it has not observed, **When**
   processed, **Then** the grounding guardrail blocks the message.
4. **Given** any injection attempt, **When** detected, **Then** it is logged with the
   matched pattern for review.

### Edge Cases

- A user whose data is entirely absent: the agent must state the limitation rather than
  reason from nothing.
- The model calls no tools and answers from parametric knowledge: the grounding guardrail
  blocks any number it produced, and the turn degrades.
- The model loops on the same tool: bounded by round cap, then forced to summarise.
- The message contains a correct number the model computed itself rather than read from a
  tool: blocked. This is a deliberate false positive, and the reason `estimate_savings`
  exists.
- Guardrails reject three consecutive drafts: fall back to the deterministic provider rather
  than retry indefinitely.

## Requirements

### Functional Requirements

- **FR-001**: System MUST bind the target user at session construction. User identity MUST
  NOT be a model-supplied tool parameter.
- **FR-002**: System MUST expose exactly the tool surface defined in 001, and MUST reject
  calls to unregistered tools.
- **FR-003**: System MUST run a bounded tool-use loop with a configurable maximum round
  count, and MUST force a final answer when the cap is reached.
- **FR-004**: The agent MUST NOT perform arithmetic on financial values; all savings figures
  MUST come from the estimation tool.
- **FR-005**: System MUST run a numeric grounding check on every generated message, blocking
  any message containing a numeric value not present in the session value ledger, derivable
  from the catalog, or on a documented non-financial allowlist.
- **FR-006**: System MUST run a prohibited-advice check covering investment, tax, credit
  repair, debt strategy, and guaranteed-outcome claims.
- **FR-007**: System MUST verify that every product feature named in the output exists in
  the catalog.
- **FR-008**: System MUST run an urgency and pressure check, blocking scarcity and deadline
  language.
- **FR-009**: A guardrail block MUST degrade to the deterministic provider, never surface an
  error, and MUST be logged with the failing check and the offending span.
- **FR-010**: System MUST detect prompt-injection patterns in user input and log matches.
- **FR-011**: System MUST state explicitly when estimated savings do not exceed the
  subscription cost.
- **FR-012**: Generation MUST return a structured result: message, tool calls, evidence
  citations, guardrail verdicts, provider telemetry, and degradation status.
- **FR-013**: System MUST support multi-turn conversation with retained tool results.
- **FR-014**: System MUST include a required disclosure that figures are estimates based on
  the user's own recent activity.
- **FR-015**: Every check MUST be individually testable and individually reportable; a
  composite pass/fail is insufficient.

### Key Entities

- **Session**: one user, one tool surface, one value ledger, one conversation.
- **Agent turn**: input, tool calls, draft, guardrail verdicts, final message.
- **Guardrail verdict**: check name, pass/fail, offending span, severity.
- **Evidence citation**: a claim in the message linked to the tool call that supports it.
- **Agent result**: the structured output the API and evaluation harness both consume.

## Success Criteria

- **SC-001**: Zero grounding violations reach output across the golden case set. Absolute.
- **SC-002**: 100% of savings figures in output trace to an estimation-tool result.
- **SC-003**: 100% of prohibited-advice probes are declined.
- **SC-004**: 100% of injection probes fail to redirect a tool call or leak the prompt.
- **SC-005**: For users whose savings are below cost, ≥ 95% of outputs state it explicitly.
- **SC-006**: Median end-to-end generation under 20 seconds on the fast tier, 4 CPU cores.
- **SC-007**: Guardrail block rate is reported per run; a rate above 15% is treated as a
  prompt-quality regression requiring investigation.
- **SC-008**: Every generated message carries the required disclosure.

## Assumptions

- Tool results are trustworthy; they come from our own deterministic code, not a third
  party. Data-quality problems are 001's concern.
- English only for v1.
- The agent is advisory. It cannot mutate accounts, start subscriptions, or take any action
  — a deliberate limitation on blast radius, not an omission.
- The nudge is generated asynchronously and cached, so seconds of latency are acceptable.
- Guardrails are conservative by design. A blocked true statement is a cost we accept to
  make "no invented figure reaches a user" absolute.
