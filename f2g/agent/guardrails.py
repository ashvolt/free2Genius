"""Output guardrails: mechanical checks that decide whether a draft reaches a user.

Principle I of the constitution says the agent may state a number only if that
number came from this user's own data. This module is where that stops being a
request and becomes an enforced invariant.

The central check is **numeric grounding** (ADR-007). Every tool result is
walked as it is produced and its numeric leaves recorded in a per-session
ledger. Here, every number in the draft is extracted and checked for membership
in that ledger. A number that is not accounted for blocks the message; the turn
degrades to the deterministic provider. Nothing unaccounted reaches a user.

Deliberate property: this produces **false positives**. A number the model
computed correctly — a sum it did in its head — is blocked, because we cannot
distinguish "correct arithmetic" from "confident fabrication" by looking at the
output. That strictness is exactly why `estimate_savings` exists: derivation
belongs in Python. The guardrail's rigidity is what forced the better tool
design, and softening it would undo that.

Every check reports independently. A single composite pass/fail would tell an
operator that something was wrong without saying what, and the block rate per
check is the signal that detects prompt drift (feature 009).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from f2g.data import catalog


class Severity(str, Enum):
    BLOCK = "block"      # message must not reach a user
    WARN = "warn"        # recorded, does not block


@dataclass
class Finding:
    check: str
    severity: Severity
    message: str
    span: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
            "span": self.span,
        }


@dataclass
class GuardrailReport:
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.BLOCK for f in self.findings)

    @property
    def passed(self) -> bool:
        return not self.blocked

    def by_check(self) -> dict[str, bool]:
        """Per-check pass state, so the UI can render one badge per check."""
        failed = {f.check for f in self.findings if f.severity is Severity.BLOCK}
        return {name: name not in failed for name in self.checks_run}

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "checks": self.by_check(),
            "findings": [f.to_dict() for f in self.findings],
        }


# --------------------------------------------------------------------------
# 1. Numeric grounding
# --------------------------------------------------------------------------

# Currency, percentages, and bare numbers (with optional thousands separators).
_CURRENCY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_PERCENT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?%")
_BARE_NUMBER = re.compile(r"(?<![\w$.])(\d[\d,]*(?:\.\d+)?)(?![\w%])")

# Bare integers that are never financial claims: small counts, ordinals, and the
# window lengths that appear in every tool result. Currency and percentages are
# never exempted by this list — only undecorated integers.
_SAFE_BARE_INTEGERS = set(range(0, 13)) | {14, 15, 20, 24, 30, 31, 60, 90, 365}


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _catalog_values() -> set[float]:
    """Values the pricing catalog sanctions, independent of any tool call."""
    values: set[float] = {round(float(catalog.GENIUS_MONTHLY_PRICE), 2)}
    for v in catalog.FREE_TIER_FEES.values():
        values.add(round(float(v), 2))
    for f in catalog.FEATURES:
        for key in ("unit_saving", "coverage_rate", "assumed_cancel_rate"):
            if key in f:
                values.add(round(float(f[key]), 2))
                # A rate may legitimately be written as a percentage.
                values.add(round(float(f[key]) * 100, 2))
    return values


def check_numeric_grounding(text: str, value_ledger: Iterable[float]) -> list[Finding]:
    """Every number in `text` must trace to a tool result or the catalog."""
    allowed = {round(float(v), 2) for v in value_ledger} | _catalog_values()
    findings: list[Finding] = []

    def accounted(value: float) -> bool:
        return round(value, 2) in allowed

    for match in _CURRENCY.finditer(text):
        value = _to_float(match.group(1))
        if value is None or not accounted(value):
            findings.append(
                Finding(
                    "numeric_grounding",
                    Severity.BLOCK,
                    f"Monetary figure {match.group(0)!r} does not appear in any tool result "
                    "for this user.",
                    span=match.group(0),
                )
            )

    for match in _PERCENT.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        # A rate may appear in tool output either as 0.70 or as 70.
        if not (accounted(value) or accounted(value / 100.0)):
            findings.append(
                Finding(
                    "numeric_grounding",
                    Severity.BLOCK,
                    f"Percentage {match.group(0)!r} does not appear in any tool result "
                    "for this user.",
                    span=match.group(0),
                )
            )

    spans_taken = [m.span() for m in _CURRENCY.finditer(text)] + [
        m.span() for m in _PERCENT.finditer(text)
    ]

    def inside_taken(pos: int) -> bool:
        return any(a <= pos < b for a, b in spans_taken)

    for match in _BARE_NUMBER.finditer(text):
        if inside_taken(match.start()):
            continue
        value = _to_float(match.group(1))
        if value is None:
            continue
        if value.is_integer() and int(value) in _SAFE_BARE_INTEGERS:
            continue
        if not accounted(value):
            findings.append(
                Finding(
                    "numeric_grounding",
                    Severity.BLOCK,
                    f"Figure {match.group(1)!r} does not appear in any tool result for "
                    "this user.",
                    span=match.group(0),
                )
            )
    return findings


# --------------------------------------------------------------------------
# 2. Prohibited financial advice
# --------------------------------------------------------------------------

# Words that flip an advice claim into a disclaimer. Checked in the text
# immediately preceding a match.
#
# This exists because of a real false positive: the pricing catalog's required
# disclosure reads "They are not guarantees of future savings", and a bare
# /guarantee/ pattern blocked the agent's own disclaimer — the guardrail
# rejecting the very sentence that makes the output compliant. A safety check
# that fires on negated text is not conservative, it is broken: it trains
# operators to ignore it and it blocks correct output.
_NEGATIONS = (
    "not", "no", "never", "without", "aren't", "isn't", "cannot", "can't",
    "don't", "doesn't", "rather than", "instead of",
)
_NEGATION_WINDOW = 40


def _is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - _NEGATION_WINDOW) : start].lower()
    return any(re.search(rf"\b{re.escape(word)}\b", prefix) for word in _NEGATIONS)


_ADVICE_PATTERNS: list[tuple[str, str]] = [
    (r"\byou should (invest|buy stock|buy shares|put your money into)\b", "investment advice"),
    (r"\b(invest|investing) (in|your money)\b", "investment advice"),
    (r"\b(stocks?|crypto|bitcoin|etf|portfolio|mutual funds?)\b", "investment product"),
    (r"\bguarantee[ds]?\b", "guaranteed outcome"),
    (r"\b(will|shall) definitely (save|earn|make|get)\b", "guaranteed outcome"),
    (r"\btax (deduction|advice|strategy|write.?off)\b", "tax advice"),
    (r"\b(fix|repair|boost|improve) your credit score\b", "credit repair advice"),
    (r"\bdebt (consolidation|strategy|settlement)\b", "debt strategy advice"),
    (r"\byou (should|must) (take out|borrow)\b", "borrowing advice"),
    (r"\brisk.?free\b", "guaranteed outcome"),
]


def check_prohibited_advice(text: str) -> list[Finding]:
    findings = []
    lowered = text.lower()
    for pattern, label in _ADVICE_PATTERNS:
        for m in re.finditer(pattern, lowered):
            if _is_negated(lowered, m.start()):
                # e.g. "these are not guarantees of future savings" — a
                # disclaimer, which is the opposite of the thing being checked.
                continue
            findings.append(
                Finding(
                    "prohibited_advice",
                    Severity.BLOCK,
                    f"Output contains {label}, which is out of scope for this agent.",
                    span=m.group(0),
                )
            )
            break
    return findings


# --------------------------------------------------------------------------
# 3. Feature names must exist in the catalog
# --------------------------------------------------------------------------

# "Genius Overdraft Protector", "the Genius Auto-Invest feature", etc.
_FEATURE_CLAIM = re.compile(r"\bGenius\s+((?:[A-Z][\w-]*)(?:\s+[A-Z][\w-]*){0,3})")


# Short forms a writer may reasonably use for a catalog feature. Kept explicit
# rather than inferred, so adding an alias is a deliberate, reviewable act.
_FEATURE_ALIASES = {
    "instant delivery", "instant advance delivery", "express delivery",
    "overdraft shield", "subscription watch", "smart savings", "budget coach",
}


def check_feature_names(text: str) -> list[Finding]:
    """Any capitalised product name attached to 'Genius' must be a real feature."""
    known = {name.lower() for name in catalog.FEATURE_NAMES} | _FEATURE_ALIASES
    findings = []
    for match in _FEATURE_CLAIM.finditer(text):
        claimed = match.group(1).strip()
        if claimed.lower() in {"genius", "plan", "subscription", "membership"}:
            continue
        if not any(claimed.lower() in k or k in claimed.lower() for k in known):
            findings.append(
                Finding(
                    "feature_names",
                    Severity.BLOCK,
                    f"'Genius {claimed}' is not a feature in the catalog.",
                    span=match.group(0),
                )
            )
    return findings


# --------------------------------------------------------------------------
# 4. Pressure and urgency
# --------------------------------------------------------------------------

_URGENCY_PATTERNS = [
    r"\bact (now|fast|today)\b",
    r"\blimited[- ]time\b",
    r"\boffer (ends|expires)\b",
    r"\bdon'?t miss\b",
    r"\bonly \d+ (days?|hours?) left\b",
    r"\blast chance\b",
    r"\bhurry\b",
    r"\bexclusive offer\b",
]


def check_urgency(text: str) -> list[Finding]:
    findings = []
    lowered = text.lower()
    for pattern in _URGENCY_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            findings.append(
                Finding(
                    "no_pressure",
                    Severity.BLOCK,
                    "Output uses urgency or scarcity language.",
                    span=m.group(0),
                )
            )
    return findings


# --------------------------------------------------------------------------
# 5. Coherence — degenerate repetition
# --------------------------------------------------------------------------

_MIN_REPEAT_LEN = 40
_MAX_REPEATS = 2


def check_coherence(text: str) -> list[Finding]:
    """Detect the repetition loops small instruction-tuned models fall into.

    Observed directly: Qwen2.5-1.5B produced one correct, fully grounded
    paragraph and then repeated it nine times until it hit the token cap. Every
    safety check passed — the numbers were real, the advice was clean, no
    pressure language — because the output was *safe* and *useless*.

    Safety guardrails do not cover usability, so this is its own check. It is a
    BLOCK because shipping a message that repeats itself nine times is worse
    for a user than shipping the templated floor.
    """
    findings: list[Finding] = []

    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _MIN_REPEAT_LEN]
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    for line, n in counts.items():
        if n > _MAX_REPEATS:
            findings.append(
                Finding(
                    "coherence",
                    Severity.BLOCK,
                    f"Output repeats the same line {n} times — the model degenerated.",
                    span=line[:60],
                )
            )
            break

    # A model can also loop without exact line matches. Catch low lexical
    # diversity over a long output as a second signal.
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) > 120:
        diversity = len(set(words)) / len(words)
        if diversity < 0.28:
            findings.append(
                Finding(
                    "coherence",
                    Severity.BLOCK,
                    f"Output has very low lexical diversity ({diversity:.2f}); "
                    "likely a repetition loop.",
                )
            )
    return findings


# --------------------------------------------------------------------------
# 6. Required disclosure
# --------------------------------------------------------------------------

def check_disclosure(text: str, required: bool = True) -> list[Finding]:
    if not required:
        return []
    lowered = text.lower()
    if "estimate" in lowered or "based on your" in lowered:
        return []
    return [
        Finding(
            "disclosure",
            Severity.WARN,
            "Output does not describe its figures as estimates based on recent activity.",
        )
    ]


# --------------------------------------------------------------------------
# 7. Prompt injection, on the input side
# --------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    (r"ignore (all |your |the )?(previous|prior|above) instructions", "instruction override"),
    (r"disregard (all |your |the )?(previous|prior|above)", "instruction override"),
    (r"you are now\b", "identity override"),
    (r"(reveal|show|print|repeat) (me )?(your |the )?(system )?prompt", "prompt extraction"),
    (r"\bact as\b.{0,30}\b(admin|administrator|support agent|developer)\b", "privilege claim"),
    (r"\b[ul]\d{7}\b", "another user's identifier"),
    (r"</?(system|instructions?)>", "tag injection"),
]


def check_injection(user_text: str) -> list[Finding]:
    """Detect and record injection attempts in user input.

    Detection is defence in depth, not the defence. The actual protection is
    structural: `user_id` is bound at session construction and is not a tool
    parameter, so the model has no way to express a request for another user's
    data however it is asked. These findings exist so attempts are visible for
    review, which is why they are WARN rather than BLOCK.
    """
    findings = []
    lowered = user_text.lower()
    for pattern, label in _INJECTION_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            findings.append(
                Finding(
                    "prompt_injection",
                    Severity.WARN,
                    f"Input contains a possible {label} attempt.",
                    span=m.group(0)[:80],
                )
            )
    return findings


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

OUTPUT_CHECKS = ("numeric_grounding", "prohibited_advice", "feature_names",
                 "no_pressure", "coherence", "disclosure")


def run_output_guardrails(
    text: str,
    value_ledger: Iterable[float],
    *,
    require_disclosure: bool = True,
) -> GuardrailReport:
    report = GuardrailReport(checks_run=list(OUTPUT_CHECKS))
    report.findings.extend(check_numeric_grounding(text, value_ledger))
    report.findings.extend(check_prohibited_advice(text))
    report.findings.extend(check_feature_names(text))
    report.findings.extend(check_urgency(text))
    report.findings.extend(check_coherence(text))
    report.findings.extend(check_disclosure(text, require_disclosure))
    return report


def run_input_guardrails(user_text: str) -> GuardrailReport:
    report = GuardrailReport(checks_run=["prompt_injection"])
    report.findings.extend(check_injection(user_text))
    return report
