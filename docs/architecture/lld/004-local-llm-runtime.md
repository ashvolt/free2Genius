# LLD 004 — Local LLM Runtime & Provider Abstraction

**Domain**: C · **HLD**: [004](../hld/004-local-llm-runtime.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/llm/base.py` | Protocol, dataclasses, the typed exception hierarchy |
| `f2g/llm/grammar.py` | GBNF generation from tool schemas |
| `f2g/llm/validation.py` | Parse, validate, and render repair instructions |
| `f2g/llm/runtime.py` | Provider factory, `ToolCallRuntime`, repair loop, degradation |
| `f2g/llm/observations.py` | The one wire format for tool results in the message history |
| `f2g/llm/providers/*.py` | Four backends |

## Signatures

```python
# base.py
FINAL_ANSWER = "final_answer"
class LLMError(RuntimeError); ProviderUnavailable; GenerationTimeout
class RepairBudgetExhausted(LLMError): attempts: int; failures: list[str]
class GrammarUnsupported(LLMError)

@dataclass(frozen=True) class ToolSchema:   name, description, input_schema
@dataclass class ToolCall:  name, arguments; def signature() -> str
@dataclass class Telemetry: provider, model, prompt_tokens, completion_tokens,
                            latency_s, repair_attempts, parse_failures,
                            schema_failures, degraded, degraded_reason
@dataclass class Decision:  tool_call, is_final, telemetry, raw
@dataclass class Completion: text, telemetry

class LLMProvider(Protocol):
    def decide(messages, tools, *, temperature, seed, max_tokens) -> Decision
    def complete(messages, *, temperature, seed, max_tokens) -> Completion
    def health() -> dict

# grammar.py
def build_tool_grammar(tools: list[ToolSchema]) -> str
def grammar_fingerprint(grammar: str) -> str

# validation.py
class FailureReason(str, Enum):
    NOT_JSON | NOT_AN_OBJECT | MISSING_TOOL_KEY | UNKNOWN_TOOL |
    ARGUMENTS_NOT_OBJECT | UNKNOWN_PARAMETER | MISSING_REQUIRED |
    WRONG_TYPE | NOT_IN_ENUM
def parse_and_validate(raw, tools) -> tuple[ToolCall | None, ValidationFailure | None]

# runtime.py
def build_provider(name=None, *, tier=None) -> LLMProvider
class ToolCallRuntime:
    def decide(messages, tools, **kw) -> RuntimeResult          # may raise
    def decide_or_degrade(messages, tools, **kw) -> RuntimeResult
    def complete_or_degrade(messages, **kw) -> Completion
def repeated_call(call, previous) -> bool
```

## Grammar generation

Supported JSON Schema subset — anything else raises `GrammarUnsupported` **at registration**:

| Construct | GBNF |
|---|---|
| `string` with `enum` | union of quoted literals |
| `string` | generic JSON string rule |
| `integer` / `number` / `boolean` | numeric / literal rules |
| `array` of the above | `"[" ws (item (ws "," ws item)*)? ws "]"` |
| `object` with no properties | `"{" ws "}"` |
| nested object with properties | **rejected** — flatten the tool's arguments |

Generated shape:

```text
root ::= ws (call-get-account-summary | call-list-recent-fees | … | call-final-answer) ws
call-list-recent-fees ::= "{" ws "\"tool\"" ws ":" ws "\"list_recent_fees\"" ws "," ws
                          "\"arguments\"" ws ":" ws "{" ws
                          "\"fee_type\"" ws ":" ws list-recent-fees-prop-fee-type ws "," ws
                          "\"limit\"" ws ":" ws list-recent-fees-prop-limit ws "}" ws "}"
list-recent-fees-prop-fee-type ::= ("\"instant_transfer\"" | "\"overdraft\"") | null
estimate-savings-feature-ids-item ::= "\"budget_coach\"" | "\"instant_delivery\""
                                    | "\"overdraft_shield\"" | "\"smart_savings\""
                                    | "\"subscription_watch\""
```

Two properties worth noting:

**All declared keys are required, optional ones accept `null`.** A grammar allowing every subset
of optional keys is the power set, which explodes and which small models navigate badly. The
validator maps `null` back to "absent", so callers see a clean kwargs dict.

**Enums become literal alternatives.** This is the strongest guarantee in the module: the last
rule above means a hallucinated catalog feature is *unrepresentable*, not caught downstream.

`build_tool_grammar` is deterministic in the tool list, so generation stays reproducible at
temperature zero and the compiled grammar can be cached by fingerprint.

## GBNF gotcha, recorded because it cost time

**Every rule must fit on one logical line.** A multi-line rule body parses as a new rule name
and fails with `expecting name`. The judge grammar was first written as one multi-line `root`
rule; it failed to compile, and because the judge degrades gracefully, every score silently
became "unavailable" rather than raising. Composed from small named rules now.

## The repair loop

```python
for attempt in range(max_repair_attempts + 1):
    decision = provider.decide(working, tools)
    if decision.is_final or decision.tool_call:
        return RuntimeResult(decision, telemetry, repair_log)
    _, failure = parse_and_validate(decision.raw, tools)
    working += [{"role": "assistant", "content": decision.raw},
                {"role": "user", "content": failure.as_repair_prompt()}]
raise RepairBudgetExhausted(attempts, repair_log)
```

The repair message is the part that matters. `"Invalid arguments"` teaches a 1.5B model
nothing. `"Parameter 'fee_kind' is not recognised for 'list_recent_fees'. Valid parameters:
fee_type, limit."` is usually fixed in one attempt.

## Provider details

| Provider | Grammar | Timeout | Notes |
|---|---|---|---|
| `LlamaCppProvider` | yes | executor + wall clock, abandons | `repeat_penalty=1.18`; model cached per (path, ctx, threads, seed) |
| `OpenAICompatProvider` | no | httpx | Validation and repair do all the work; loss is measured, not assumed |
| `DeterministicProvider` | n/a | <50 ms | Fixed script, composes from observations |
| `AnthropicProvider` | no | SDK | Logs an egress warning at construction |

`repeat_penalty` exists because of a measured failure: at the library default, the 1.5B model's
final answer degenerated into nine repetitions of one paragraph.

## Observation wire format

```text
OBSERVATION <tool_name>: <json>
```

One module owns it (`observations.py`) because both the agent (which writes it) and the
deterministic provider (which reads it back) depend on the shape. Duplicating it as a convention
in two places is how it drifts.

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_grammar_enumerates_enum_values` | Invented features are unrepresentable |
| `test_grammar_rejects_unsupported_schema_at_registration` | Fail early, not at decode |
| `test_grammar_is_deterministic` | Reproducibility at temperature zero |
| `test_validation_rejects_with_specific_reason` (9 cases) | Every failure mode names itself |
| `test_nulls_are_treated_as_absent` | The grammar/validator contract |
| `test_repair_loop_recovers_after_one_bad_output` | Repair works |
| `test_repair_budget_exhaustion_raises_rather_than_guessing` | No best guesses |
| `test_exhaustion_degrades_instead_of_failing` | The degradation path |
| `test_unknown_provider_fails_at_construction_not_first_call` | Startup failure |
| `test_agent_module_imports_no_provider_implementation` | The abstraction is real, not decorative |
