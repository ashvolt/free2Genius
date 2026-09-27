"""SQLite event store and audit log.

Four tables, each with a reason to exist:

* `assignments` — who is in which arm. Written once, never updated, because a
  user whose arm changes contaminates both.
* `events` — the funnel. Idempotent on a caller-supplied key, because delivery
  is at-least-once in every real system and a double-counted conversion is an
  invented result.
* `decisions` — why each user was or was not contacted, captured at decision
  time. Reconstructed after the fact it is not evidence (feature 009, FR-001).
* `generations` — what the agent said, what it read, which gates it passed, and
  which prompt and models produced it.

SQLite is behind this module rather than in the request handlers, so the swap to
Postgres is a file change and not a rewrite. At demonstration scale it is the
right call and pretending otherwise would be complexity for its own sake.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from f2g import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    user_id        TEXT NOT NULL,
    experiment_id  TEXT NOT NULL,
    variant        TEXT NOT NULL,
    assigned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS events (
    idempotency_key TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    experiment_id   TEXT NOT NULL,
    variant         TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    value           REAL,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now')),
    out_of_window   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_exp ON events (experiment_id, variant, event_type);
CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_id, experiment_id);
CREATE INDEX IF NOT EXISTS idx_assignments_exp ON assignments (experiment_id, variant);

CREATE TABLE IF NOT EXISTS decisions (
    user_id        TEXT NOT NULL,
    cycle_id       TEXT NOT NULL,
    decision       TEXT NOT NULL,
    reason_detail  TEXT,
    uplift         REAL,
    propensity     REAL,
    estimated_saving_90d REAL,
    genius_cost_90d      REAL,
    binding_constraint   TEXT,
    model_versions TEXT,
    decided_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, cycle_id)
);

CREATE TABLE IF NOT EXISTS generations (
    generation_id  TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    message        TEXT NOT NULL,
    tool_calls     TEXT NOT NULL,
    evidence       TEXT NOT NULL,
    guardrails     TEXT NOT NULL,
    telemetry      TEXT NOT NULL,
    degraded       INTEGER NOT NULL DEFAULT 0,
    degraded_reason TEXT,
    prompt_version TEXT,
    generated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_generations_user ON generations (user_id);
"""


class EventStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- assignments ------------------------------------------------------

    def record_assignment(self, user_id: str, experiment_id: str, variant: str) -> str:
        """Idempotent. The first assignment wins and is never overwritten."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO assignments (user_id, experiment_id, variant) "
                "VALUES (?, ?, ?)",
                (user_id, experiment_id, variant),
            )
            row = conn.execute(
                "SELECT variant FROM assignments WHERE user_id = ? AND experiment_id = ?",
                (user_id, experiment_id),
            ).fetchone()
        return row["variant"]

    def get_assignment(self, user_id: str, experiment_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT variant FROM assignments WHERE user_id = ? AND experiment_id = ?",
                (user_id, experiment_id),
            ).fetchone()
        return row["variant"] if row else None

    # -- events -----------------------------------------------------------

    def record_event(
        self, *, idempotency_key: str, user_id: str, experiment_id: str,
        event_type: str, value: float | None = None, out_of_window: bool = False,
    ) -> dict[str, Any]:
        variant = self.get_assignment(user_id, experiment_id)
        if variant is None:
            # An event from a user with no assignment cannot be attributed to an
            # arm. Accepting it would quietly bias whichever arm it was guessed
            # into, so it is refused.
            raise KeyError(f"user {user_id} has no assignment in {experiment_id}")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events "
                "(idempotency_key, user_id, experiment_id, variant, event_type, value, out_of_window) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (idempotency_key, user_id, experiment_id, variant, event_type, value,
                 int(out_of_window)),
            )
            inserted = cur.rowcount > 0
        return {"recorded": inserted, "duplicate": not inserted, "variant": variant}

    def counts(self, experiment_id: str) -> list[dict[str, Any]]:
        """Per-arm funnel counts.

        Two indexed aggregations combined in Python, rather than one join.
        The obvious formulation — LEFT JOIN assignments to events with
        COUNT(DISTINCT CASE WHEN ...) — builds the full cross product of arms
        and events before aggregating, and at 45,000 assignments against 59,000
        events it did not return inside ten minutes. A dashboard query has to be
        fast enough to be read casually, which is the whole premise of the
        always-valid analysis it feeds.

        Events carry their own `variant` column (written at insert from the
        assignment), so the event side never needs the join at all.
        """
        with self._connect() as conn:
            arm_rows = conn.execute(
                "SELECT variant, COUNT(*) AS n FROM assignments "
                "WHERE experiment_id = ? GROUP BY variant",
                (experiment_id,),
            ).fetchall()
            event_rows = conn.execute(
                """
                SELECT variant,
                       event_type,
                       COUNT(DISTINCT user_id) AS users,
                       SUM(CASE WHEN value = 1 THEN 1 ELSE 0 END) AS positives
                FROM events
                WHERE experiment_id = ? AND out_of_window = 0
                GROUP BY variant, event_type
                """,
                (experiment_id,),
            ).fetchall()

        by_arm: dict[str, dict[str, Any]] = {
            r["variant"]: {
                "variant": r["variant"], "n": r["n"], "conversions": 0,
                "retained": 0, "retention_observed": 0,
            }
            for r in arm_rows
        }
        for r in event_rows:
            arm = by_arm.setdefault(
                r["variant"],
                {"variant": r["variant"], "n": 0, "conversions": 0,
                 "retained": 0, "retention_observed": 0},
            )
            if r["event_type"] == "conversion":
                arm["conversions"] = int(r["users"])
            elif r["event_type"] == "retained_30d":
                arm["retention_observed"] = int(r["users"])
                arm["retained"] = int(r["positives"] or 0)
        return list(by_arm.values())

    def timeseries(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT date(occurred_at) AS day, variant, event_type, COUNT(*) AS n
                FROM events WHERE experiment_id = ? AND out_of_window = 0
                GROUP BY day, variant, event_type ORDER BY day
                """,
                (experiment_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- audit ------------------------------------------------------------

    def record_decision(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decisions (user_id, cycle_id, decision, reason_detail, "
                "uplift, propensity, estimated_saving_90d, genius_cost_90d, binding_constraint, "
                "model_versions) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record["user_id"], record["cycle_id"], record["decision"],
                    record.get("reason_detail"), record.get("uplift"),
                    record.get("propensity"), record.get("estimated_saving_90d"),
                    record.get("genius_cost_90d"), record.get("binding_constraint"),
                    json.dumps(record.get("model_versions", {})),
                ),
            )

    def record_generation(self, generation_id: str, result: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO generations (generation_id, user_id, message, tool_calls, "
                "evidence, guardrails, telemetry, degraded, degraded_reason, prompt_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    generation_id, result["user_id"], result["message"],
                    json.dumps(result.get("tool_calls", []), default=str),
                    json.dumps(result.get("evidence", []), default=str),
                    json.dumps(result.get("guardrails", {}), default=str),
                    json.dumps(result.get("telemetry", {}), default=str),
                    int(bool(result.get("degraded"))), result.get("degraded_reason", ""),
                    result.get("prompt_version", ""),
                ),
            )

    def explain(self, user_id: str) -> dict[str, Any]:
        """Everything the system recorded about one user — the audit answer."""
        with self._connect() as conn:
            decisions = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM decisions WHERE user_id = ? ORDER BY decided_at DESC", (user_id,)
                ).fetchall()
            ]
            generations = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM generations WHERE user_id = ? ORDER BY generated_at DESC",
                    (user_id,),
                ).fetchall()
            ]
            assignments = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM assignments WHERE user_id = ?", (user_id,)
                ).fetchall()
            ]
            events = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM events WHERE user_id = ? ORDER BY occurred_at", (user_id,)
                ).fetchall()
            ]
        return {
            "user_id": user_id,
            "assignments": assignments,
            "decisions": decisions,
            "generations": generations,
            "events": events,
        }

    def generation_telemetry(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT telemetry, guardrails, degraded, degraded_reason, prompt_version "
                "FROM generations ORDER BY generated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
