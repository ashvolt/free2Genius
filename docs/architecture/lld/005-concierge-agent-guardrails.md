# LLD 005 — Genius Concierge Agent & Safety Guardrails

**Domain**: C · **HLD**: [005](../hld/005-concierge-agent-guardrails.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/agent/tools.py` | `ConciergeTools`, six tools, the value ledger, provenance |
| `f2g/agent/scope.py` | What the agent will and will not answer |
| `f2g/agent/prompts.py` | Versioned system prompt and task text |
| `f2g/agent/guardrails.py` | Six output checks plus input injection detection |
| `f2g/agent/concierge.py` | The bounded loop, degradation, `AgentResult` |

## Signatures

```python
# tools.py
class ConciergeTools:
    def __init__(self, user_id: str)          # raises KeyError on unknown user
    value_ledger: set[float]                  # populated automatically by dispatch
    call_log: list[dict]
    def dispatch(name, arguments) -> dict     # errors returned as data, never raised
    def provenance(value: float) -> list[str]
TOOL_SCHEMAS: list[dict]                      # the only tools that exist
TOOL_NAMES: set[str]

# scope.py
def classify(user_text) -> ScopeVerdict       # in_scope | out_of_scope | off_topic

# guardrails.py
def run_output_guardrails(text, value_ledger, *, require_disclosure=True) -> GuardrailReport
def run_input_guardrails(user_text) -> GuardrailReport
OUTPUT_CHECKS = ("numeric_grounding", "prohibited_advice", "feature_names",
                 "no_pressure", "coherence", "disclosure")

# concierge.py
REQUIRED_EVIDENCE = ("list_recent_fees", "estimate_savings")
class ConciergeAgent:
    def generate_nudge() -> AgentResult
    def chat(user_message, history=None) -> AgentResult
```

## The value ledger

```python
def _record_values(self, obj):
    bool  -> ignored            # True is not 1
    number-> ledger.add(round(v, 2))
    str   -> every numeric literal inside it  (see below)
    dict/list -> recurse
```

Called automatically from `dispatch`, so a newly added tool cannot forget to participate.

**Numbers inside returned strings are recorded too**, and that needs justifying. Every string in
a tool result is produced by our own Python from the user's real data — never by the model — so
a figure the model quotes out of a tool's own explanation *is* grounded, and blocking it would
be a false positive. The model still cannot introduce a number of its own, because it cannot
write into a tool result.

This was found the hard way: `estimate_savings` originally reported its derivation only as prose
(`"3 overdraft fees totalling $102.00"`), so `$102.00` never entered the ledger and the
guardrail correctly blocked a true statement. The fix was both a structured `components` field —
tools return data, not prose — and string scanning as a backstop.

## Numeric grounding

```python
allowed = {round(v, 2) for v in value_ledger} | catalog_values()

$X    -> must be in allowed
X%    -> X or X/100 must be in allowed     # a rate may be stored as 0.70 or 70
bare  -> allowed, unless it is a "safe bare integer"
```

`_SAFE_BARE_INTEGERS = {0..12, 14, 15, 20, 24, 30, 31, 60, 90, 365}` — counts, ordinals and
window lengths. **Currency and percentages are never exempted by this list**; only undecorated
integers are.

`catalog_values()` admits the monthly price, free-tier fee amounts, and each feature's
`unit_saving` / `coverage_rate` / `assumed_cancel_rate` (and those rates × 100), so pricing is
sayable even with an empty session ledger.

### Deliberate false positives

| Model writes | Truth | Verdict | Why |
|---|---|---|---|
| `$45` | `$44.97` | **blocked** | Rounding is indistinguishable from fabrication by inspection |
| `$79.90` (correct sum of two fees) | correct | **blocked** | Derivation belongs in Python |

Both are fixed at the cause rather than by loosening the check: the prompt forbids rounding
(v1.3.0) and `estimate_savings` does the arithmetic.

## Negation-aware advice checking

```python
for pattern, label in _ADVICE_PATTERNS:
    for m in re.finditer(pattern, lowered):
        if _is_negated(lowered, m.start()):   # 40-char lookback for not/no/never/cannot/…
            continue
        -> BLOCK
```

The catalog's required disclosure reads *"They are not guarantees of future savings"*, and a
bare `/guarantee/` pattern blocked the agent's own disclaimer — the guardrail rejecting the
sentence that makes the output compliant. A check that fires on negated text is not
conservative, it is broken: it blocks correct output and trains operators to ignore it.

## Coherence

```python
identical line (≥40 chars) appearing > 2 times          -> BLOCK
len(words) > 120 and unique/total < 0.28                -> BLOCK
```

Observed: the 1.5B model produced one correct, fully grounded paragraph and repeated it nine
times. **Every safety check passed** — the numbers were real, the advice clean, no pressure —
because the output was safe and useless. Safety guardrails do not cover usability, so this is
its own check, and it blocks because the templated floor is better for a user than a message
that repeats itself nine times.

## The loop

```python
for round in 1..max_rounds:                 # default 7
    decision = runtime.decide_or_degrade(messages, schemas)
    if final:
        missing = REQUIRED_EVIDENCE - gathered
        if missing and not pushed_back:
            pushed_back = True
            messages += ["you must call: " + missing]   # ask once, model may choose better args
            continue
        break
    if repeated_call(call, made):
        messages += ["you already called that; choose another tool or answer"]
        continue
    observation = tools.dispatch(call.name, call.arguments)
    messages += [assistant(raw), user(OBSERVATION ...)]
else:
    messages += ["you have used all available tool calls; answer now"]

for tool in REQUIRED_EVIDENCE - gathered:   # enforce, don't request
    forced.append(tool); dispatch(tool, defaults)
```

## Guardrail outcome handling

```python
report = run_output_guardrails(draft, ledger)
if report.blocked:
    draft = deterministic_writer(messages)     # completes the investigation first
    report = run_output_guardrails(draft, ledger)
    degraded = True
    if report.blocked:                          # the floor itself failed
        draft = "We could not put together a reliable summary…"
        report = run_output_guardrails(draft, ledger, require_disclosure=False)
```

The deterministic writer **finishes the tool script before composing**. Without that it would
report "no fees were charged" for a user who simply had not been looked at — a false statement
to someone about their own money. Absence of a tool call is not absence of fees.

## Evidence provenance

For each `$X` / `X%` in the final message, `ConciergeTools.provenance(value)` re-walks each
logged tool result and returns the tools whose output contained it. Powers the console's
clickable chips. A figure with empty provenance renders in the error style — visible rather than
silently plausible.

## Measured behaviour

| Observation | Tier | Outcome |
|---|---|---|
| Seven fabricated dollar figures in one message | 1.5B | All blocked; user got the templated message |
| Nine-fold paragraph repetition | 1.5B | Caught by coherence after it passed every safety check |
| Answered from `get_account_summary` alone, claiming "no significant fees" for a user with $136.93 | 3B | Fixed by the required-evidence precondition |
| `$45` written for `$44.97` | both | Blocked; prompt v1.3.0 forbids rounding |

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_identity_is_not_a_model_supplied_parameter` | The security boundary |
| `test_injection_cannot_change_the_bound_user` | Injection has nothing to redirect |
| `test_every_figure_traces_to_a_tool_call` | The chip contract |
| `test_required_evidence_is_always_gathered` | The precondition |
| `test_disclaimer_is_not_a_guarantee` | The negation regression |
| `test_rounding_is_treated_as_fabrication` | The deliberate false positive |
| `test_repetition_loop_blocked` | Coherence |
| `test_refusal_touches_no_account_data` | Scope decided before inference |
| `test_zero_fee_user_is_told_it_is_not_worth_it` | The constitutional requirement |
| `test_unknown_tool_is_an_error_result_not_an_exception` | Errors are data |
