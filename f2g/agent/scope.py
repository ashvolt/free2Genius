"""What the concierge will and will not answer.

Scope is a product decision, so it is enforced in the agent rather than left to
the model. A refusal that depends on the model cooperating is not a control: the
deterministic fallback had no way to decline at all, and answered a question
about bitcoin with a summary of the user's overdraft fees. The evaluation gate
caught it, which is what the gate is for.

Enforcing it here means every provider — a 1.5B local model, a frontier model,
the template engine — refuses identically, for free, before any inference
happens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Out-of-scope subject matter. These mirror the *output* advice guardrail:
# the same topics that must not appear in an answer are the ones we decline to
# answer about.
OUT_OF_SCOPE_PATTERNS: list[tuple[str, str]] = [
    (r"\b(invest|investing|investment|stocks?|shares?|index fund|etf|crypto|bitcoin|portfolio)\b",
     "investments"),
    (r"\b(credit score|credit report|credit repair|fico)\b", "credit"),
    (r"\b(tax|taxes|deduction|write.?off|irs)\b", "tax"),
    (r"\b(debt consolidation|consolidate my debt|debt settlement|bankruptcy)\b",
     "debt strategy"),
    (r"\b(mortgage|refinanc|loan approval|insurance policy)\b", "lending and insurance"),
    (r"\b(retirement|401k|401\(k\)|ira\b|pension)\b", "retirement planning"),
]

# Things the concierge is for. Used to tell an off-topic question apart from an
# in-scope one, so we redirect rather than refuse.
IN_SCOPE_MARKERS = (
    "fee", "fees", "advance", "advances", "genius", "subscription", "overdraft",
    "transfer", "balance", "deposit", "budget", "saving", "savings", "charge",
    "charged", "cost", "worth it", "upgrade", "plan", "account", "money",
    "spend", "spending", "subscriptions",
)


@dataclass
class ScopeVerdict:
    in_scope: bool
    kind: str          # "ok" | "out_of_scope" | "off_topic"
    topic: str = ""
    response: str = ""


def _decline(topic: str) -> str:
    return (
        f"I can't advise on {topic} — that's outside what I can help with. "
        "I can explain the fees on your account and whether Genius would save you money."
    )


OFF_TOPIC_RESPONSE = (
    "That's outside what I can help with. I can explain the fees on your account "
    "and whether Genius would save you money on them."
)


def classify(user_text: str) -> ScopeVerdict:
    """Decide whether to answer, decline, or redirect.

    Order matters: a question can mention both money and investments ("should I
    invest my savings?"), and the out-of-scope topic has to win.
    """
    if not user_text or not user_text.strip():
        return ScopeVerdict(True, "ok")

    lowered = user_text.lower()

    for pattern, topic in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, lowered):
            return ScopeVerdict(False, "out_of_scope", topic, _decline(topic))

    if not any(marker in lowered for marker in IN_SCOPE_MARKERS):
        return ScopeVerdict(False, "off_topic", "", OFF_TOPIC_RESPONSE)

    return ScopeVerdict(True, "ok")
