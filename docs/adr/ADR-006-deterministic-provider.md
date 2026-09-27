# ADR-006 — A deterministic non-LLM provider is a first-class runtime

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: C (Agentic Layer)

## Context

The agent needs to work when the model does not: no weights on disk, model server down,
inference timeout exceeded, repair loop exhausted, guardrail rejected the draft. In a
system that generates customer-facing financial explanations, "the LLM was unavailable so
we said nothing" is an acceptable outcome; "the LLM was unavailable so we said something
unchecked" is not.

The tempting shape is a mock in the test suite. That has a specific failure mode: mocks
drift from production behaviour, and the fallback path is exercised only in tests, so the
first time it runs in anger is the first time it has ever run in anger.

## Decision

**A `DeterministicProvider` is a production runtime, selectable in config, exercised in
CI, and the automatic degradation target for every failure path.**

It composes the same `ConciergeTools` results into a templated explanation. It has no
model, no sampling, and no network. Its output is grounded by construction: it can only
interpolate values that came from tool results, so it passes the numeric grounding check
trivially rather than by inspection.

It is not a stub. It is the floor of the product.

## Consequences

**Gained**

- The full system — tests, evaluation harness, API, front end, demo — runs on a clean
  checkout with no weights and no network. Anyone can clone and run it, which matters
  enormously for a portfolio project a reviewer will spend ten minutes on.
- Graceful degradation is a tested path, not a hope, because the fallback is the same code
  the test suite runs against every commit.
- It is the control arm in agent evaluation: the LLM must beat the template on
  helpfulness, and if it does not, the template ships. That framing keeps the LLM honest
  about the value it adds.
- Establishes the floor of output quality. The worst thing a user can receive is a
  correct, grounded, slightly wooden explanation.

**Paid**

- Two generation paths to maintain, and the templates must stay consistent with the
  prompt's claims about what the product says.
- Template output is visibly less fluent. Accepted: correctness outranks fluency, and the
  degradation is visible to us rather than to the user's bank balance.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Mock provider in tests only | Fallback path untested in production shape; drift guaranteed |
| Error out when the model is unavailable | Turns a model outage into a product outage for a non-critical surface |
| Retry until the model responds | Unbounded latency on a path with a user waiting |
| Cache the last LLM response per user | Stale financial claims are worse than wooden fresh ones — fee history moves |
