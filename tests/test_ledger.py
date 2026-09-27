"""Feature 001 — tasks T031-T033. Success criterion SC-002."""
from __future__ import annotations

import pytest

from f2g.data.accounts import build_ledger, repository
from f2g.data.catalog import FREE_TIER_FEES


@pytest.fixture(scope="module")
def repo():
    try:
        return repository()
    except FileNotFoundError:
        pytest.skip("run `python -m f2g.data.generate` first")


def test_fee_events_reconcile_to_aggregates(repo):
    """SC-002: detail and aggregate must tell the same story, to the cent.

    If these diverge, the model scores a user on one fee total while the agent
    quotes another — the same user, two contradictory stories, and no error
    anywhere.
    """
    sample = repo.frame.sample(400, random_state=0)
    for row in sample.to_dict("records"):
        led = build_ledger(row["user_id"])
        instant = sum(e["amount_usd"] for e in led["fee_events"] if e["type"] == "instant_transfer")
        overdraft = sum(e["amount_usd"] for e in led["fee_events"] if e["type"] == "overdraft")
        assert instant == pytest.approx(row["instant_transfer_fees_90d"], abs=0.01), row["user_id"]
        assert overdraft == pytest.approx(row["overdraft_fees_90d"], abs=0.01), row["user_id"]


def test_subscription_spend_reconciles(repo):
    sample = repo.frame.sample(250, random_state=1)
    for row in sample.to_dict("records"):
        led = build_ledger(row["user_id"])
        total = sum(s["monthly_usd"] for s in led["subscriptions"])
        assert total == pytest.approx(row["recurring_subscription_spend"], abs=0.05), row["user_id"]


def test_ledger_is_stable_across_calls(repo):
    uid = repo.frame.iloc[42]["user_id"]
    first = build_ledger(uid)
    build_ledger.cache_clear()
    second = build_ledger(uid)
    assert first == second


def test_fee_amounts_come_from_the_catalog(repo):
    sample = repo.frame[repo.frame.instant_transfer_fees_90d > 0].head(50)
    for uid in sample.user_id:
        for e in build_ledger(uid)["fee_events"]:
            expected = FREE_TIER_FEES[
                "instant_transfer_fee" if e["type"] == "instant_transfer" else "overdraft_fee_typical"
            ]
            assert e["amount_usd"] == expected


def test_no_duplicate_fee_dates_within_type(repo):
    """Two identical fees on one date would read to a user as a double charge."""
    sample = repo.frame[repo.frame.instant_transfer_fees_90d > 20].head(40)
    for uid in sample.user_id:
        led = build_ledger(uid)
        for kind in ("instant_transfer", "overdraft"):
            dates = [e["date"] for e in led["fee_events"] if e["type"] == kind]
            assert len(dates) == len(set(dates)), uid


def test_zero_activity_users_produce_empty_collections(repo):
    quiet = repo.frame[
        (repo.frame.advances_90d == 0)
        & (repo.frame.overdraft_fees_90d == 0)
        & (repo.frame.direct_deposit_active == 0)
    ]
    if quiet.empty:
        pytest.skip("no fully quiet users in this cohort")
    led = build_ledger(quiet.iloc[0]["user_id"])
    assert led["advances"] == []
    assert led["direct_deposits"] == []
    assert all(e["type"] != "overdraft" for e in led["fee_events"])


def test_unknown_user_raises_distinguishably(repo):
    """Never an empty ledger — that would read as 'this user has no fees'."""
    with pytest.raises(KeyError):
        build_ledger("definitely-not-a-user")


def test_events_are_newest_first(repo):
    uid = repo.frame[repo.frame.instant_transfer_fees_90d > 10].iloc[0]["user_id"]
    dates = [e["date"] for e in build_ledger(uid)["fee_events"]]
    assert dates == sorted(dates, reverse=True)
