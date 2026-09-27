"""Hosted Claude, as an explicitly opt-in escalation path.

Disabled by default. Selecting it sends user financial data outside our trust
boundary, which is the one thing ADR-001 exists to avoid, so construction logs a
warning naming the egress rather than doing it quietly.

It exists because the provider abstraction is only credible if a genuinely
different backend plugs into it, and because the evaluation harness comparing a
1.5B local model against a frontier model on the same cases is a more honest
statement about local-first than an assertion would be.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from f2g.llm.base import (
    Completion,
    Decision,
    FINAL_ANSWER,
    ProviderUnavailable,
    Stopwatch,
    Telemetry,
    ToolSchema,
)
from f2g.llm.validation import parse_and_validate

log = logging.getLogger(__name__)

_SYSTEM_SUFFIX = """
Reply with exactly one JSON object and nothing else:
  {"tool": "<tool_name>", "arguments": { ... }}
or, when you have enough information to answer:
  {"tool": "final_answer", "arguments": {}}
"""


class AnthropicProvider:
    def __init__(self, model: str = "claude-opus-5", *, timeout_s: float = 90.0) -> None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise ProviderUnavailable(
                "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or use the "
                "default local provider (F2G_LLM_PROVIDER=llamacpp)."
            )
        log.warning(
            "EGRESS: the hosted provider is enabled. User account data will be sent to "
            "the Anthropic API. This is off by default — see ADR-001."
        )
        self.name = "anthropic"
        self.model_id = model
        self.timeout_s = timeout_s

    def _client(self):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("the `anthropic` package is not installed") from exc
        return anthropic.Anthropic(timeout=self.timeout_s)

    @staticmethod
    def _split(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]
        return system, turns

    def decide(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolSchema],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 256,
    ) -> Decision:
        system, turns = self._split(messages)
        catalogue = "\n".join(
            f"- {t.name}: {t.description} params={json.dumps(t.input_schema.get('properties', {}))}"
            for t in tools
        )
        with Stopwatch() as sw:
            resp = self._client().messages.create(
                model=self.model_id,
                max_tokens=max_tokens,
                system=f"{system}\n\nAvailable tools:\n{catalogue}\n{_SYSTEM_SUFFIX}",
                messages=turns,
            )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        tel = Telemetry(
            provider=self.name, model=self.model_id,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            latency_s=sw.elapsed,
        )
        call, failure = parse_and_validate(raw, tools)
        if failure is not None:
            tel.schema_failures = 1
            return Decision(tool_call=None, is_final=False, telemetry=tel, raw=raw)
        assert call is not None
        return Decision(
            tool_call=None if call.name == FINAL_ANSWER else call,
            is_final=call.name == FINAL_ANSWER,
            telemetry=tel, raw=raw,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 1024,
    ) -> Completion:
        system, turns = self._split(messages)
        with Stopwatch() as sw:
            resp = self._client().messages.create(
                model=self.model_id, max_tokens=max_tokens, system=system, messages=turns
            )
        return Completion(
            text="".join(b.text for b in resp.content if b.type == "text").strip(),
            telemetry=Telemetry(
                provider=self.name, model=self.model_id,
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                latency_s=sw.elapsed,
            ),
        )

    def health(self) -> dict[str, Any]:
        from f2g import config as cfg

        return {
            "provider": self.name, "model": self.model_id,
            "available": cfg.has_anthropic_key(),
            "detail": "opt-in cloud escalation",
            "egress": "user data leaves the trust boundary — see ADR-001",
        }
