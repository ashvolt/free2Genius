# Implementation Plan: Local Llm Runtime

**Feature**: `004` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/004-local-llm-runtime.md)** · **[LLD](../../docs/architecture/lld/004-local-llm-runtime.md)**

## Summary

A provider protocol with four backends, and three reliability layers that make tool calling
work on a 1.5B model: a GBNF grammar generated from the tool schemas, schema validation with
specific repair instructions, and a bounded repair loop that raises rather than guessing.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: llama-cpp-python (optional), httpx, anthropic (optional)
**Models**: Qwen2.5-1.5B and 3B Instruct, Q4_K_M GGUF, ~2.9 GB, gitignored
**Testing**: pytest — grammar generation, every validation failure mode, repair, substitutability
**Performance**: median tool-call latency under 4 s on the fast tier, 4 CPU cores (measured ~2 s)
**Constraints**: must run with no network and no API key; deterministic at temperature zero

## Constitution Check

| Principle | Satisfied by |
|---|---|
| II. Local-first inference | Default provider is in-process; hosted is opt-in and logs its egress |
| IV. Guardrails as code | Grammar and validation are executable, not prompt instructions |
| VI. Reproducible | Fixed seed, temperature zero, grammar deterministic in the tool list |
| Tech constraint: no vendor tool-use API | Correctness is the runtime's responsibility |

**Result**: Pass.

## Technical approach

The `decide`/`complete` split is what makes a small model usable: constrained decoding for the
~20-token action choice, unconstrained generation for prose. Asking a 1.5B model to emit long
prose inside a grammar-constrained JSON string fails often.

Grammar generation covers a deliberately narrow JSON Schema subset and raises
`GrammarUnsupported` at registration rather than at decode, so a tool author finds out when they
add the tool.

## Project Structure

```text
f2g/llm/base.py         protocol, dataclasses, typed exceptions
f2g/llm/grammar.py      GBNF generation
f2g/llm/validation.py   parse, validate, repair instructions
f2g/llm/runtime.py      factory, ToolCallRuntime, degradation
f2g/llm/providers/      llamacpp · openai_compat · deterministic · anthropic_cloud
tests/test_llm_runtime.py
```

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Grammar generation | Malformed tool calls are otherwise routine on small models | Retrying on parse failure multiplies latency without bounding the outcome |
| Four providers | The abstraction is only credible if genuinely different backends plug in | Two would leave the seam untested |
| decide/complete split | A single constrained call cannot produce good prose | One call is simpler and produces escaped, truncated output |
| Abandon-on-timeout | The binding offers no cancellation | Claiming cancellation we do not have would be worse than documenting it |
