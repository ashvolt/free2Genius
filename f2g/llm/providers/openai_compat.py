"""An OpenAI-compatible chat endpoint: vLLM, Ollama, LM Studio, TGI.

The path for running a larger open-weights model on a GPU box while keeping the
same agent code. Still inside your own infrastructure — the point of ADR-001 is
the trust boundary, not the process boundary.

No grammar constraint is available over this interface, so the syntactic
guarantee is lost and the validation plus repair layers do all the work. That
difference is measured rather than assumed: the evaluation harness reports
tool-call validity per provider, so the cost of losing the grammar is a number.
"""
from __future__ import annotations

import json
from typing import Any

from f2g.llm.base import (
    Completion,
    Decision,
    FINAL_ANSWER,
    GenerationTimeout,
    ProviderUnavailable,
    Stopwatch,
    Telemetry,
    ToolSchema,
)
from f2g.llm.validation import parse_and_validate

_TOOL_INSTRUCTION = """You must reply with exactly one JSON object and nothing else.

To call a tool:
{"tool": "<tool_name>", "arguments": { ... }}

When you have enough information to answer:
{"tool": "final_answer", "arguments": {}}

Available tools:
%s
"""


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "not-needed",
        name: str = "openai_compat",
        timeout_s: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.api_key = api_key
        self.name = name
        self.timeout_s = timeout_s

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                r.raise_for_status()
                return r.json()
        except httpx.TimeoutException as exc:
            raise GenerationTimeout(f"{self.base_url} timed out after {self.timeout_s}s") from exc
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed provider error
            raise ProviderUnavailable(f"{self.base_url} unreachable: {exc}") from exc

    def _describe(self, tools: list[ToolSchema]) -> str:
        return "\n".join(
            f"- {t.name}: {t.description}\n  parameters: "
            f"{json.dumps(t.input_schema.get('properties', {}))}"
            for t in tools
        )

    def decide(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolSchema],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 256,
    ) -> Decision:
        instructed = [
            *messages,
            {"role": "system", "content": _TOOL_INSTRUCTION % self._describe(tools)},
        ]
        with Stopwatch() as sw:
            resp = self._post(
                {
                    "model": self.model_id, "messages": instructed,
                    "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
                    # Ask for JSON where the server supports it; harmless where not.
                    "response_format": {"type": "json_object"},
                }
            )
        raw = resp["choices"][0]["message"].get("content") or ""
        usage = resp.get("usage", {})
        tel = Telemetry(
            provider=self.name, model=self.model_id,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
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
        with Stopwatch() as sw:
            resp = self._post(
                {"model": self.model_id, "messages": messages, "temperature": temperature,
                 "max_tokens": max_tokens, "seed": seed}
            )
        usage = resp.get("usage", {})
        return Completion(
            text=(resp["choices"][0]["message"].get("content") or "").strip(),
            telemetry=Telemetry(
                provider=self.name, model=self.model_id,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_s=sw.elapsed,
            ),
        )

    def health(self) -> dict[str, Any]:
        try:
            import httpx

            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self.base_url}/models",
                               headers={"Authorization": f"Bearer {self.api_key}"})
            ok = r.status_code < 400
            detail = "ready" if ok else f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        return {
            "provider": self.name, "model": self.model_id, "available": ok, "detail": detail,
            "egress": f"HTTP to {self.base_url} — keep this inside your own network",
        }
