"""The provider contract: the single seam where model choice lives.

Everything above this file — the agent, its tools, its guardrails, the
evaluation harness — is written against these types and never learns which
model is underneath. That is what makes local-first inference a *choice*
rather than a constraint (ADR-001), and it is what lets the evaluation harness
score a 1.5B local model, a 3B local model and a template engine through
exactly the same code path.

The protocol is deliberately small. Two operations:

* `decide` — pick the next action under a grammar constraint. Small, fully
  constrained output: either a tool call or the decision to answer.
* `complete` — produce free prose. Unconstrained.

Splitting them is what makes a small model usable. Asking a 1.5B model to emit
a long prose answer *inside* a JSON string, under grammar constraint, with
correct escaping, fails often. Asking it to emit twenty constrained tokens
choosing a tool, then separately to write prose with no constraint, plays to
what it can actually do.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# The pseudo-tool the model selects when it has enough information to answer.
# Modelling "stop" as a tool keeps the decision inside one grammar, so the model
# never has to choose between two output shapes.
FINAL_ANSWER = "final_answer"


class LLMError(RuntimeError):
    """Base for every runtime failure the agent is expected to handle."""


class ProviderUnavailable(LLMError):
    """The backend could not be reached or constructed."""


class GenerationTimeout(LLMError):
    """Generation exceeded the configured wall-clock budget."""


class RepairBudgetExhausted(LLMError):
    """The model could not produce a valid tool call within the repair budget.

    Raised rather than returning a best guess. In a financial context a
    plausible-but-wrong tool call is worse than an error, because it produces
    confident output from the wrong inputs.
    """

    def __init__(self, attempts: int, failures: list[str]) -> None:
        super().__init__(f"no valid tool call after {attempts} attempts: {failures}")
        self.attempts = attempts
        self.failures = failures


class GrammarUnsupported(LLMError):
    """A tool schema uses a JSON Schema construct the grammar cannot express.

    Raised at registration time, never at decode time — a tool author finds out
    when they add the tool, not when a user is waiting.
    """


@dataclass(frozen=True)
class ToolSchema:
    """What the model is told about one tool."""

    name: str
    description: str
    input_schema: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolSchema":
        return cls(name=d["name"], description=d["description"], input_schema=d["input_schema"])


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]

    def signature(self) -> str:
        """Stable identity for repeat detection."""
        items = ",".join(f"{k}={self.arguments[k]!r}" for k in sorted(self.arguments))
        return f"{self.name}({items})"


@dataclass
class Telemetry:
    """Per-call operational facts. Feature 009 aggregates these."""

    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    repair_attempts: int = 0
    parse_failures: int = 0
    schema_failures: int = 0
    degraded: bool = False
    degraded_reason: str = ""

    def merge(self, other: "Telemetry") -> "Telemetry":
        return Telemetry(
            provider=other.provider or self.provider,
            model=other.model or self.model,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            latency_s=self.latency_s + other.latency_s,
            repair_attempts=self.repair_attempts + other.repair_attempts,
            parse_failures=self.parse_failures + other.parse_failures,
            schema_failures=self.schema_failures + other.schema_failures,
            degraded=self.degraded or other.degraded,
            degraded_reason=other.degraded_reason or self.degraded_reason,
        )


@dataclass
class Decision:
    """The outcome of one `decide` call."""

    tool_call: ToolCall | None
    is_final: bool
    telemetry: Telemetry = field(default_factory=Telemetry)
    raw: str = ""


@dataclass
class Completion:
    text: str
    telemetry: Telemetry = field(default_factory=Telemetry)


@runtime_checkable
class LLMProvider(Protocol):
    """What every backend must offer. Intentionally minimal."""

    name: str
    model_id: str

    def decide(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolSchema],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 256,
    ) -> Decision:
        """Choose the next action: one tool call, or the decision to answer."""
        ...

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 1024,
    ) -> Completion:
        """Produce free prose."""
        ...

    def health(self) -> dict[str, Any]:
        """Whether this provider can serve, and what it is."""
        ...


class Stopwatch:
    """Wall-clock timing for telemetry, as a context manager."""

    def __enter__(self) -> "Stopwatch":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.perf_counter() - self._t0

    elapsed: float = 0.0
