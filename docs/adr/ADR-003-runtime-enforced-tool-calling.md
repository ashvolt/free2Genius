# ADR-003 — Tool calling enforced by the runtime, not by the model's native API

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: C (Agentic Layer)

## Context

[ADR-001](ADR-001-local-first-inference.md) commits us to a 1.5–3B open-weights model.
Such models emit malformed tool calls at a rate that makes the naive loop unusable:
prose wrapped around JSON, trailing commas, invented parameter names, hallucinated tool
names, occasionally a plausible-looking *narration* of a tool call instead of a call.

Relying on the vendor's native tool-use API is not available to us in the same way a
hosted model offers it, and even where a chat template exposes one, it provides no
schema guarantee.

An agent whose loop breaks on 15% of turns cannot carry a product.

## Decision

**The runtime owns tool-call correctness.** Three layers, cheapest first:

1. **Grammar-constrained decoding.** The tool-call protocol is expressed as a GBNF
   grammar derived from the registered tool schemas, so `llama.cpp` cannot sample a token
   sequence that is not a syntactically valid call. Malformed JSON becomes unrepresentable
   rather than handled.
2. **Schema validation.** Every parsed call is validated against its JSON Schema:
   unknown tool, unknown parameter, wrong type, missing required field.
3. **Bounded repair loop.** A validation failure is returned to the model as a structured
   error observation naming exactly what was wrong, for at most `MAX_REPAIR_ATTEMPTS`
   rounds, then the turn degrades to the deterministic provider
   ([ADR-006](ADR-006-deterministic-provider.md)).

Providers that *do* offer native tool use may use it; the interface is the same, and the
validation and repair layers still run.

## Consequences

**Gained**

- Tool calling works on a 1.5B model, which is what makes local-first viable at all.
  The two decisions hold each other up.
- Reliability is measurable and attributable: the runtime records parse failures, schema
  failures, and repair attempts per turn, so "the model is bad at tools" becomes a number
  instead of a vibe.
- Provider-portable. Swapping in a hosted model does not change behaviour, because the
  contract is ours, not the vendor's.

**Paid**

- We maintain a grammar generator and a validator — real code with real tests, where a
  hosted API would have handed us a parameter.
- Constrained decoding costs a small amount of throughput.
- Grammar generation supports a deliberately narrow slice of JSON Schema (objects,
  strings with enums, integers, arrays of strings). Tool authors are constrained; this is
  documented as a limitation rather than hidden.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Trust the model's JSON, retry on failure | Measured failure rate too high; retries multiply latency without bounding the outcome |
| Regex extraction of JSON from prose | Fails silently on nested structures and produces plausible-but-wrong arguments — the worst failure mode in a financial context |
| One tool per turn, no arguments | Removes expressiveness the product needs (fee-type filters, feature-id lists) |
| Fine-tune for tool calling | Same reasoning as ADR-001: not yet earned, and constrained decoding solves it without a training pipeline |
