"""Feature 004 — grammar, validation, repair and provider substitutability."""
from __future__ import annotations

import pytest

from f2g.agent.tools import TOOL_SCHEMAS
from f2g.llm.base import (
    FINAL_ANSWER,
    Decision,
    GrammarUnsupported,
    RepairBudgetExhausted,
    Telemetry,
    ToolCall,
    ToolSchema,
)
from f2g.llm.grammar import build_tool_grammar
from f2g.llm.providers.deterministic import DeterministicProvider
from f2g.llm.runtime import ToolCallRuntime, build_provider, repeated_call
from f2g.llm.validation import FailureReason, parse_and_validate

SCHEMAS = [ToolSchema.from_dict(t) for t in TOOL_SCHEMAS]


# -- grammar ---------------------------------------------------------------

def test_grammar_enumerates_enum_values():
    """Enum parameters become literal alternatives, so an invented catalog
    feature is unrepresentable at the decoder rather than caught later."""
    g = build_tool_grammar(SCHEMAS)
    assert '"\\"instant_delivery\\""' in g
    assert '"\\"overdraft_shield\\""' in g
    assert '"\\"instant_transfer\\""' in g


def test_grammar_includes_final_answer():
    assert FINAL_ANSWER in build_tool_grammar(SCHEMAS)


def test_grammar_is_deterministic():
    assert build_tool_grammar(SCHEMAS) == build_tool_grammar(SCHEMAS)


def test_grammar_rejects_unsupported_schema_at_registration():
    bad = ToolSchema("weird", "d", {"type": "object",
                                    "properties": {"x": {"type": "null"}}})
    with pytest.raises(GrammarUnsupported):
        build_tool_grammar([bad])


def test_grammar_rejects_nested_objects():
    bad = ToolSchema("nested", "d", {
        "type": "object",
        "properties": {"x": {"type": "object", "properties": {"y": {"type": "string"}}}},
    })
    with pytest.raises(GrammarUnsupported, match="nested objects"):
        build_tool_grammar([bad])


def test_grammar_needs_at_least_one_tool():
    with pytest.raises(GrammarUnsupported):
        build_tool_grammar([])


# -- validation ------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,reason",
    [
        ('{"tool":"read_email","arguments":{}}', FailureReason.UNKNOWN_TOOL),
        ('{"tool":"list_recent_fees","arguments":{"fee_kind":"x"}}', FailureReason.UNKNOWN_PARAMETER),
        ('{"tool":"list_recent_fees","arguments":{"limit":"lots"}}', FailureReason.WRONG_TYPE),
        ('{"tool":"list_recent_fees","arguments":{"fee_type":"parking"}}', FailureReason.NOT_IN_ENUM),
        ('{"tool":"estimate_savings","arguments":{}}', FailureReason.MISSING_REQUIRED),
        ('{"tool":"estimate_savings","arguments":{"feature_ids":["nope"]}}', FailureReason.NOT_IN_ENUM),
        ("no json here", FailureReason.NOT_JSON),
        ('["a","list"]', FailureReason.NOT_AN_OBJECT),
        ('{"arguments":{}}', FailureReason.MISSING_TOOL_KEY),
    ],
)
def test_validation_rejects_with_specific_reason(raw, reason):
    call, failure = parse_and_validate(raw, SCHEMAS)
    assert call is None
    assert failure is not None and failure.reason is reason
    # The repair prompt must name the problem; "invalid" teaches a small model
    # nothing.
    assert len(failure.as_repair_prompt()) > 40


def test_validation_accepts_prose_wrapped_json():
    call, failure = parse_and_validate(
        'Sure! {"tool":"get_account_summary","arguments":{}}', SCHEMAS
    )
    assert failure is None and call is not None and call.name == "get_account_summary"


def test_nulls_are_treated_as_absent():
    """The grammar emits every declared key; null means 'not set'."""
    call, failure = parse_and_validate(
        '{"tool":"list_recent_fees","arguments":{"fee_type":null,"limit":null}}', SCHEMAS
    )
    assert failure is None and call is not None and call.arguments == {}


def test_final_answer_validates():
    call, failure = parse_and_validate(f'{{"tool":"{FINAL_ANSWER}","arguments":{{}}}}', SCHEMAS)
    assert failure is None and call is not None and call.name == FINAL_ANSWER


# -- repair loop -----------------------------------------------------------

class _ScriptedProvider:
    """Emits a fixed sequence of raw outputs, to drive the repair loop."""

    name = "scripted"
    model_id = "test"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def decide(self, messages, tools, **kw) -> Decision:
        raw = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        call, failure = parse_and_validate(raw, tools)
        if failure is not None:
            return Decision(None, False, Telemetry(provider=self.name), raw)
        return Decision(
            None if call.name == FINAL_ANSWER else call, call.name == FINAL_ANSWER,
            Telemetry(provider=self.name), raw,
        )

    def complete(self, messages, **kw):
        from f2g.llm.base import Completion

        return Completion("ok", Telemetry(provider=self.name))

    def health(self):
        return {"provider": self.name, "available": True}


def test_repair_loop_recovers_after_one_bad_output():
    provider = _ScriptedProvider([
        '{"tool":"nope","arguments":{}}',
        '{"tool":"get_account_summary","arguments":{}}',
    ])
    rt = ToolCallRuntime(provider, max_repair_attempts=2)
    result = rt.decide([{"role": "user", "content": "x"}], SCHEMAS)
    assert result.decision.tool_call is not None
    assert result.telemetry.repair_attempts == 1
    assert len(result.repair_log) == 1


def test_repair_budget_exhaustion_raises_rather_than_guessing():
    provider = _ScriptedProvider(['{"tool":"nope","arguments":{}}'])
    rt = ToolCallRuntime(provider, max_repair_attempts=2)
    with pytest.raises(RepairBudgetExhausted):
        rt.decide([{"role": "user", "content": "x"}], SCHEMAS)


def test_exhaustion_degrades_instead_of_failing():
    provider = _ScriptedProvider(['{"tool":"nope","arguments":{}}'])
    rt = ToolCallRuntime(provider, max_repair_attempts=1)
    result = rt.decide_or_degrade([{"role": "user", "content": "x"}], SCHEMAS)
    assert result.telemetry.degraded is True
    assert result.decision.tool_call is not None  # the deterministic script took over


def test_repeat_detection():
    a = ToolCall("list_recent_fees", {"fee_type": "overdraft"})
    b = ToolCall("list_recent_fees", {"fee_type": "overdraft"})
    c = ToolCall("list_recent_fees", {"fee_type": "instant_transfer"})
    assert repeated_call(b, [a]) is True
    assert repeated_call(c, [a]) is False


# -- providers -------------------------------------------------------------

def test_default_provider_degrades_when_weights_are_missing(monkeypatch, tmp_path):
    """A fresh clone with no model weights must serve, not 500.

    Nobody chose the default explicitly, and ADR-006 makes the deterministic
    provider the degradation target for every failure path. This was a real
    defect: POST /agent/nudge with no provider returned a 500 on a fresh clone.
    """
    from f2g import config

    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_PROVIDER", "llamacpp")
    provider = build_provider()
    assert provider.name == "deterministic"


def test_explicit_provider_never_silently_substitutes(monkeypatch, tmp_path):
    """The other half of the contract.

    A caller who asked for `llamacpp` and got a template back would believe they
    were measuring a model they were not.
    """
    from f2g import config
    from f2g.llm.base import ProviderUnavailable

    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    with pytest.raises(ProviderUnavailable, match="model weights not found"):
        build_provider("llamacpp")


def test_unknown_provider_fails_at_construction_not_first_call():
    from f2g.llm.base import ProviderUnavailable

    with pytest.raises(ProviderUnavailable, match="unknown provider"):
        build_provider("telepathy")


def test_deterministic_provider_is_always_available():
    p = DeterministicProvider()
    assert p.health()["available"] is True
    assert p.health()["egress"] == "none"


def test_deterministic_provider_follows_its_script():
    p = DeterministicProvider()
    d = p.decide([], SCHEMAS)
    assert d.tool_call is not None and d.tool_call.name == "get_account_summary"


def test_agent_module_imports_no_provider_implementation():
    """SC-006: switching providers must be configuration, not code.

    If the agent imported a concrete provider, the abstraction would be
    decorative.
    """
    import pathlib

    source = pathlib.Path("f2g/agent/concierge.py").read_text()
    assert "providers.llamacpp" not in source
    assert "providers.openai_compat" not in source
    assert "providers.anthropic_cloud" not in source
