# Feature Specification: Local LLM Runtime & Provider Abstraction

**Feature ID**: `004` · **Domain**: C — Agentic Layer
**Created**: 2026-09-27 · **Status**: Implemented · **Converged**: 2026-09-27
**Depends on**: —
**Input**: "Run an agent on open-weights models inside our own boundary, and make tool
calling reliable enough to build a product on even though the model is small."

## Why this feature exists

We committed to local open-weights inference so that user financial data never leaves our
trust boundary and so the evaluation suite is free to run on every commit
([ADR-001](../../docs/adr/ADR-001-local-first-inference.md)).

That commitment has a bill attached. A 1.5–3B instruction-tuned model does not emit clean
tool calls the way a frontier model does. Measured on this repository's smoke test, the
1.5B model produced syntactically valid JSON under grammar constraint but selected the
*wrong tool* for a plainly-worded request. Without help, the naive loop breaks often enough
to be unusable.

This feature pays that bill. **Reliability is the runtime's responsibility, not the
model's** ([ADR-003](../../docs/adr/ADR-003-runtime-enforced-tool-calling.md)). It also
isolates provider choice behind one interface, so the agent, its tools and its guardrails
never learn which model is underneath.

## User Scenarios & Testing

### User Story 1 — An engineer runs the agent with no network and no API key (Priority: P1)

Point the runtime at a local GGUF file and get chat completions and tool calls in-process.

**Why this priority**: It is the default configuration and the entire premise.

**Independent Test**: With the network disabled, load a local model, request a completion,
and receive text. Then request a tool call and receive a validated structured call.

**Acceptance Scenarios**:

1. **Given** a GGUF model on disk, **When** the runtime is constructed, **Then** it loads
   without network access.
2. **Given** a loaded model and a tool schema set, **When** a tool call is requested,
   **Then** the returned call names a registered tool and validates against its schema.
3. **Given** a fixed seed and zero temperature, **When** the same request runs twice,
   **Then** the outputs are identical.
4. **Given** no model file present, **When** the runtime is constructed, **Then** it fails
   with a message naming the expected path and the command that fetches it.

### User Story 2 — Malformed model output never reaches the agent (Priority: P1)

The runtime constrains, validates, and repairs. The agent receives either a valid tool call
or an explicit, typed failure — never a half-parsed guess.

**Why this priority**: A plausible-but-wrong tool call in a financial context is worse than
an error, because it produces confident output from wrong inputs.

**Independent Test**: Feed the validator hand-written malformed outputs — prose-wrapped
JSON, unknown tool, unknown parameter, wrong type, missing required field — and confirm each
is rejected with a specific reason and each triggers exactly one repair attempt.

**Acceptance Scenarios**:

1. **Given** a request with registered tools, **When** decoding is grammar-constrained,
   **Then** the raw output parses as JSON without repair on the first attempt.
2. **Given** a call naming an unregistered tool, **When** validated, **Then** it is rejected
   with reason `unknown_tool` and the model receives the list of valid names.
3. **Given** a call with a parameter absent from the schema, **When** validated, **Then** it
   is rejected with reason `unknown_parameter` naming the offending key.
4. **Given** repeated invalid calls, **When** the repair budget is exhausted, **Then** the
   runtime raises a typed exhaustion error rather than returning a best guess.
5. **Given** any turn, **When** it completes, **Then** parse failures, schema failures and
   repair attempts are recorded as telemetry.

### User Story 3 — Providers are interchangeable without touching agent code (Priority: P1)

Switch between in-process llama.cpp, an OpenAI-compatible endpoint (vLLM, Ollama,
LM Studio, TGI), a hosted frontier model, and the deterministic template provider, by
configuration alone.

**Why this priority**: It is what makes the local-first commitment a *choice* rather than a
constraint, and it is what lets the same agent be demonstrated on a laptop and a server.

**Independent Test**: Run the identical agent conversation against two providers and confirm
the agent, tool and guardrail code paths are byte-identical, differing only in configuration.

**Acceptance Scenarios**:

1. **Given** a provider name in configuration, **When** the runtime is built, **Then** the
   corresponding provider is constructed and no agent code references the provider type.
2. **Given** an OpenAI-compatible endpoint URL, **When** a completion is requested, **Then**
   it is served over that endpoint with the same return shape as the local provider.
3. **Given** an unknown provider name, **When** the runtime is built, **Then** it fails at
   construction naming the supported providers, not at first inference.
3a. **Given** the *default* provider is unavailable (no weights on a fresh clone), **When** the
   runtime is built without an explicit provider name, **Then** it falls back to the
   deterministic provider with a warning rather than raising. *(Added after a fresh-clone
   check: `POST /agent/nudge` with no provider returned a 500. Nobody chose the default
   explicitly, and ADR-006 makes the deterministic provider the degradation target for every
   failure path. An **explicitly** named unavailable provider still raises — substituting
   silently would let a caller believe they were measuring a model they were not.)*
4. **Given** any provider, **When** a completion is requested, **Then** the result carries
   the provider name, model identifier, token counts and wall-clock latency.

### User Story 4 — Failure degrades instead of breaking (Priority: P1)

Timeout, missing weights, endpoint refusal, or exhausted repairs all degrade to the
deterministic provider rather than surfacing an error to a user.

**Why this priority**: The fallback is a production path, not a test fixture
([ADR-006](../../docs/adr/ADR-006-deterministic-provider.md)).

**Independent Test**: Inject each failure mode and confirm a usable grounded response is
still produced, with the degradation recorded.

**Acceptance Scenarios**:

1. **Given** a generation exceeding the timeout, **When** it elapses, **Then** generation is
   abandoned and the deterministic provider answers.
2. **Given** a degraded turn, **When** its result is inspected, **Then** it is marked
   degraded with a machine-readable reason.
3. **Given** the deterministic provider, **When** it generates, **Then** it requires no
   model, no network, and completes in under 50 ms.

### Edge Cases

- Context window exceeded by accumulated tool results: the runtime must trim oldest tool
  observations and record the trim, never silently truncate the system prompt or the most
  recent observation.
- A model emitting a valid tool call for a tool it has already called with identical
  arguments: detected and surfaced to the agent as a repeat, so the agent can stop rather
  than loop.
- Grammar generation encountering an unsupported JSON Schema construct: fail at
  registration time with a clear message, never at decode time.
- Two concurrent sessions sharing one loaded model: serialised access, since a single
  llama.cpp context is not safe for concurrent use.
- Zero registered tools: valid, produces a plain completion with no grammar.

## Requirements

### Functional Requirements

- **FR-001**: System MUST define a provider interface supporting a text completion and a
  tool-call completion, over a message list, tool schemas, temperature, max tokens and seed.
- **FR-002**: System MUST implement an in-process GGUF provider via llama.cpp supporting at
  least two configured model tiers (fast and quality).
- **FR-003**: System MUST implement an OpenAI-compatible HTTP provider covering vLLM,
  Ollama, LM Studio and TGI.
- **FR-004**: System MUST implement a deterministic provider that requires no model.
- **FR-005**: System MUST implement a hosted-frontier provider as an opt-in path, disabled
  by default, and MUST log a warning naming the egress when it is enabled.
- **FR-006**: System MUST generate a GBNF grammar from the registered tool schemas so that
  tool-call decoding cannot produce syntactically invalid output.
- **FR-007**: Grammar generation MUST support object, string with enum, integer, number,
  boolean, and array-of-string parameter types, and MUST reject unsupported constructs at
  registration time.
- **FR-008**: System MUST validate every parsed tool call against its schema — tool
  existence, parameter names, types, and required fields.
- **FR-009**: Validation failures MUST be returned to the model as structured, specific
  error observations, for at most a configured number of repair attempts.
- **FR-010**: Exhausting the repair budget MUST raise a typed error the caller can catch and
  degrade on.
- **FR-011**: Every completion MUST return provider name, model identifier, prompt and
  completion token counts, latency, repair attempts, and whether the result was degraded.
- **FR-012**: Generation MUST respect a configurable wall-clock timeout.
- **FR-013**: All providers MUST be deterministic at temperature zero with a fixed seed.
- **FR-014**: Access to a single loaded model MUST be serialised across concurrent callers.
- **FR-015**: Context overflow MUST be handled by trimming the oldest tool observations,
  recording what was trimmed.

### Key Entities

- **Provider**: something that turns messages plus tool schemas into a completion.
- **Tool schema**: name, description, JSON Schema of parameters; the grammar's source.
- **Tool call**: a validated tool name and argument dictionary.
- **Completion result**: content or tool calls, plus telemetry.
- **Validation failure**: a typed reason and a human-readable message for the repair loop.
- **Runtime configuration**: provider selection, model paths, tiers, limits, timeouts.

## Success Criteria

- **SC-001**: Tool-call syntactic validity under grammar constraint is 100% across the
  golden request set — malformed JSON is unrepresentable, not merely rare.
- **SC-002**: Tool *selection* accuracy is measured and reported per model tier. This is the
  honest metric: the grammar guarantees the call is well-formed, not that it is the right
  call.
- **SC-003**: Median tool-call latency on the fast tier is under 4 seconds on 4 CPU cores.
- **SC-004**: The deterministic provider responds in under 50 ms.
- **SC-005**: Every failure mode degrades to a usable response; zero unhandled exceptions
  reach a caller across the injected-failure suite.
- **SC-006**: Switching providers requires changing configuration only; a test asserts the
  agent module imports no provider implementation directly.
- **SC-007**: Repeated identical requests at temperature zero produce identical output.

## Assumptions

- Qwen2.5-Instruct at 1.5B and 3B, Q4_K_M quantization, is the reference model family.
  Others are expected to work but only these two are benchmarked.
- CPU inference is acceptable because nudge generation is asynchronous and cached; it is not
  on a page-load path.
- Model weights are an operational artifact, fetched by a documented command, never
  committed.
- A single process serves one model at a time. Multi-model serving is out of scope.
- Streaming is out of scope for v1; the nudge is generated whole and cached. Chat streaming
  is recorded as future work.
