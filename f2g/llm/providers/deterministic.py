"""A provider with no model: templated, grounded, and always available.

Not a mock. This is a production runtime and the automatic degradation target
for every failure path (ADR-006). It is also the control arm in agent
evaluation: the language model has to beat this on judged helpfulness, and if it
does not, this is what ships.

It is grounded by construction. It can only interpolate values that appear in
tool observations, so it passes the numeric grounding check without needing to
be checked — which makes it the safe floor of the product rather than a
placeholder.

Its `decide` follows a fixed investigation script rather than reasoning: summary
→ fees → catalog → savings → answer. Deterministic, complete, and fast.
"""
from __future__ import annotations

from typing import Any

from f2g.llm import observations
from f2g.llm.base import Completion, Decision, Stopwatch, Telemetry, ToolCall, ToolSchema

# The fixed investigation order. Each step runs only if that tool is registered
# and has not already produced an observation.
SCRIPT: list[tuple[str, dict[str, Any]]] = [
    ("get_account_summary", {}),
    ("list_recent_fees", {}),
    ("get_advance_history", {}),
    ("get_genius_feature_catalog", {}),
    ("estimate_savings", {"feature_ids": ["instant_delivery", "overdraft_shield"]}),
]


def _money(x: float) -> str:
    return f"${x:,.2f}"


class DeterministicProvider:
    """LLMProvider that composes a grounded explanation from tool results."""

    name = "deterministic"
    model_id = "template-v1"

    def __init__(self, *, timeout_s: float = 1.0) -> None:
        self.timeout_s = timeout_s

    def decide(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolSchema],
        *,
        temperature: float = 0.0,
        seed: int = 7,
        max_tokens: int = 256,
    ) -> Decision:
        seen = observations.collect(messages)
        registered = {t.name for t in tools}
        with Stopwatch() as sw:
            for tool, args in SCRIPT:
                if tool in registered and tool not in seen:
                    return Decision(
                        tool_call=ToolCall(tool, dict(args)),
                        is_final=False,
                        telemetry=Telemetry(provider=self.name, model=self.model_id,
                                            latency_s=sw.elapsed),
                    )
        return Decision(
            tool_call=None,
            is_final=True,
            telemetry=Telemetry(provider=self.name, model=self.model_id, latency_s=sw.elapsed),
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
            text = self._compose(observations.collect(messages))
        return Completion(
            text=text,
            telemetry=Telemetry(provider=self.name, model=self.model_id, latency_s=sw.elapsed),
        )

    # -- composition ------------------------------------------------------

    def _compose(self, obs: dict[str, Any]) -> str:
        fees = obs.get("list_recent_fees") or {}
        savings = obs.get("estimate_savings") or {}
        catalog = obs.get("get_genius_feature_catalog") or {}

        by_type = fees.get("by_type") or {}
        instant = (by_type.get("instant_transfer") or {})
        overdraft = (by_type.get("overdraft") or {})

        lines: list[str] = []

        # 1. What we found.
        total = fees.get("total_usd")
        if not fees or not total:
            lines.append(
                "Looking at the last 90 days of your account, you have not been charged "
                "any express-delivery or overdraft fees."
            )
        else:
            bits = []
            if instant.get("count"):
                bits.append(
                    f"{instant['count']} express-delivery "
                    f"{'fee' if instant['count'] == 1 else 'fees'} totalling "
                    f"{_money(instant['total_usd'])}"
                )
            if overdraft.get("count"):
                bits.append(
                    f"{overdraft['count']} overdraft "
                    f"{'fee' if overdraft['count'] == 1 else 'fees'} totalling "
                    f"{_money(overdraft['total_usd'])}"
                )
            lines.append(
                "In the last 90 days you were charged " + " and ".join(bits) + "."
            )

        # 2. What Genius would have done about it.
        per_feature = [f for f in savings.get("per_feature", []) if f.get("estimated_saving_usd")]
        if per_feature:
            lines.append("")
            lines.append("Based on that history, Genius would have helped like this:")
            for f in per_feature:
                qualifier = " (estimated)" if f.get("is_estimate") else ""
                lines.append(
                    f"- **{f['feature_name']}** — about "
                    f"{_money(f['estimated_saving_usd'])}{qualifier}. {f.get('basis', '')}".rstrip()
                )

        # 3. The honest bottom line. This paragraph is the reason the product is
        #    defensible: it says plainly when the subscription would not pay for
        #    itself, using figures that came from the estimator, not from prose.
        if savings:
            total_saving = savings.get("total_estimated_saving_usd", 0.0)
            cost = savings.get("genius_cost_over_window_usd", 0.0)
            net = savings.get("net_position_usd", total_saving - cost)
            lines.append("")
            if net > 0:
                lines.append(
                    f"Over the same 90 days Genius costs {_money(cost)}, so on your recent "
                    f"activity it would have left you about {_money(net)} better off."
                )
            else:
                lines.append(
                    f"Over the same 90 days Genius costs {_money(cost)}, which is more than "
                    f"the {_money(total_saving)} it would have saved you. On your recent "
                    f"activity it would not pay for itself, so it is probably not worth it "
                    f"right now."
                )

        disclosure = catalog.get("disclosure") or savings.get("disclosure")
        if disclosure:
            lines.append("")
            lines.append(f"_{disclosure}_")

        return "\n".join(lines).strip() or (
            "There is not enough recent account activity to say whether Genius would "
            "save you money."
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model_id,
            "available": True,
            "detail": "always available; no model required",
            "egress": "none",
        }
