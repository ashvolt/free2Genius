"""Provider construction and the bounded repair loop.

This module is the only place that knows which providers exist. Everything
above it depends on the `LLMProvider` protocol, which is what makes the
provider swap a configuration change (FR-003 / SC-006 of feature 004).

The repair loop is layer three of ADR-003. When a decision fails validation the
model is told *exactly* what was wrong and asked again, at most
`MAX_REPAIR_ATTEMPTS` times. On exhaustion it raises rather than guessing — a
plausible-but-wrong tool call produces confident output from the wrong inputs,
which in a financial product is worse than an error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from f2g import config
from f2g.llm.base import (
    Decision,
    GenerationTimeout,
    LLMError,
    LLMProvider,
    ProviderUnavailable,
    RepairBudgetExhausted,
    Telemetry,
    ToolCall,
    ToolSchema,
)
from f2g.llm.providers.deterministic import DeterministicProvider
from f2g.llm.validation import parse_and_validate

log = logging.getLogger(__name__)

PROVIDERS = ("llamacpp", "openai", "deterministic", "anthropic")


def build_provider(name: str | None = None, *, tier: str | None = None) -> LLMProvider:
    """Construct a provider.

    Two modes, and the difference matters:

    * **Explicit** (`name` given) — fails at construction rather than at first
      inference. If a caller asked for `llamacpp` and the weights are missing,
      silently handing back something else would be dishonest: they would think
      they were measuring a model they were not.
    * **Automatic** (`name` omitted, so the configured default applies) — falls
      back to the deterministic provider with a warning. Nobody chose the
      default explicitly, and ADR-006 makes the deterministic provider the
      degradation target for every failure path. A fresh clone with no model
      weights should serve a correct templated answer, not a 500.
    """
    explicit = name is not None
    name = (name or config.LLM_PROVIDER).lower()

    if not explicit:
        try:
            return _construct(name, tier)
        except ProviderUnavailable as exc:
            log.warning(
                "default provider %r is unavailable (%s); falling back to the "
                "deterministic provider. Run `make models` and "
                "`pip install llama-cpp-python` to use a local model.",
                name, exc,
            )
            return DeterministicProvider()

    return _construct(name, tier)


def _construct(name: str, tier: str | None) -> LLMProvider:
    if name == "deterministic":
        return DeterministicProvider()


    if name == "llamacpp":
        from f2g.llm.providers.llamacpp import LlamaCppProvider

        path = config.model_path(tier)
        if not path.exists():
            raise ProviderUnavailable(
                f"model weights not found at {path}.\n"
                f"  fetch them:      make models\n"
                f"  or run without:  F2G_LLM_PROVIDER=deterministic"
            )
        return LlamaCppProvider(
            path, n_ctx=config.LLM_N_CTX, n_threads=config.LLM_N_THREADS,
            seed=config.LLM_SEED, timeout_s=config.LLM_TIMEOUT_S,
            name=f"llamacpp:{tier or config.MODEL_TIER}",
        )

    if name == "openai":
        from f2g.llm.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            config.OPENAI_COMPAT_BASE_URL, config.OPENAI_COMPAT_MODEL,
            timeout_s=config.LLM_TIMEOUT_S,
        )

    if name == "anthropic":
        from f2g.llm.providers.anthropic_cloud import AnthropicProvider

        return AnthropicProvider(model=config.ANTHROPIC_MODEL, timeout_s=config.LLM_TIMEOUT_S)

    raise ProviderUnavailable(f"unknown provider {name!r}; expected one of {PROVIDERS}")


@dataclass
class RuntimeResult:
    decision: Decision
    telemetry: Telemetry
    repair_log: list[str] = field(default_factory=list)


class ToolCallRuntime:
    """Wraps a provider with validation, repair and graceful degradation."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_repair_attempts: int | None = None,
        fallback: LLMProvider | None = None,
    ) -> None:
        self.provider = provider
        self.max_repair_attempts = (
            config.MAX_REPAIR_ATTEMPTS if max_repair_attempts is None else max_repair_attempts
        )
        self.fallback = fallback if fallback is not None else DeterministicProvider()

    # -- decisions --------------------------------------------------------

    def decide(
        self, messages: list[dict[str, str]], tools: list[ToolSchema], **kw: Any
    ) -> RuntimeResult:
        telemetry = Telemetry(provider=self.provider.name, model=self.provider.model_id)
        repair_log: list[str] = []
        working = list(messages)

        for attempt in range(self.max_repair_attempts + 1):
            decision = self.provider.decide(working, tools, **kw)
            telemetry = telemetry.merge(decision.telemetry)

            if decision.is_final or decision.tool_call is not None:
                telemetry.repair_attempts = attempt
                return RuntimeResult(decision, telemetry, repair_log)

            # Invalid. Tell the model precisely what was wrong and try again.
            _, failure = parse_and_validate(decision.raw, tools)
            detail = failure.as_repair_prompt() if failure else "Output could not be parsed."
            repair_log.append(f"attempt {attempt + 1}: {detail}")
            log.warning("tool-call repair %d/%d: %s", attempt + 1, self.max_repair_attempts, detail)
            working = [
                *working,
                {"role": "assistant", "content": decision.raw},
                {"role": "user", "content": detail},
            ]

        telemetry.repair_attempts = self.max_repair_attempts
        raise RepairBudgetExhausted(self.max_repair_attempts + 1, repair_log)

    def decide_or_degrade(
        self, messages: list[dict[str, str]], tools: list[ToolSchema], **kw: Any
    ) -> RuntimeResult:
        """`decide`, but every failure mode lands on the deterministic script."""
        try:
            return self.decide(messages, tools, **kw)
        except (RepairBudgetExhausted, GenerationTimeout, ProviderUnavailable, LLMError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("degrading decision to %s — %s", self.fallback.name, reason)
            decision = self.fallback.decide(messages, tools, **kw)
            tel = decision.telemetry
            tel.degraded = True
            tel.degraded_reason = reason
            return RuntimeResult(decision, tel, [reason])

    # -- prose ------------------------------------------------------------

    def complete_or_degrade(self, messages: list[dict[str, str]], **kw: Any):
        try:
            return self.provider.complete(messages, **kw)
        except (GenerationTimeout, ProviderUnavailable, LLMError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("degrading completion to %s — %s", self.fallback.name, reason)
            out = self.fallback.complete(messages, **kw)
            out.telemetry.degraded = True
            out.telemetry.degraded_reason = reason
            return out

    def health(self) -> dict[str, Any]:
        return {"primary": self.provider.health(), "fallback": self.fallback.health()}


def repeated_call(call: ToolCall, previous: list[ToolCall]) -> bool:
    """Whether this exact call was already made.

    Small models loop: they call the same tool with the same arguments and read
    the same answer. Surfacing the repeat lets the agent stop rather than burn
    its round budget.
    """
    sig = call.signature()
    return any(p.signature() == sig for p in previous)
