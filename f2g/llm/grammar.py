"""Generate a GBNF grammar from tool schemas, so a malformed tool call is
unrepresentable rather than merely unlikely.

This is the first and cheapest of the three reliability layers in ADR-003. A
1.5B model asked politely for JSON produces prose-wrapped JSON, trailing commas,
invented parameter names and occasionally a *narration* of a tool call. Under a
grammar, llama.cpp cannot sample a token sequence outside the language, so that
entire failure class disappears at the decoder rather than being handled after
the fact.

Two design choices worth stating:

**All declared properties are required in the grammar, with `null` permitted for
optional ones.** Generating a grammar that allows every subset of optional keys
means enumerating the power set, which explodes and produces a grammar the model
navigates badly. Emitting every key with an explicit `null` is simpler for the
model, deterministic for us, and the validator maps `null` back to "absent".

**Enums become literal alternatives.** This is the strongest property here: if a
parameter's allowed values are known — fee types, catalog feature ids — the model
*cannot* emit anything else. A hallucinated product feature is not caught
downstream; it never exists.

The supported subset of JSON Schema is deliberately narrow, and anything outside
it raises at registration time (`GrammarUnsupported`) rather than at decode time.
"""
from __future__ import annotations

import re
from typing import Any

from f2g.llm.base import FINAL_ANSWER, GrammarUnsupported, ToolSchema

SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "array", "object"}

_PRIMITIVES = """
ws      ::= [ \\t\\n]*
string  ::= "\\"" chars "\\"" 
chars   ::= char*
char    ::= [^"\\\\] | "\\\\" ["\\\\/bfnrt]
integer ::= "-"? ("0" | [1-9][0-9]*)
number  ::= "-"? ("0" | [1-9][0-9]*) ("." [0-9]+)?
boolean ::= "true" | "false"
null    ::= "null"
"""


def _rule_name(*parts: str) -> str:
    raw = "-".join(parts)
    return re.sub(r"[^a-zA-Z0-9-]", "-", raw).lower()


def _quoted_terminal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"\\"{escaped}\\""'


def _value_rule(prop_name: str, spec: dict[str, Any], tool: str, rules: dict[str, str]) -> str:
    """Return the GBNF expression matching one property's value."""
    jtype = spec.get("type")
    if jtype not in SUPPORTED_TYPES:
        raise GrammarUnsupported(
            f"tool '{tool}' property '{prop_name}': unsupported type {jtype!r}. "
            f"Supported: {sorted(SUPPORTED_TYPES)}"
        )

    if "enum" in spec:
        if jtype != "string":
            raise GrammarUnsupported(
                f"tool '{tool}' property '{prop_name}': enum is only supported on strings"
            )
        return " | ".join(_quoted_terminal(v) for v in spec["enum"])

    if jtype == "string":
        return "string"
    if jtype == "integer":
        return "integer"
    if jtype == "number":
        return "number"
    if jtype == "boolean":
        return "boolean"
    if jtype == "array":
        items = spec.get("items")
        if not isinstance(items, dict):
            raise GrammarUnsupported(f"tool '{tool}' property '{prop_name}': array needs 'items'")
        inner = _value_rule(f"{prop_name}-item", items, tool, rules)
        item_rule = _rule_name(tool, prop_name, "item")
        rules[item_rule] = inner
        arr_rule = _rule_name(tool, prop_name, "array")
        rules[arr_rule] = f'"[" ws ({item_rule} (ws "," ws {item_rule})*)? ws "]"'
        return arr_rule
    if jtype == "object":
        if spec.get("properties"):
            raise GrammarUnsupported(
                f"tool '{tool}' property '{prop_name}': nested objects with properties "
                "are not supported; flatten the tool's arguments"
            )
        return '"{" ws "}"'
    raise GrammarUnsupported(f"tool '{tool}' property '{prop_name}': unreachable")


def _tool_rule(tool: ToolSchema, rules: dict[str, str]) -> str:
    schema = tool.input_schema or {}
    props: dict[str, Any] = schema.get("properties", {}) or {}
    required = set(schema.get("required", []))

    call_rule = _rule_name("call", tool.name)

    if not props:
        rules[call_rule] = (
            f'"{{" ws "\\"tool\\"" ws ":" ws {_quoted_terminal(tool.name)} ws "," ws '
            f'"\\"arguments\\"" ws ":" ws "{{" ws "}}" ws "}}"'
        )
        return call_rule

    parts = []
    for i, (prop, spec) in enumerate(props.items()):
        expr = _value_rule(prop, spec, tool.name, rules)
        prop_rule = _rule_name(tool.name, "prop", prop)
        # Optional properties accept an explicit null rather than being omitted,
        # which keeps the grammar linear instead of a power set of key subsets.
        rules[prop_rule] = expr if prop in required else f"({expr}) | null"
        parts.append(
            (f'ws "," ws ' if i else "")
            + f'"\\"{prop}\\"" ws ":" ws {prop_rule}'
        )

    body = " ".join(parts)
    rules[call_rule] = (
        f'"{{" ws "\\"tool\\"" ws ":" ws {_quoted_terminal(tool.name)} ws "," ws '
        f'"\\"arguments\\"" ws ":" ws "{{" ws {body} ws "}}" ws "}}"'
    )
    return call_rule


def build_tool_grammar(tools: list[ToolSchema]) -> str:
    """A GBNF grammar matching exactly one valid tool call, or the final-answer
    decision.

    The returned grammar is deterministic in the tool list, so it can be cached
    and so the same tool set always produces the same grammar — which matters,
    because a grammar that varies between runs would make generation
    irreproducible even at temperature zero.
    """
    if not tools:
        raise GrammarUnsupported("cannot build a tool grammar with no tools")

    rules: dict[str, str] = {}
    alternatives = [_tool_rule(t, rules) for t in tools]

    final_rule = _rule_name("call", FINAL_ANSWER)
    rules[final_rule] = (
        f'"{{" ws "\\"tool\\"" ws ":" ws {_quoted_terminal(FINAL_ANSWER)} ws "," ws '
        f'"\\"arguments\\"" ws ":" ws "{{" ws "}}" ws "}}"'
    )
    alternatives.append(final_rule)

    lines = [f"root ::= ws ({' | '.join(alternatives)}) ws"]
    for name, body in rules.items():
        lines.append(f"{name} ::= {body}")
    lines.append(_PRIMITIVES.strip())
    return "\n".join(lines)


def grammar_fingerprint(grammar: str) -> str:
    import hashlib

    return hashlib.sha256(grammar.encode()).hexdigest()[:12]
