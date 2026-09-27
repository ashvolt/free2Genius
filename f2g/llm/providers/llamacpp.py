"""In-process inference over a quantized GGUF model via llama.cpp.

The default provider. No network, no API key, no per-token cost — which is what
makes the evaluation suite affordable enough to gate every commit (ADR-001).

Two operational realities are handled explicitly rather than hidden:

**Concurrency.** A single llama.cpp context is not safe for concurrent use, so
access is serialised behind a lock. This is a real throughput ceiling for a
single process and is stated in the HLD rather than discovered under load.

**Cancellation.** This binding offers no way to interrupt a generation in
flight. The timeout below therefore *abandons* a slow generation rather than
killing it: the caller gets `GenerationTimeout` promptly and can degrade, while
the worker thread runs to completion in the background and releases the lock
when it finishes. Work is bounded by `max_tokens`, so the abandoned generation
always terminates. Pretending we can cancel would be worse than saying we
cannot.
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
from pathlib import Path
from typing import Any

from f2g.llm.base import (
    Completion,
    Decision,
    GenerationTimeout,
    LLMProvider,
    ProviderUnavailable,
    Stopwatch,
    Telemetry,
    ToolSchema,
)
from f2g.llm.grammar import build_tool_grammar, grammar_fingerprint
from f2g.llm.validation import parse_and_validate

log = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def _load_model(path: Path, n_ctx: int, n_threads: int, seed: int):
    key = f"{path}:{n_ctx}:{n_threads}:{seed}"
    with _CACHE_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        try:
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderUnavailable(
                "llama-cpp-python is not installed. `pip install llama-cpp-python`, "
                "or select a different provider with F2G_LLM_PROVIDER."
            ) from exc
        if not path.exists():
            raise ProviderUnavailable(
                f"model weights not found at {path}. Fetch them with `make models`."
            )
        log.info("loading GGUF model %s", path.name)
        model = Llama(
            model_path=str(path), n_ctx=n_ctx, n_threads=n_threads,
            verbose=False, seed=seed,
        )
        _MODEL_CACHE[key] = model
        return model


class LlamaCppProvider:
    """LLMProvider backed by a local GGUF file."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        name: str = "llamacpp",
        n_ctx: int = 8192,
        n_threads: int = 4,
        seed: int = 7,
        timeout_s: float = 90.0,
        repeat_penalty: float = 1.18,
    ) -> None:
        self.model_path = Path(model_path)
        self.name = name
        self.model_id = self.model_path.stem
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.seed = seed
        self.timeout_s = timeout_s
        # Small instruction-tuned models loop without this. Measured on
        # Qwen2.5-1.5B: at the library default the final answer degenerated into
        # nine repetitions of one paragraph.
        self.repeat_penalty = repeat_penalty
        self._lock = threading.Lock()
        self._grammar_cache: dict[str, Any] = {}
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1,
                                                           thread_name_prefix="llamacpp")

    # -- internals --------------------------------------------------------

    @property
    def _model(self):
        return _load_model(self.model_path, self.n_ctx, self.n_threads, self.seed)

    def _grammar_for(self, tools: list[ToolSchema]):
        text = build_tool_grammar(tools)
        key = grammar_fingerprint(text)
        if key not in self._grammar_cache:
            from llama_cpp import LlamaGrammar

            # Compiling a grammar is not free, and the tool set is stable for
            # the life of a process, so this cache is worth having.
            self._grammar_cache[key] = LlamaGrammar.from_string(text, verbose=False)
        return self._grammar_cache[key]

    def _generate(self, **kwargs) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            with self._lock:
                return self._model.create_chat_completion(**kwargs)

        future = self._pool.submit(run)
        try:
            return future.result(timeout=self.timeout_s)
        except concurrent.futures.TimeoutError as exc:
            # Abandoned, not cancelled — see the module docstring.
            raise GenerationTimeout(
                f"generation exceeded {self.timeout_s:.0f}s on {self.model_id}"
            ) from exc

    # -- protocol ---------------------------------------------------------

    def decide(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolSchema],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 256,
    ) -> Decision:
        grammar = self._grammar_for(tools)
        with Stopwatch() as sw:
            resp = self._generate(
                messages=messages, temperature=temperature, max_tokens=max_tokens,
                grammar=grammar, seed=seed,
            )
        raw = resp["choices"][0]["message"]["content"] or ""
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
        from f2g.llm.base import FINAL_ANSWER

        return Decision(
            tool_call=None if call.name == FINAL_ANSWER else call,
            is_final=call.name == FINAL_ANSWER,
            telemetry=tel,
            raw=raw,
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
            resp = self._generate(
                messages=messages, temperature=temperature, max_tokens=max_tokens,
                seed=seed, repeat_penalty=self.repeat_penalty,
            )
        usage = resp.get("usage", {})
        return Completion(
            text=(resp["choices"][0]["message"]["content"] or "").strip(),
            telemetry=Telemetry(
                provider=self.name, model=self.model_id,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_s=sw.elapsed,
            ),
        )

    def health(self) -> dict[str, Any]:
        ok = self.model_path.exists()
        return {
            "provider": self.name,
            "model": self.model_id,
            "available": ok,
            "detail": "ready" if ok else f"weights missing at {self.model_path}",
            "egress": "none — in-process local inference",
        }
