# Risk Register — Free2Genius

> Synthetic project. This register is modelled on what a real risk review would ask for. It
> does not claim to be a completed regulatory filing.

Every risk names either a **control** — something in the codebase that a test exercises — or
an explicit **acceptance**. A mitigation with no control is recorded as accepted risk, because
writing "we are careful about this" in a register and calling it mitigated is how controls
quietly stop existing.

Severity is the consequence if the risk occurs, not its likelihood.

---

## R1 — The agent states a fee, price or saving that is not real

**Severity**: Critical — a false financial claim to a consumer is a regulatory matter, not a
UX defect.

**Control**: Every numeric value returned by any tool is recorded in a per-session ledger, and
every number in the draft message must be a member of it. An unmatched figure blocks the
message and the turn degrades to the deterministic writer.

- Code: `f2g/agent/tools.py` (`dispatch` → `_record_values`), `f2g/agent/guardrails.py`
  (`check_numeric_grounding`)
- Test: `tests/test_guardrails.py`, and the CI gate in `f2g/evals/harness.py` fails the build
  on any violation
- Evidence it works: during development the 1.5B model fabricated seven dollar figures in one
  message (`$100`, `$26.50`, `$18`, `$62`, `$44.50`). All were blocked; the user would have
  received a correct templated message.

**Residual**: The check is set membership, so a *correct* number the model derived itself is
also blocked. Accepted deliberately — derivation belongs in Python, which is why
`estimate_savings` exists. The false-positive rate is monitored as `guardrail_block_rate`.

---

## R2 — The agent invents a product feature

**Severity**: High — promising a capability that does not exist is mis-selling.

**Control**: Catalog feature ids are an enum in the tool schema, and the grammar generator
turns enums into literal alternatives, so the decoder cannot emit a feature that does not
exist. A second check verifies any capitalised "Genius X" phrase against the catalog.

- Code: `f2g/llm/grammar.py`, `f2g/agent/guardrails.py` (`check_feature_names`)
- Test: `tests/test_llm_runtime.py::test_grammar_enumerates_enum_values`

---

## R3 — Prompt injection redirects the agent at another user's data

**Severity**: Critical — a data breach.

**Control**: Structural, not detective. `user_id` is bound at session construction and appears
in no tool schema, so the model has no way to express a request for another user. Injection
attempts are additionally detected and logged for review.

- Code: `f2g/agent/tools.py` (`ConciergeTools.__init__`), `f2g/agent/guardrails.py`
  (`check_injection`)
- Test: `tests/test_agent.py::test_identity_is_not_a_model_supplied_parameter`,
  `::test_injection_cannot_change_the_bound_user`

---

## R4 — The system persuades users to buy something that does not benefit them

**Severity**: High — mis-selling, and the failure mode a conversion-optimising system produces
by default.

**Control**: The value-fit gate. Estimated 90-day savings are computed deterministically from
the user's own fee history and compared to the subscription cost over the same window; users
below the threshold are suppressed regardless of predicted uplift. The gate runs *before* the
contact budget, so it cannot be masked by the budget having already excluded someone.

- Code: `f2g/ml/policy.py`, decision recorded per user with the figures behind it
- Test: `tests/test_policy.py::test_high_uplift_zero_fee_user_is_suppressed`
- Measured: mean estimated saving of contacted users $70.21 with the gate against $34.75
  without; the gate is the binding constraint, suppressing 7,530 of 12,000 candidates.

**Residual**: The margin (default 1.0) is a configurable number with an ethical edge. Lowering
it below 1.0 is a governance decision requiring sign-off, not a tuning exercise. It is logged
with every decision.

---

## R5 — Contact actively harms some users

**Severity**: High — a nudge that annoys a fee-stressed user is a real cost to them.

**Control**: Users with non-positive predicted uplift are excluded unconditionally. This is
the capability a propensity model does not have, and it is why uplift modelling was chosen
(ADR-002).

- Code: `f2g/ml/policy.py`
- Test: `tests/test_policy.py::test_never_contacts_negative_uplift`,
  `::test_all_negative_uplift_returns_empty_not_least_bad`

---

## R6 — A conversion win is bought with churn

**Severity**: High — the metric improves while users are worse off.

**Control**: 30-day retention among converters is a pre-declared guardrail, and the stopping
rules check for **harm before success**, so a conversion win cannot mask a retention breach
for as long as the win holds.

- Code: `f2g/experiment/analysis.py` (`stopping_verdict`)
- Test: `tests/test_experiment.py::test_harm_is_checked_before_success`

---

## R7 — A false positive is declared by repeatedly checking the dashboard

**Severity**: Medium — a programme ships on a result that is not real.

**Control**: Always-valid confidence sequences reported alongside the fixed-horizon interval.

- Code: `f2g/experiment/analysis.py`
- Test: `tests/test_experiment.py::test_null_experiment_repeated_looks`
- Measured: under no true effect, read 200 times, the naive fixed-horizon test declares a
  winner 49% of the time at a nominal 5%; the sequential bound holds at 3%.

---

## R7a — The agent gives financial, tax, investment or debt advice

**Severity**: High — advising a consumer on investments or debt strategy without authorisation
is a regulated-activity problem, not a tone problem.

**Control**: Scope is decided in the agent **before any model runs**. An out-of-scope question
is declined with a one-sentence redirect, without reading the user's account data at all. A
second, independent check scans generated output for advice patterns, negation-aware so that
the required disclaimer is not itself flagged.

- Code: `f2g/agent/scope.py` (input side), `f2g/agent/guardrails.py`
  (`check_prohibited_advice`, output side)
- Test: `tests/test_evals.py::test_out_of_scope_questions_are_declined`,
  `::test_refusal_touches_no_account_data`, `tests/test_guardrails.py`
- Evidence it was needed: the evaluation gate failed its first run with a refusal rate of
  **0.00**. Asked about bitcoin, the deterministic writer replied with a summary of the user's
  overdraft fees, because refusal had been left to the model and the template engine had no way
  to decline. Moving the decision into the agent fixed it for every provider at once.

**Residual**: Pattern-based scope detection will miss creative phrasings. The output-side
advice check is the second line, and the case set is extended whenever a miss is found.

---

## R8 — The system treats lower-income users differently

**Severity**: High — both a fairness and a regulatory concern.

**Control**: Contact rate, conversion, retention, mean uplift, mean estimated saving, and
per-band model discrimination and calibration are reported for every income band on every run.
The report separates gaps already in the population from gaps the policy introduces. A
parity-constrained selection mode is available with its cost stated.

- Code: `f2g/ml/policy.py` (`_fairness_table`), `f2g/ml/evaluate.py` (`slice_metrics`)
- Test: `tests/test_policy.py::test_fairness_table_separates_eligibility_from_policy`
- Measured: contact-rate gap 0.021 against a 0.10 tolerance.

**Residual**: Income band correlates with the latent segments by construction in this
synthetic population, so a gap is *expected* and the interesting question is whether the policy
widens it. On real data, which attributes may be monitored versus used is a legal question this
project does not answer.

---

## R9 — A user complains and we cannot explain why we contacted them

**Severity**: High — an unexplainable automated decision is a compliance failure regardless of
whether the decision was correct.

**Control**: A decision record is written at decision time for every user, contacted or not,
carrying the scores, the constraints evaluated, the binding constraint, the value-fit figures
and the model and prompt versions. Generations are logged with their tool calls, evidence and
per-check guardrail verdicts. `GET /audit/{user_id}` returns the whole record.

- Code: `f2g/api/store.py` (`record_decision`, `record_generation`, `explain`)
- Test: `tests/test_api.py::test_audit_returns_the_full_record`

---

## R10 — The model silently degrades after a data or prompt change

**Severity**: Medium.

**Control**: Model metrics, the fairness report and the agent evaluation regenerate on every
training run and are part of the merge gate. Guardrail block rate by check is monitored; above
0.15 it is treated as a prompt-quality regression. The model card is generated from current
output and a test asserts the committed copy matches.

- Code: `f2g/api/telemetry.py`, `f2g/governance/model_card.py`
- Test: `tests/test_governance.py`

---

## R11 — User financial data leaves our infrastructure

**Severity**: Critical.

**Control**: The default runtime is an open-weights model executed in-process from local
weights. No inference provider appears in the default configuration. A hosted provider exists
but is opt-in and logs a warning naming the egress when constructed.

- Code: `f2g/llm/runtime.py`, `f2g/llm/providers/anthropic_cloud.py`
- Test: `tests/test_llm_runtime.py::test_agent_module_imports_no_provider_implementation`

---

## R12 — The demonstration service is exposed publicly

**Severity**: Critical if it occurred — there is no authentication.

**Accepted, not mitigated.** This is a portfolio project. No auth, no rate limiting, no TLS
termination, no secret management. The absence is stated in the README, the OpenAPI
description, and the console footer rather than left for someone to discover. **Do not deploy
this service.**

---

## R13 — Synthetic results are mistaken for real ones

**Severity**: High — overstating provenance is a credibility failure and, in a hiring context,
a dishonesty one.

**Control**: Constitution Principle VIII. Every generated report, the model card, the API
description, every console view and every chart caption states that the data is synthetic.

**Residual**: Screenshots can be separated from their captions. Accepted.

---

## Risks accepted without a control

| Risk | Why accepted |
|---|---|
| No authentication (R12) | Demonstration scope; stated everywhere rather than hidden |
| No human review loop | Out of scope for a portfolio build; named as a limitation in the model card |
| Single-process, single-node service | Demonstration scale; the store and provider sit behind interfaces so the swap is bounded |
| No PII redaction layer | Unnecessary while inference is local; would be required before enabling the hosted provider, and is noted in ADR-001 |
| Fairness monitored on one axis | The synthetic population offers one; a real programme needs a legal decision first |
