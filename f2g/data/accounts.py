"""Account data access: the layer the agent's tools read from.

Two responsibilities:

1. `AccountRepository` -- load the generated cohorts and look users up by id.
   In a real system this is a service call; here it is a cached CSV read.
2. `build_ledger` -- expand a user's *aggregate* feature row into the concrete
   event list the agent needs to be specific ("three $4.99 instant-transfer
   fees on Jul 3, Jul 19 and Aug 2" rather than "you pay some fees").

The ledger is derived deterministically from the user id, so the same user
always produces the same events. A tool that returns different data on every
call makes an agent impossible to test or debug.

Critically, the expanded events are *consistent with the aggregates*: the
individual fee events sum exactly to `instant_transfer_fees_90d`. If they did
not, the agent's narrative and the model's features would tell different
stories about the same user, with no error anywhere -- the sort of bug that
destroys trust in a system like this.
"""
from __future__ import annotations

import datetime as dt
import functools
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from f2g import config
from f2g.data.catalog import FREE_TIER_FEES

# Anchor date for the synthetic 90-day window, so output is reproducible.
AS_OF = dt.date(2026, 9, 1)

MERCHANTS = [
    ("Netflix", 15.49), ("Spotify", 11.99), ("Hulu", 17.99), ("Planet Fitness", 24.99),
    ("Adobe CC", 22.99), ("iCloud+", 2.99), ("Amazon Prime", 14.99),
    ("DoorDash DashPass", 9.99), ("Peloton App", 12.99), ("NYTimes", 4.25),
    ("Audible", 14.95), ("Xbox Game Pass", 16.99),
]

INCOME_EMPLOYERS = [
    "Sunrise Logistics", "Bayline Retail Group", "Cedar Health Partners",
    "Northgate Staffing", "Vertex Field Services",
]


def _user_rng(user_id: str) -> np.random.Generator:
    """A generator seeded from the user id -- same user, same ledger, always."""
    digest = hashlib.sha256(user_id.encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


class AccountRepository:
    """In-memory store of the generated cohorts."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self._by_id = {row["user_id"]: row for row in frame.to_dict("records")}

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._by_id.get(user_id)

    def exists(self, user_id: str) -> bool:
        return user_id in self._by_id

    def ids(self, cohort: str | None = None, limit: int | None = None) -> list[str]:
        f = self._frame
        if cohort:
            f = f[f["cohort"] == cohort]
        ids = f["user_id"].tolist()
        return ids[:limit] if limit else ids


@functools.lru_cache(maxsize=1)
def repository() -> AccountRepository:
    """Load pilot + live cohorts once per process."""
    frames = []
    for name in ("pilot_users.csv", "live_users.csv"):
        path = config.DATA_DIR / name
        if path.exists():
            frames.append(pd.read_csv(path))
    if not frames:
        raise FileNotFoundError(
            f"No cohort CSVs in {config.DATA_DIR}. "
            "Run `python -m f2g.data.generate` first."
        )
    return AccountRepository(pd.concat(frames, ignore_index=True))


def _spread_dates(rng: np.random.Generator, count: int, window_days: int = 90) -> list[str]:
    """`count` distinct dates inside the trailing window, newest first.

    Sampled without replacement, so two fee events never land on the same date
    -- which would read to a user as a duplicate charge.
    """
    if count <= 0:
        return []
    offsets = sorted(
        rng.choice(np.arange(1, window_days + 1), size=min(count, window_days), replace=False)
    )
    return [(AS_OF - dt.timedelta(days=int(o))).isoformat() for o in offsets][::-1]


@functools.lru_cache(maxsize=4096)
def build_ledger(user_id: str) -> dict[str, Any]:
    """Expand one user's aggregates into concrete, dated events."""
    user = repository().get(user_id)
    if user is None:
        # Distinguishable from "this user has no fees". Never an empty ledger.
        raise KeyError(user_id)

    rng = _user_rng(user_id)

    # --- Fee events -------------------------------------------------------
    # Emitted from the same counts that produced the aggregate, so the sum is
    # arithmetically forced rather than checked afterwards.
    n_instant = int(user["_instant_transfer_count_90d"])
    n_overdraft = int(user["_overdraft_count_90d"])
    fee_events: list[dict[str, Any]] = []
    for date in _spread_dates(rng, n_instant):
        fee_events.append({
            "date": date,
            "type": "instant_transfer",
            "amount_usd": FREE_TIER_FEES["instant_transfer_fee"],
            "description": "Express delivery fee on cash advance",
            "charged_by": "albert",
        })
    for date in _spread_dates(rng, n_overdraft):
        fee_events.append({
            "date": date,
            "type": "overdraft",
            "amount_usd": FREE_TIER_FEES["overdraft_fee_typical"],
            "description": "Overdraft fee on linked checking account",
            "charged_by": "linked_bank",
        })
    fee_events.sort(key=lambda e: e["date"], reverse=True)

    # --- Advances ---------------------------------------------------------
    n_adv = int(user["advances_90d"])
    avg_amt = float(user["advance_amount_avg"])
    advances = []
    for i, date in enumerate(_spread_dates(rng, n_adv)):
        amount = round(max(25.0, rng.normal(avg_amt, max(avg_amt * 0.18, 5.0))), 2)
        advances.append({
            "date": date,
            "amount_usd": amount,
            "delivery": "instant" if i < n_instant else "standard",
            "repaid_on_time": bool(rng.random() < float(user["advance_repaid_on_time_rate"])),
        })

    # --- Recurring subscriptions -----------------------------------------
    n_subs = int(user["recurring_subscriptions_count"])
    picks = (
        rng.choice(len(MERCHANTS), size=min(n_subs, len(MERCHANTS)), replace=False)
        if n_subs else []
    )
    subs_raw = [{"merchant": MERCHANTS[i][0], "monthly_usd": MERCHANTS[i][1]} for i in picks]
    # Rescale so the detail matches the aggregate the model was trained on.
    raw_total = sum(s["monthly_usd"] for s in subs_raw)
    target_total = float(user["recurring_subscription_spend"])
    scale = (target_total / raw_total) if raw_total > 0 else 1.0
    subscriptions = [
        {
            "merchant": s["merchant"],
            "monthly_usd": round(s["monthly_usd"] * scale, 2),
            "last_charged": (AS_OF - dt.timedelta(days=int(rng.integers(1, 31)))).isoformat(),
            # "Unused" is a heuristic signal in the real product; here it is a
            # deterministic draw the agent must describe as a *flag*, not fact.
            "looks_unused": bool(rng.random() < 0.22),
        }
        for s in subs_raw
    ]

    # --- Direct deposits --------------------------------------------------
    deposits = []
    if int(user["direct_deposit_active"]) == 1:
        employer = INCOME_EMPLOYERS[int(rng.integers(0, len(INCOME_EMPLOYERS)))]
        monthly = float(user["dd_amount_monthly"])
        for k in range(3):
            deposits.append({
                "date": (AS_OF - dt.timedelta(days=30 * k + int(rng.integers(0, 4)))).isoformat(),
                "amount_usd": round(monthly / 2, 2),
                "source": employer,
            })

    return {
        "user_id": user_id,
        "as_of": AS_OF.isoformat(),
        "window_days": 90,
        "fee_events": fee_events,
        "advances": advances,
        "subscriptions": subscriptions,
        "direct_deposits": deposits,
    }
