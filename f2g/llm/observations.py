"""One agreed wire format for tool observations inside the message history.

Both the agent (which writes them) and the deterministic provider (which reads
them back) depend on this shape, so it lives in one module rather than being
duplicated as a convention in two places.
"""
from __future__ import annotations

import json
import re
from typing import Any

PREFIX = "OBSERVATION"
_PATTERN = re.compile(rf"^{PREFIX} (?P<tool>[a-z_]+): (?P<payload>.*)$", re.DOTALL)


def render(tool: str, result: Any) -> str:
    return f"{PREFIX} {tool}: {json.dumps(result, default=str)}"


def parse(content: str) -> tuple[str, Any] | None:
    m = _PATTERN.match(content.strip())
    if not m:
        return None
    try:
        return m.group("tool"), json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None


def collect(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Every observation in the history, keyed by tool name (latest wins)."""
    out: dict[str, Any] = {}
    for m in messages:
        parsed = parse(str(m.get("content", "")))
        if parsed:
            out[parsed[0]] = parsed[1]
    return out
