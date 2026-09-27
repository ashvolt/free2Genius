"""Simulate a running experiment so the console has something to show.

Not a fixture file: it replays the *pilot* cohort's real simulated outcomes
through the live assignment and event pipeline, so the dashboard is driven by
the same code path production would use. A hand-written fixture would let the
dashboard look right while the pipeline was broken.

The three arms are given different effect sizes drawn from the data itself:

* `agent_concierge`  — the grounded agent nudge; receives the full treatment
  effect, because a message built from the user's own fees is what the pilot's
  treatment represented.
* `generic_upsell`   — static copy; receives a fraction of it, reflecting that
  generic copy moves fewer people.
* `holdout`          — eligible, deliberately not contacted; baseline only.

Run: `python scripts/seed_experiment.py [--days 21]`
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

# Runnable directly (`python scripts/seed_experiment.py`) without requiring the
# package to be installed or PYTHONPATH to be set — one less step between a
# reviewer and a working demo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from f2g import config
from f2g.api.store import EventStore
from f2g.experiment.assign import DEFAULT_EXPERIMENT, assign

# How much of the measured treatment effect each arm realises.
ARM_EFFECT = {"agent_concierge": 1.00, "generic_upsell": 0.45, "holdout": 0.0}

# Retention among converters. The generic arm converts fewer people but also
# retains them worse, because it persuades without regard to value fit — which
# is exactly the harm the guardrail metric exists to detect.
ARM_RETENTION_PENALTY = {"agent_concierge": 0.0, "generic_upsell": 0.06, "holdout": 0.0}


def seed(days: int = 21, n_users: int = 45000, seed_value: int = 4242) -> dict[str, int]:
    """Bulk-load the simulated experiment.

    Written as batched `executemany` against one connection rather than a call
    per event. The per-event API on `EventStore` is the right shape for the
    request path — idempotent, one row, safe under concurrency — and exactly the
    wrong shape for loading 180,000 rows, where it spends all its time opening
    connections. Backfills and request paths have different access patterns and
    it is worth writing both.
    """
    rng = np.random.default_rng(seed_value)
    pilot = pd.read_csv(config.DATA_DIR / "pilot_users.csv")
    if n_users < len(pilot):
        pilot = pilot.sample(n_users, random_state=seed_value)

    store = EventStore()  # ensures the schema exists
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    assignments: list[tuple] = []
    events: list[tuple] = []
    counts = {"assignments": 0, "impressions": 0, "conversions": 0, "retention": 0}

    uids = pilot["user_id"].to_numpy()
    p0 = pilot["p0"].to_numpy(dtype=float)
    tau = pilot["true_tau"].to_numpy(dtype=float)
    value_fit = pilot["value_fit"].to_numpy(dtype=float)

    variants = np.array([assign(u, DEFAULT_EXPERIMENT) for u in uids])
    effect = np.array([ARM_EFFECT[v] for v in variants])
    penalty = np.array([ARM_RETENTION_PENALTY[v] for v in variants])

    p_convert = np.clip(p0 + tau * effect, 0, 1)
    converted = rng.random(len(uids)) < p_convert
    retain_p = np.clip(0.58 + 0.34 * value_fit - penalty, 0.05, 0.97)
    retained = rng.random(len(uids)) < retain_p

    day_offsets = rng.integers(0, days, len(uids))
    hour_offsets = rng.integers(0, 24, len(uids))

    for i, uid in enumerate(uids):
        variant = variants[i]
        ts = (start + dt.timedelta(days=int(day_offsets[i]), hours=int(hour_offsets[i]))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        assignments.append((uid, DEFAULT_EXPERIMENT.id, variant, ts))
        events.append((f"imp-{uid}", uid, DEFAULT_EXPERIMENT.id, variant, "impression", None, ts, 0))
        counts["impressions"] += 1
        if converted[i]:
            events.append(
                (f"conv-{uid}", uid, DEFAULT_EXPERIMENT.id, variant, "conversion", 1.0, ts, 0)
            )
            counts["conversions"] += 1
            events.append(
                (f"ret-{uid}", uid, DEFAULT_EXPERIMENT.id, variant, "retained_30d",
                 1.0 if retained[i] else 0.0, ts, 0)
            )
            counts["retention"] += 1
    counts["assignments"] = len(assignments)

    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM events WHERE experiment_id = ?", (DEFAULT_EXPERIMENT.id,))
        conn.execute("DELETE FROM assignments WHERE experiment_id = ?", (DEFAULT_EXPERIMENT.id,))
        conn.executemany(
            "INSERT OR IGNORE INTO assignments (user_id, experiment_id, variant, assigned_at) "
            "VALUES (?,?,?,?)",
            assignments,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO events (idempotency_key, user_id, experiment_id, variant, "
            "event_type, value, occurred_at, out_of_window) VALUES (?,?,?,?,?,?,?,?)",
            events,
        )
        conn.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--users", type=int, default=45000)
    args = parser.parse_args()

    counts = seed(args.days, args.users)
    print(f"seeded {counts}")

    from fastapi.testclient import TestClient
    from f2g.api.main import app

    summary = TestClient(app).get("/experiment/summary").json()
    print("\narms:")
    for arm in summary["arms"]:
        print(f"  {arm['arm']:17s} n={arm['n']:5d}  conv={arm['rate']:.4f}  "
              f"retention={arm['retention_rate']:.4f}")
    c = summary["conversion"]
    r = summary["retention_guardrail"]
    print(f"\nconversion lift : {c['absolute_lift']:+.4f} "
          f"({c['relative_lift']:+.1%})")
    print(f"  fixed CI      : [{c['fixed_ci'][0]:+.4f}, {c['fixed_ci'][1]:+.4f}]  p={c['fixed_p_value']:.4g}")
    print(f"  sequential CI : [{c['sequential_ci'][0]:+.4f}, {c['sequential_ci'][1]:+.4f}]")
    print(f"retention guard : {r['absolute_lift']:+.4f}  margin -{r['margin']:.3f}")
    print(f"  sequential CI : [{r['sequential_ci'][0]:+.4f}, {r['sequential_ci'][1]:+.4f}]")
    print(f"\nVERDICT: {summary['verdict']['verdict']} — {summary['verdict']['rule']}")
    print(f"         {summary['verdict']['detail']}")


if __name__ == "__main__":
    main()
