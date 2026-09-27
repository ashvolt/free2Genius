# ADR-007 — Grounding enforced by a numeric value ledger

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: C (Agentic Layer)

## Context

The single most damaging failure this system can produce is a confident, invented
financial figure: a fee the user never paid, a price that is not ours, a saving that does
not exist. In consumer finance that is not a bad UX outcome, it is a regulatory one.

The standard mitigations are all probabilistic. A firm system prompt reduces the rate. A
self-critique pass reduces it further. An LLM judge catches many instances. None of them
*bound* it, and all of them fail exactly when the model is confidently wrong — the case
that matters.

## Decision

**Every numeric value returned by any tool is recorded in a per-session ledger, and every
number in the generated message must be a member of that ledger, or the message is
blocked.**

Mechanics:

- `ConciergeTools.dispatch()` recursively walks each tool result and records every numeric
  leaf into `value_ledger`, rounded to 2 decimal places. Recording is automatic, so a new
  tool cannot forget to participate.
- The output guardrail extracts every currency and numeric token from the draft message.
- Each extracted value must match a ledger entry, a value derivable from the pricing
  catalog, or fall in a small allowlist of non-financial integers (dates, counts already
  present in tool output).
- An unmatched value is a **hard block**. The turn degrades to the deterministic provider.
  Nothing unaccounted reaches a user.

## Consequences

**Gained**

- Numeric hallucination moves from "unlikely" to "cannot reach the user". That is a
  categorically different claim, and it is the claim this project is built to be able to
  make.
- The property is testable, so it can gate CI: the golden case set asserts zero grounding
  violations, and a violation fails the build
  ([006](../../specs/006-agent-evaluation-harness/spec.md)).
- It is cheap. A set membership check per number, no second model call, no added latency —
  which is why it can run on every request in production rather than on a sample.
- It composes with weak models. A 1.5B model that occasionally invents a number is safe
  to deploy behind this gate, which is what makes [ADR-001](ADR-001-local-first-inference.md)
  defensible.

**Paid**

- False positives: a legitimately *derived* number (a sum the model computed correctly)
  is blocked. This is deliberate and is the reason `estimate_savings` exists — derivation
  belongs in Python. The guardrail's strictness is what forced the better tool design.
- Number extraction from prose needs care: percentages, ranges, written numerals,
  thousands separators. Covered by an explicit test corpus.
- A blocked message costs a generation. Tracked as `guardrail_block_rate`; a rising rate
  signals prompt drift and is a monitored signal rather than a silent cost.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Prompt instruction only | Unbounded failure rate; no enforcement; fails when the model is confident |
| LLM-as-judge on every response | Second inference on the hot path, and a probabilistic check on the one property that must be absolute. Retained for *quality* judging, where probabilistic is fine |
| Structured output with a fixed schema of pre-computed numbers | Considered seriously, and partly adopted — the deterministic provider works this way. Rejected as the sole approach because it removes the model's ability to explain, which is the product |
| Post-hoc audit sampling | Detects breaches after users have seen them |
