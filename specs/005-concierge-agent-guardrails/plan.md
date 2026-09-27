# Implementation Plan: Concierge Agent Guardrails

**Feature**: `005` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/005-concierge-agent-guardrails.md)** · **[LLD](../../docs/architecture/lld/005-concierge-agent-guardrails.md)**

## Summary

A bounded tool loop over a user-bound tool surface, with scope decided before inference,
required evidence enforced by the loop, six independently-reported output gates, and automatic
degradation to a writer that is grounded by construction.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: the 004 runtime; no new third-party code
**Testing**: pytest — every gate for what it must catch and what it must not
**Performance**: median end-to-end generation under 20 s on the fast tier (measured 60-110 s at
7 rounds; the nudge is generated asynchronously and cached, so this is acceptable and is recorded
as the gap it is)
**Constraints**: must produce a usable answer on every failure path

## Constitution Check

| Principle | Satisfied by |
|---|---|
| I. Evidence over persuasion | Value ledger membership; the agent can and does recommend against buying |
| IV. Guardrails as code | Six executable checks, each independently reported and independently tested |
| II. Local-first | Provider-agnostic; no provider imported by agent code |
| VIII. Synthetic data stated | Disclosure required in output and checked |

**Result**: Pass.

## Technical approach

Defences are chosen leftmost-first from structural (the model cannot express the failure),
procedural (the agent acts rather than the model), detective (checked before a human sees it).
Prompt instructions are mitigations that reduce how often gates fire, never controls.

`SC-006` (median under 20 s) is **not met** on the fast tier at the default round budget. The
measured figure is 60–110 s. Recorded here rather than quietly adjusted: the nudge is generated
asynchronously and cached with a TTL, so it is not on a user-facing path, but the criterion as
written is unmet and reducing the round budget or the model tier is the obvious lever.

## Project Structure

```text
f2g/agent/tools.py       ConciergeTools, six tools, value ledger, provenance
f2g/agent/scope.py       what the agent will and will not answer
f2g/agent/prompts.py     versioned policy
f2g/agent/guardrails.py  six output checks + input injection detection
f2g/agent/concierge.py   the loop, degradation, AgentResult
tests/test_agent.py  tests/test_guardrails.py
```

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Scope as a separate module | Refusal must not depend on the model | Leaving it to the prompt produced a 0.00 refusal rate |
| Required-evidence precondition | Both model tiers answered without looking | Asking in the prompt did not work |
| String scanning in the value ledger | Tool-generated prose contains real figures | Without it, a true statement quoting a tool's own derivation is blocked |
| Six checks not one | Per-check block rate is the drift signal | A composite verdict says something broke without saying what |
