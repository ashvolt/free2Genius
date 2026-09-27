"""The Genius concierge agent: a bounded tool loop with hard output gates.

The loop itself is small — that is the point of an agent, and the interesting
engineering is everywhere else:

* identity is bound at construction, so no input can redirect the agent at
  another user (feature 005, FR-001);
* the round budget is hard, and exhausting it forces an answer rather than
  looping;
* repeated identical calls are detected, because small models loop;
* every draft passes the guardrails before anyone sees it, and a block degrades
  to the deterministic provider rather than surfacing an error.

The degradation path is the part most worth reading. A blocked message is not
an error state: the user still gets a correct, grounded explanation, and we get
a logged reason. That is what makes the zero-grounding-violation gate
affordable — the strict check has somewhere safe to fall.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from f2g import config
from f2g.agent import prompts
from f2g.agent.guardrails import GuardrailReport, run_input_guardrails, run_output_guardrails
from f2g.agent.tools import TOOL_SCHEMAS, ConciergeTools
from f2g.llm import observations
from f2g.llm.base import LLMProvider, Telemetry, ToolCall, ToolSchema
from f2g.llm.providers.deterministic import DeterministicProvider
from f2g.llm.runtime import ToolCallRuntime, build_provider, repeated_call

log = logging.getLogger(__name__)

_SCHEMAS = [ToolSchema.from_dict(t) for t in TOOL_SCHEMAS]

# Evidence the agent must hold before it is allowed to answer.
#
# This is a protocol precondition, not a prompt request, and it exists because
# of a measured failure. Qwen2.5-3B called only `get_account_summary`, never
# looked at the fee ledger, and concluded "there are no significant fees from
# the free plan" for a user carrying $136.93 in fees. Nothing in the safety
# layer catches that: every number it stated was real, and the sentence was
# still false.
#
# A grammar can guarantee a tool call is well-formed. It cannot guarantee the
# model chose to look. So the loop enforces what the prompt merely asks for:
# the fee history and the savings estimate must exist before an answer is
# accepted, and if the model will not fetch them, the agent fetches them
# itself. An answer about whether a subscription saves money, written without
# looking at what the user actually pays, is not an answer.
REQUIRED_EVIDENCE = ("list_recent_fees", "estimate_savings")

_DEFAULT_ARGS: dict[str, dict[str, Any]] = {
    "list_recent_fees": {},
    "estimate_savings": {"feature_ids": ["instant_delivery", "overdraft_shield"]},
}


@dataclass
class Evidence:
    """One figure in the message, tied to the tool call that produced it."""

    value: float
    rendered: str
    tools: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "rendered": self.rendered, "tools": self.tools}


@dataclass
class AgentResult:
    user_id: str
    message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)
    input_guardrails: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    degraded_reason: str = ""
    prompt_version: str = prompts.PROMPT_VERSION
    rounds_used: int = 0
    # Tools the agent had to call itself because the model did not. A rising
    # rate here is the signal that the model is under-investigating.
    forced_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "user_id": self.user_id,
            "message": self.message,
            "tool_calls": self.tool_calls,
            "evidence": [e.to_dict() for e in self.evidence],
            "guardrails": self.guardrails,
            "input_guardrails": self.input_guardrails,
            "telemetry": self.telemetry,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "prompt_version": self.prompt_version,
            "rounds_used": self.rounds_used,
            "forced_evidence": self.forced_evidence,
        }
        return d


class ConciergeAgent:
    def __init__(
        self,
        user_id: str,
        *,
        provider: LLMProvider | None = None,
        max_rounds: int | None = None,
    ) -> None:
        # Identity is fixed here and never appears in a tool schema. This is the
        # security boundary: the model has no way to express a request for
        # another user's data, whatever a prompt-injection attempt asks for.
        self.tools = ConciergeTools(user_id)
        self.user_id = user_id
        self.max_rounds = max_rounds or config.AGENT_MAX_TOOL_ROUNDS
        self.runtime = ToolCallRuntime(provider or build_provider())
        self._fallback = DeterministicProvider()

    # -- public surface ---------------------------------------------------

    def generate_nudge(self) -> AgentResult:
        return self._run(prompts.NUDGE_TASK, user_visible_input="")

    def chat(self, user_message: str, history: list[dict[str, str]] | None = None) -> AgentResult:
        task = f"{prompts.CHAT_PREAMBLE}\n\nUser question: {user_message}"
        return self._run(task, user_visible_input=user_message, history=history)

    # -- the loop ---------------------------------------------------------

    def _run(
        self,
        task: str,
        *,
        user_visible_input: str,
        history: list[dict[str, str]] | None = None,
    ) -> AgentResult:
        input_report = run_input_guardrails(user_visible_input) if user_visible_input else None

        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            *(history or []),
            {"role": "user", "content": task},
        ]

        telemetry = Telemetry()
        made: list[ToolCall] = []
        tool_records: list[dict[str, Any]] = []
        rounds = 0
        pushed_back = False

        def gathered() -> set[str]:
            return {r["tool"] for r in tool_records}

        for rounds in range(1, self.max_rounds + 1):
            result = self.runtime.decide_or_degrade(messages, _SCHEMAS)
            telemetry = telemetry.merge(result.telemetry)
            decision = result.decision

            if decision.is_final or decision.tool_call is None:
                missing = [t for t in REQUIRED_EVIDENCE if t not in gathered()]
                if missing and not pushed_back:
                    # Ask once, naming exactly what is missing. Models often
                    # comply, and a model-chosen call is better than ours
                    # because it may pick better arguments.
                    pushed_back = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You have not looked at everything you need yet. Before you "
                                f"answer you must call: {', '.join(missing)}. "
                                "Call the first of those now."
                            ),
                        }
                    )
                    continue
                break

            call = decision.tool_call
            if repeated_call(call, made):
                # Small models loop. Tell the model rather than spending the
                # rest of the budget re-reading the same answer.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"You already called {call.name} with those arguments and have "
                            "the result above. Either call a different tool or choose "
                            "final_answer."
                        ),
                    }
                )
                continue

            observation = self.tools.dispatch(call.name, call.arguments)
            made.append(call)
            tool_records.append(
                {"tool": call.name, "arguments": call.arguments, "result": observation}
            )
            messages.append({"role": "assistant", "content": decision.raw})
            messages.append(
                {"role": "user", "content": observations.render(call.name, observation)}
            )
        else:
            # Budget exhausted without the model choosing to answer. Force it.
            messages.append(
                {
                    "role": "user",
                    "content": "You have used all available tool calls. Answer now with what you have.",
                }
            )

        # --- enforce the evidence precondition ---------------------------
        # If the model still has not gathered the required evidence, gather it
        # here. The agent is accountable for the claim it makes, so it does not
        # get to answer from a partial view just because the model declined to
        # look.
        forced: list[str] = []
        for tool in REQUIRED_EVIDENCE:
            if tool not in gathered():
                args = dict(_DEFAULT_ARGS.get(tool, {}))
                observation = self.tools.dispatch(tool, args)
                tool_records.append(
                    {"tool": tool, "arguments": args, "result": observation, "forced": True}
                )
                messages.append(
                    {"role": "user", "content": observations.render(tool, observation)}
                )
                forced.append(tool)
        if forced:
            log.info("forced evidence gathering for %s: %s", self.user_id, forced)

        # --- final prose -------------------------------------------------
        messages.append(
            {"role": "user", "content": prompts.final_answer_instruction(bool(tool_records))}
        )
        completion = self.runtime.complete_or_degrade(
            messages, max_tokens=config.AGENT_MAX_TOKENS
        )
        telemetry = telemetry.merge(completion.telemetry)
        draft = completion.text

        # --- output gates ------------------------------------------------
        report = run_output_guardrails(draft, self.tools.value_ledger)
        degraded = telemetry.degraded
        degraded_reason = telemetry.degraded_reason

        if report.blocked:
            reasons = "; ".join(
                f.message for f in report.findings if f.severity.value == "block"
            )
            log.warning("guardrail block for %s: %s", self.user_id, reasons)
            draft = self._deterministic_message(messages)
            report = run_output_guardrails(draft, self.tools.value_ledger)
            degraded = True
            degraded_reason = f"guardrail_block: {reasons}"
            # If the templated floor itself fails, something is wrong with the
            # ledger rather than the model, and silence is the correct output.
            if report.blocked:
                log.error(
                    "deterministic fallback also blocked for %s: %s",
                    self.user_id,
                    "; ".join(
                        f"{f.check}[{f.span}]"
                        for f in report.findings
                        if f.severity.value == "block"
                    ),
                )
                draft = (
                    "We could not put together a reliable summary of your account right "
                    "now. Please try again shortly."
                )
                report = run_output_guardrails(draft, self.tools.value_ledger,
                                               require_disclosure=False)

        return AgentResult(
            user_id=self.user_id,
            message=draft,
            tool_calls=tool_records,
            evidence=self._evidence_for(draft),
            guardrails=report.to_dict(),
            input_guardrails=input_report.to_dict() if input_report else {},
            telemetry={
                "provider": telemetry.provider,
                "model": telemetry.model,
                "prompt_tokens": telemetry.prompt_tokens,
                "completion_tokens": telemetry.completion_tokens,
                "latency_s": round(telemetry.latency_s, 3),
                "repair_attempts": telemetry.repair_attempts,
                "schema_failures": telemetry.schema_failures,
            },
            degraded=degraded,
            degraded_reason=degraded_reason,
            rounds_used=rounds,
            forced_evidence=forced,
        )

    # -- helpers ----------------------------------------------------------

    def _deterministic_message(self, messages: list[dict[str, str]]) -> str:
        """The templated floor — after completing any investigation the model skipped.

        This finishes the tool script before composing, and that is not an
        optimisation. The template describes what it found; if the fee tool was
        never called it would otherwise report "no fees were charged", which for
        a user who *does* have fees is a false statement about their own money.
        Absence of a tool call is not absence of fees, and the floor must not
        confuse the two.
        """
        working = list(messages)
        # The script is finite and each step consumes one distinct tool, so the
        # tool count is a sufficient bound.
        for _ in range(len(_SCHEMAS) + 1):
            decision = self._fallback.decide(working, _SCHEMAS)
            if decision.is_final or decision.tool_call is None:
                break
            call = decision.tool_call
            result = self.tools.dispatch(call.name, call.arguments)
            working.append(
                {"role": "user", "content": observations.render(call.name, result)}
            )
        return self._fallback.complete(working).text

    def _evidence_for(self, text: str) -> list[Evidence]:
        """Tie each figure in the message back to the call that produced it."""
        from f2g.agent.guardrails import _CURRENCY, _PERCENT

        found: list[Evidence] = []
        seen: set[str] = set()
        for pattern in (_CURRENCY, _PERCENT):
            for match in pattern.finditer(text):
                rendered = match.group(0)
                if rendered in seen:
                    continue
                seen.add(rendered)
                try:
                    value = float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
                tools = self.tools.provenance(value) or self.tools.provenance(value / 100.0)
                found.append(Evidence(value=value, rendered=rendered, tools=tools))
        return found


def generate_for(user_id: str, provider_name: str | None = None) -> AgentResult:
    """Convenience entry point used by the API and the evaluation harness."""
    provider = build_provider(provider_name) if provider_name else None
    return ConciergeAgent(user_id, provider=provider).generate_nudge()
