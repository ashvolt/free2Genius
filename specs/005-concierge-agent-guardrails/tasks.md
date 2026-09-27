# Tasks: Genius Concierge Agent & Safety Guardrails

**Feature**: `005` · **Status**: Complete · **Verify**: `pytest tests/test_agent.py tests/test_guardrails.py -q`

## Phase 1: Tools (US1)
- [x] **T001** `ConciergeTools` bound to one `user_id` at construction
- [x] **T002** Six tools; identity absent from every schema
- [x] **T003** `dispatch` returning errors as data, never raising
- [x] **T004** Value ledger populated automatically by `dispatch`
- [x] **T005** `list_recent_fees` — totals cover all filtered events, not just the returned page
- [x] **T006** `estimate_savings` — deterministic, conservative, `net_position` never clamped
- [x] **T007** Structured `components` alongside the prose `basis`
- [x] **T008** Ledger scans numbers inside tool-returned strings
- [x] **T009** `provenance()` for the console's evidence chips

## Phase 2: Policy (US1, US2)
- [x] **T010** Versioned system prompt with hard rules
- [x] **T011** v1.3.0 — forbid rounding, after `$45` was written for `$44.97`

## Phase 3: Guardrails (US1, US2, US4)
- [x] **T012** Numeric grounding against ledger ∪ catalog
- [x] **T013** Percentages matched as either a rate or a percent
- [x] **T014** Safe bare integers, never exempting currency or percentages
- [x] **T015** Prohibited advice, **negation-aware**
- [x] **T016** Feature names checked against the catalog
- [x] **T017** Urgency and pressure
- [x] **T018** Coherence — repetition and lexical diversity
- [x] **T019** Disclosure (warn, not block)
- [x] **T020** Input injection detection, logged for review
- [x] **T021** Per-check reporting rather than a composite verdict
- [x] **T022** [P] Tests: each check for what it catches and what it must not

## Phase 4: The loop (US1, US3)
- [x] **T023** Bounded rounds with a forced answer at the cap
- [x] **T024** Repeat-call detection surfaced to the model
- [x] **T025** Guardrail block → deterministic writer → re-check → safe refusal
- [x] **T026** Deterministic writer completes the investigation before composing
- [x] **T027** `AgentResult` with evidence, verdicts, telemetry, degradation
- [x] **T028** Multi-turn chat

## Phase 5: Corrections from measurement
- [x] **T029** `scope.py` — refusal decided before inference, after the gate measured 0.00
- [x] **T030** `REQUIRED_EVIDENCE` precondition, after both tiers answered without looking
- [x] **T031** Coherence check, after a nine-fold repetition passed every safety check

## Outstanding

- [ ] **T032** Bring median generation latency within SC-006. Not met at 62–110 s; see the spec
  for the levers. Mitigated by async generation and caching, not fixed.
- [ ] **T033** Human review loop for generated messages — required before any real rollout,
  recorded as a limitation in the model card.

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 grounding violations reaching output | 0 | 0 | pass |
| SC-002 savings figures from the estimator | 100% | 100% | pass |
| SC-003 prohibited-advice refusal | 100% | 100% | pass (was 0.00) |
| SC-004 injection resistance | 100% | 100% | pass |
| SC-005 "not worth it" where applicable | ≥ 95% | 100% | pass |
| SC-006 median generation latency | < 20 s | 62–110 s | **NOT MET** |
| SC-007 block rate reported | yes | yes | pass |
| SC-008 disclosure present | 100% | 100% | pass |
