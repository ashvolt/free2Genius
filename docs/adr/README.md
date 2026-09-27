# Architecture Decision Records

Each record captures one decision that was not obvious, the options that were rejected,
and what the decision costs us. Format: lightweight Nygard ADR.

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-local-first-inference.md) | Local open-weights inference as the default runtime | Accepted |
| [002](ADR-002-uplift-over-propensity.md) | Uplift (T-learner) as the targeting signal, propensity as a diagnostic | Accepted |
| [003](ADR-003-runtime-enforced-tool-calling.md) | Tool calling enforced by the runtime, not delegated to the model's native API | Accepted |
| [004](ADR-004-value-fit-gate.md) | The agent's grounded savings estimate is a hard constraint inside the targeting policy | Accepted |
| [005](ADR-005-sequential-testing.md) | Sequential (always-valid) inference for the A/B test instead of fixed-horizon | Accepted |
| [006](ADR-006-deterministic-provider.md) | A deterministic non-LLM provider is a first-class runtime, not a test mock | Accepted |
| [007](ADR-007-numeric-grounding-ledger.md) | Grounding enforced by a numeric value ledger rather than by prompt instruction | Accepted |
