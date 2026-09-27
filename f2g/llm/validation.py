"""Validate a parsed tool call against its schema, and turn a failure into a
repair instruction the model can act on.

Layer two and three of ADR-003. The grammar makes malformed *syntax*
unrepresentable; it cannot stop the model choosing a sensible-looking but wrong
argument, and providers without grammar support (an OpenAI-compatible endpoint,
for instance) get no syntactic guarantee at all. So every call is validated
regardless of how it was produced.

The repair message matters as much as the check. "Invalid arguments" tells a
1.5B model nothing. "Parameter 'fee_kind' is not recognised for
'list_recent_fees'. Valid parameters: fee_type, limit." is a correction it can
usually act on in one attempt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from f2g.llm.base import FINAL_ANSWER, ToolCall, ToolSchema


class FailureReason(str, Enum):
    NOT_JSON = "not_json"
    NOT_AN_OBJECT = "not_an_object"
    MISSING_TOOL_KEY = "missing_tool_key"
    UNKNOWN_TOOL = "unknown_tool"
    ARGUMENTS_NOT_OBJECT = "arguments_not_object"
    UNKNOWN_PARAMETER = "unknown_parameter"
    MISSING_REQUIRED = "missing_required"
    WRONG_TYPE = "wrong_type"
    NOT_IN_ENUM = "not_in_enum"


@dataclass
class ValidationFailure:
    reason: FailureReason
    message: str

    def as_repair_prompt(self) -> str:
        return (
            f"Your previous output was rejected ({self.reason.value}). {self.message} "
            "Reply with a single corrected JSON tool call and nothing else."
        )


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def parse_tool_call(raw: str) -> tuple[dict[str, Any] | None, ValidationFailure | None]:
    """Parse model output into a dict, tolerating surrounding prose.

    Under a grammar the output is already clean. Without one, small models wrap
    JSON in commentary ("Sure! Here's the call: {...}"), so a bounded recovery
    is attempted before giving up: take the outermost brace-delimited span. This
    is recovery, not interpretation — anything that does not parse is rejected.
    """
    text = raw.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None, ValidationFailure(
                FailureReason.NOT_JSON,
                "No JSON object was found in the output.",
            )
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, ValidationFailure(
                FailureReason.NOT_JSON, f"Output is not valid JSON ({exc.msg})."
            )
    if not isinstance(obj, dict):
        return None, ValidationFailure(
            FailureReason.NOT_AN_OBJECT, "Top-level output must be a JSON object."
        )
    return obj, None


def validate_call(
    obj: dict[str, Any], tools: list[ToolSchema]
) -> tuple[ToolCall | None, ValidationFailure | None]:
    """Check a parsed call against the registered tool schemas."""
    by_name = {t.name: t for t in tools}

    name = obj.get("tool") or obj.get("name")
    if not isinstance(name, str):
        return None, ValidationFailure(
            FailureReason.MISSING_TOOL_KEY,
            f'The object must have a "tool" key naming one of: '
            f'{", ".join([*sorted(by_name), FINAL_ANSWER])}.',
        )

    if name == FINAL_ANSWER:
        return ToolCall(name=FINAL_ANSWER, arguments={}), None

    if name not in by_name:
        return None, ValidationFailure(
            FailureReason.UNKNOWN_TOOL,
            f"'{name}' is not an available tool. Valid tools: "
            f'{", ".join([*sorted(by_name), FINAL_ANSWER])}.',
        )

    args = obj.get("arguments", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, ValidationFailure(
            FailureReason.ARGUMENTS_NOT_OBJECT,
            f"'arguments' for '{name}' must be a JSON object.",
        )

    schema = by_name[name].input_schema or {}
    props: dict[str, Any] = schema.get("properties", {}) or {}
    required = set(schema.get("required", []))

    unknown = set(args) - set(props)
    if unknown:
        return None, ValidationFailure(
            FailureReason.UNKNOWN_PARAMETER,
            f"Parameter(s) {sorted(unknown)} are not recognised for '{name}'. "
            f"Valid parameters: {sorted(props) or 'none'}.",
        )

    # The grammar emits every declared key, using null for ones the model does
    # not want to set. Drop those here so downstream code sees a clean kwargs
    # dict and Python defaults apply.
    cleaned = {k: v for k, v in args.items() if v is not None}

    missing = required - set(cleaned)
    if missing:
        return None, ValidationFailure(
            FailureReason.MISSING_REQUIRED,
            f"Required parameter(s) {sorted(missing)} are missing for '{name}'.",
        )

    for key, value in cleaned.items():
        spec = props[key]
        jtype = spec.get("type")
        check = _TYPE_CHECKS.get(jtype)
        if check and not check(value):
            return None, ValidationFailure(
                FailureReason.WRONG_TYPE,
                f"Parameter '{key}' of '{name}' must be of type {jtype}, "
                f"got {type(value).__name__}.",
            )
        if "enum" in spec and value not in spec["enum"]:
            return None, ValidationFailure(
                FailureReason.NOT_IN_ENUM,
                f"Parameter '{key}' of '{name}' must be one of {spec['enum']}, got {value!r}.",
            )
        if jtype == "array" and isinstance(spec.get("items"), dict):
            item_spec = spec["items"]
            item_check = _TYPE_CHECKS.get(item_spec.get("type"))
            for item in value:
                if item_check and not item_check(item):
                    return None, ValidationFailure(
                        FailureReason.WRONG_TYPE,
                        f"Items of '{key}' in '{name}' must be "
                        f"{item_spec.get('type')}, got {type(item).__name__}.",
                    )
                if "enum" in item_spec and item not in item_spec["enum"]:
                    return None, ValidationFailure(
                        FailureReason.NOT_IN_ENUM,
                        f"Items of '{key}' in '{name}' must be one of "
                        f"{item_spec['enum']}, got {item!r}.",
                    )

    return ToolCall(name=name, arguments=cleaned), None


def parse_and_validate(
    raw: str, tools: list[ToolSchema]
) -> tuple[ToolCall | None, ValidationFailure | None]:
    obj, failure = parse_tool_call(raw)
    if failure:
        return None, failure
    assert obj is not None
    return validate_call(obj, tools)
