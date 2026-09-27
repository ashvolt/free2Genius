# ADR-001 — Local open-weights inference as the default runtime

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: C (Agentic Layer)

## Context

The concierge agent reads a user's transactions, cash-advance history, and fee events —
among the most sensitive data a consumer fintech holds. Two runtime options exist:

1. A hosted frontier model (Claude, GPT, Gemini). Best instruction-following, best tool
   use, zero infrastructure, per-token cost, and user financial data leaves our trust
   boundary on every request.
2. A quantized open-weights model running in our own process. Weaker instruction
   following, some engineering to make reliable, no marginal cost, and no egress.

The decision is not primarily about model quality. It is about which conversation we
want to have with a security reviewer, and what the evaluation suite is allowed to cost.

## Decision

**Open-weights local inference is the default and the only configuration required to run
the system.** Qwen2.5-1.5B-Instruct (fast tier) and Qwen2.5-3B-Instruct (quality tier),
Q4_K_M-quantized GGUF, executed in-process via `llama.cpp`.

Hosted providers are supported behind the same `LLMProvider` interface as an explicitly
configured escalation path. Selecting one is a config change and touches no agent logic,
no tool, and no guardrail.

## Consequences

**Gained**

- No user financial attribute crosses a network boundary in the default configuration.
  "The data never left" is a one-line answer to the hardest question in the review.
- Marginal inference cost is zero, so the full agent evaluation suite can run on every
  commit. This is what makes the zero-grounding-violation CI gate affordable, and that
  gate is the project's strongest safety claim. A metered API would have forced us to
  sample the eval set, and a sampled safety gate is not a gate.
- Reproducible evaluation: fixed weights, `temperature=0`, fixed seed. The same golden
  case produces the same output next month. Hosted models are updated beneath you.
- Cost per nudge is bounded by hardware, which makes unit economics legible in a way a
  per-token bill does not.

**Paid**

- A 1.5–3B model does not follow instructions like a frontier model. This is the real
  cost, and it is paid down deliberately in [ADR-003](ADR-003-runtime-enforced-tool-calling.md):
  reliability becomes the runtime's responsibility rather than the model's.
- CPU latency is seconds, not milliseconds. Acceptable because the nudge is generated
  asynchronously and cached; it is not on a page-load path.
- Model weights (~2.9 GB) are an operational artifact to distribute. They are gitignored
  and fetched by `make models`.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Hosted frontier model as default | Egress of financial PII; per-commit eval cost; non-reproducible outputs across silent model updates |
| Fine-tuning a small model for this task | Premature. Prompt + tools + guardrails have not been exhausted, and fine-tuning would bind us to a data collection process that does not exist yet |
| 7B+ local model | Does not fit CPU latency budget on commodity hardware; 3B clears the quality bar once tool calling is runtime-enforced |
| Rules engine, no LLM | Cannot produce per-user natural-language explanation, which is the product. Retained as the *fallback* provider — see [ADR-006](ADR-006-deterministic-provider.md) |
