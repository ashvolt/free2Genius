"""The Genius feature catalog: the single source of truth for pricing facts.

SYNTHETIC / ILLUSTRATIVE. These prices and descriptions are invented for this
portfolio project. They are not Albert's real pricing.

Why this file exists: a language model asked "what does Genius cost?" will
produce a confident number from its training data, and that number is a
compliance incident waiting to happen. The agent is therefore given no pricing
knowledge of its own — it must call `get_genius_feature_catalog()`, and every
price it may state comes from here. One file to audit, one file to change.
"""
from __future__ import annotations

from typing import Any

GENIUS_MONTHLY_PRICE = 14.99

# Fees a *free* user pays today. The agent may only reference these amounts.
FREE_TIER_FEES = {
    "instant_transfer_fee": 4.99,   # per expedited advance delivery
    "overdraft_fee_typical": 34.00,  # charged by the user's bank, not by us
}

FEATURES: list[dict[str, Any]] = [
    {
        "feature_id": "instant_delivery",
        "name": "Free instant advance delivery",
        "summary": (
            "Cash advances arrive instantly at no fee. On the free plan each "
            "expedited delivery costs $4.99."
        ),
        "saves_against": "instant_transfer_fees",
        "unit_saving": 4.99,
        "evidence_required": "instant_transfer fee events in the last 90 days",
    },
    {
        "feature_id": "overdraft_shield",
        "name": "Overdraft shield",
        "summary": (
            "Automatically triggers a small advance when the linked account is "
            "about to go negative, so the bank's overdraft fee is not charged. "
            "It does not refund fees already paid."
        ),
        "saves_against": "overdraft_fees",
        "unit_saving": 34.00,
        # Deliberately conservative: the shield cannot catch every overdraft.
        "coverage_rate": 0.70,
        "evidence_required": "overdraft fee events in the last 90 days",
    },
    {
        "feature_id": "subscription_watch",
        "name": "Subscription watch",
        "summary": (
            "Detects recurring charges and flags ones that look unused so you "
            "can cancel them. Savings depend on what you choose to cancel."
        ),
        "saves_against": "recurring_subscription_spend",
        # A potential, not a promise. The estimator applies this rate and the
        # agent must describe the result as an estimate.
        "assumed_cancel_rate": 0.15,
        "evidence_required": "detected recurring merchants",
    },
    {
        "feature_id": "smart_savings",
        "name": "Smart savings",
        "summary": (
            "Moves small, affordable amounts into savings automatically based "
            "on cash flow. This builds a balance; it is not a fee saving."
        ),
        "saves_against": None,
        "evidence_required": "cash-flow history",
    },
    {
        "feature_id": "budget_coach",
        "name": "Budget coach",
        "summary": (
            "Category budgets with alerts before you overspend. Free users get "
            "a read-only view; Genius adds alerts and rollover budgets."
        ),
        "saves_against": None,
        "evidence_required": "budgeting session history",
    },
]

FEATURE_IDS = {f["feature_id"] for f in FEATURES}
FEATURE_NAMES = {f["name"] for f in FEATURES}


def get_catalog() -> dict[str, Any]:
    """Catalog payload handed to the agent as a tool result."""
    return {
        "monthly_price_usd": GENIUS_MONTHLY_PRICE,
        "free_tier_fees_usd": FREE_TIER_FEES,
        "features": FEATURES,
        "disclosure": (
            "Savings figures are estimates based on this user's own last 90 "
            "days of activity. They are not guarantees of future savings."
        ),
    }


def get_feature(feature_id: str) -> dict[str, Any] | None:
    for f in FEATURES:
        if f["feature_id"] == feature_id:
            return f
    return None
