"""LLM-as-judge for the qualities a regex cannot see.

Deliberately scoped. The judge does **not** decide safety — the programmatic
checks do, and they gate the build. The judge scores whether the message is
accurate against the evidence, relevant, appropriately hedged, readable and free
of pressure. Those are judgements; grounding is a fact.

Two limitations are stated rather than hidden:

1. When the judge runs on the same local model as the agent, it is marking its
   own homework, and self-judging correlates errors. That is why judge scores
   track *relative change over time* and never gate a release.
2. If the judge and the programmatic grounding check disagree — the judge scores
   accuracy highly on a message the ledger rejected — that is reported as a
   judge-calibration finding. The programmatic check always wins.

Scores are produced under a grammar, so a malformed rubric is unrepresentable
and an unparseable judge response cannot be silently coerced into a number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any

from f2g.llm.base import LLMProvider

DIMENSIONS = ("accuracy", "relevance", "hedging", "clarity", "no_pressure")

JUDGE_GRAMMAR = r"""
root    ::= ws "{" ws
            "\"accuracy\""    ws ":" ws score ws "," ws
            "\"relevance\""   ws ":" ws score ws "," ws
            "\"hedging\""     ws ":" ws score ws "," ws
            "\"clarity\""     ws ":" ws score ws "," ws
            "\"no_pressure\"" ws ":" ws score ws "," ws
            "\"rationale\""   ws ":" ws string
            ws "}" ws
score   ::= "1" | "2" | "3" | "4" | "5"
string  ::= "\"" char* "\""
char    ::= [^"\\] | "\\" ["\\/bfnrt]
ws      ::= [ \t\n]*
"""

RUBRIC = """You are grading a message written by a financial assistant for one user.

You are given the user's actual account data as gathered by tools, and the
message the assistant wrote. Grade the message on five dimensions, 1 to 5.

accuracy    5 = every claim matches the evidence; 1 = states things the evidence
            does not support.
relevance   5 = addresses what matters for THIS user's situation; 1 = generic.
hedging     5 = estimates are described as estimates, uncertainty is honest;
            1 = states estimates as certainties.
clarity     5 = a non-expert understands it on one read; 1 = confusing or
            repetitive.
no_pressure 5 = no urgency, no manipulation, recommends against buying when the
            numbers say so; 1 = pushy.

Reply with one JSON object and nothing else."""


@dataclass
class JudgeScore:
    accuracy: int
    relevance: int
    hedging: int
    clarity: int
    no_pressure: int
    rationale: str
    available: bool = True
    error: str = ""

    @property
    def mean(self) -> float:
        return sum(getattr(self, d) for d in DIMENSIONS) / len(DIMENSIONS)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mean"] = round(self.mean, 3)
        return d

    @classmethod
    def unavailable(cls, reason: str) -> "JudgeScore":
        return cls(0, 0, 0, 0, 0, "", available=False, error=reason)


def judge(
    provider: LLMProvider,
    message: str,
    tool_results: list[dict[str, Any]],
    *,
    max_tokens: int = 320,
) -> JudgeScore:
    evidence = json.dumps(
        [{"tool": t["tool"], "result": t["result"]} for t in tool_results],
        default=str,
    )[:6000]

    messages = [
        {"role": "system", "content": RUBRIC},
        {
            "role": "user",
            "content": (
                f"EVIDENCE (tool results):\n{evidence}\n\n"
                f"MESSAGE TO GRADE:\n{message}\n\n"
                "Grade it now."
            ),
        },
    ]

    try:
        raw = _constrained(provider, messages, max_tokens)
    except Exception as exc:  # noqa: BLE001 - judge failure must not fail the run
        return JudgeScore.unavailable(f"{type(exc).__name__}: {exc}")

    try:
        data = json.loads(raw)
        return JudgeScore(
            accuracy=int(data["accuracy"]), relevance=int(data["relevance"]),
            hedging=int(data["hedging"]), clarity=int(data["clarity"]),
            no_pressure=int(data["no_pressure"]), rationale=str(data.get("rationale", "")),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        # Never coerce an unparseable judgement into a score.
        return JudgeScore.unavailable(f"unparseable judge output: {exc}")


def _constrained(provider: LLMProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Grammar-constrained generation where the provider supports it."""
    model = getattr(provider, "_model", None)
    if model is not None and hasattr(provider, "_generate"):
        from llama_cpp import LlamaGrammar

        grammar = LlamaGrammar.from_string(JUDGE_GRAMMAR, verbose=False)
        resp = provider._generate(  # noqa: SLF001 - deliberate, documented coupling
            messages=messages, temperature=0.0, max_tokens=max_tokens,
            grammar=grammar, seed=7,
        )
        return resp["choices"][0]["message"]["content"] or ""
    return provider.complete(messages, max_tokens=max_tokens, temperature=0.0).text


def calibration_disagreement(score: JudgeScore, grounding_passed: bool) -> str | None:
    """Flag when the judge and the mechanical check disagree.

    A judge that scores accuracy 5 on a message the value ledger rejected is
    miscalibrated, and that is a finding about the judge — not a reason to
    doubt the ledger.
    """
    if not score.available:
        return None
    if not grounding_passed and score.accuracy >= 4:
        return "judge scored accuracy high on a message the grounding check blocked"
    if grounding_passed and score.accuracy <= 2:
        return "judge scored accuracy low on a fully grounded message"
    return None
