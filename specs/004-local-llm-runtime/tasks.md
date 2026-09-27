# Tasks: Local LLM Runtime & Provider Abstraction

**Feature**: `004` · **Status**: Complete · **Verify**: `pytest tests/test_llm_runtime.py -q`

## Phase 1: Contract (US3)
- [x] **T001** `LLMProvider` protocol — `decide` / `complete` / `health`
- [x] **T002** `ToolSchema`, `ToolCall`, `Decision`, `Completion`, `Telemetry`
- [x] **T003** Typed exceptions: `ProviderUnavailable`, `GenerationTimeout`, `RepairBudgetExhausted`, `GrammarUnsupported`
- [x] **T004** Model `final_answer` as a pseudo-tool so one grammar covers both outcomes

## Phase 2: Grammar (US2)
- [x] **T005** Generate GBNF from tool schemas
- [x] **T006** Enum → literal alternatives (makes invented features unrepresentable)
- [x] **T007** Require all keys, permit `null` for optional ones, avoiding a power-set grammar
- [x] **T008** Raise `GrammarUnsupported` at registration for unsupported constructs
- [x] **T009** Fingerprint grammars for caching and reproducibility
- [x] **T010** [P] Tests: enums present, determinism, rejection of nested objects and empty tool sets

## Phase 3: Validation and repair (US2)
- [x] **T011** Tolerant parse: recover the outermost brace span from prose-wrapped output
- [x] **T012** Validate tool existence, parameter names, types, required fields, enums, array items
- [x] **T013** Typed `FailureReason` per rejection
- [x] **T014** Render specific repair instructions naming the offending key or value
- [x] **T015** Map `null` to absent so callers get clean kwargs
- [x] **T016** Bounded repair loop that raises on exhaustion
- [x] **T017** `repeated_call` detection
- [x] **T018** [P] Tests: 9 failure modes, prose recovery, repair, exhaustion

## Phase 4: Providers (US1, US3, US4)
- [x] **T019** `LlamaCppProvider` — in-process GGUF, model cache, serialised access
- [x] **T020** Wall-clock timeout via an executor; document that it abandons rather than cancels
- [x] **T021** `repeat_penalty` after observing degenerate repetition
- [x] **T022** `OpenAICompatProvider`
- [x] **T023** `DeterministicProvider` — fixed script, composes from observations
- [x] **T024** `AnthropicProvider` — opt-in, logs its egress at construction
- [x] **T025** `build_provider` factory failing at construction, not first inference
- [x] **T026** `observations.py` — one wire format both writer and reader depend on
- [x] **T027** [P] Tests: unknown provider, deterministic availability, substitutability

## Phase 5: Corrections from measurement
- [x] **T028** Added `repeat_penalty` and a tighter answer budget after a nine-fold repetition loop
- [x] **T029** Rewrote the judge grammar one-rule-per-line after `expecting name` silently disabled every score

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 tool-call syntactic validity | 100% | 100% under grammar | pass |
| SC-002 tool selection reported per tier | reported | reported; both tiers under-investigate | pass (metric is honest, result is weak) |
| SC-003 median tool-call latency, fast tier | < 4 s | ~2 s | pass |
| SC-004 deterministic provider latency | < 50 ms | < 10 ms | pass |
| SC-005 failure modes degrade | all | all | pass |
| SC-006 provider swap is config-only | yes | asserted by test | pass |
| SC-007 repeated requests identical | yes | yes at temperature 0 | pass |
