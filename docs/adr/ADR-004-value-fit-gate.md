# ADR-004 — The agent's grounded savings estimate is a hard constraint inside the targeting policy

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: B + C (the coupling)

## Context

Uplift targeting answers "who is most movable". It does not answer "who *should* be
moved". Those come apart in an uncomfortable way: the most movable users include people
who can be talked into a $14.99/month subscription that will save them nothing.

Contacting them is optimal under the conversion metric and indefensible under any other
reading. It also shows up later as churn — which is exactly what the 30-day retention
guardrail detects, *after* we have already charged people.

A guardrail that catches the harm after it occurs is worth having. A constraint that
prevents it is worth more.

## Decision

**The agent's `estimate_savings` output is a hard eligibility constraint in the targeting
policy, evaluated before contact.**

For every user the policy would otherwise nudge, the concierge tool layer computes — from
that user's own 90-day fee history, deterministically, in Python — the estimated saving
and the subscription cost over the same window. If

```
estimated_saving_90d < genius_price_90d × VALUE_FIT_MARGIN
```

the user is **suppressed regardless of predicted uplift**.

This inverts the usual dependency. The agent is normally a downstream consumer of the
model's decision; here its grounded arithmetic is an upstream veto over that decision.

## Consequences

**Gained**

- The system **cannot** reach its conversion target by mis-selling, because the honesty
  check is inside the decision rather than beside it. This is a structural property, not
  a policy anyone has to remember to apply.
- The suppression set is auditable: every suppressed user has a stored reason and the
  numbers behind it. "Why didn't this user get contacted?" has a factual answer.
- It creates an honest, defensible answer to the interview question *"how do you stop a
  growth model from harming users?"* — the answer is a constraint with a test, not a
  principle in a slide.
- Retention rises as a side effect rather than as a separate initiative, because the
  users most likely to churn are the ones the gate removes.

**Paid**

- Reachable conversion volume falls. This is the correct trade and is stated up front in
  the experiment design, with the expected magnitude, so nobody discovers it as a
  surprise mid-test.
- Couples domains B and C: the policy cannot be evaluated without the tool layer. Managed
  by depending on `ConciergeTools` (deterministic, no LLM) rather than on the agent
  itself — so no model inference is needed to compute eligibility.
- `VALUE_FIT_MARGIN` is a business lever with an ethical edge. It is configured in one
  place, defaulted conservatively at 1.0, logged with every decision, and never tuned to
  hit a number.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Retention guardrail only | Detects harm after users have been charged; reactive by construction |
| Value fit as a model feature | A feature can be traded off against other features. A constraint cannot. That difference is the whole point |
| Post-hoc filter on the generated message | Too late: the user has already been selected and the impression already spent |
| Let the LLM judge value fit | Delegates a money decision to a 3B model's arithmetic, which Principle I forbids outright |
