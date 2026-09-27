"""Deterministic variant assignment.

Assignment is a pure function of (user id, experiment id). Nothing is stored to
decide it, so the same user always lands in the same arm — on every request, in
every process, after any restart, whether or not the event store was reachable.

An assignment that can drift invalidates the experiment silently: a user who
sees the treatment on Monday and the control on Tuesday contaminates both arms
and no analysis can recover from it.

Salting with the experiment id means successive experiments partition the
population independently. Without the salt, every experiment would split users
the same way, and a user unlucky in one test would be unlucky in all of them —
correlated assignment across experiments that nobody would notice until the
results stopped reproducing.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

BUCKETS = 10_000


@dataclass(frozen=True)
class Arm:
    name: str
    share: float
    description: str = ""


@dataclass(frozen=True)
class Experiment:
    id: str
    arms: tuple[Arm, ...]
    primary_metric: str = "conversion"
    guardrail_metric: str = "retained_30d"
    guardrail_margin: float = 0.03  # non-inferiority margin, absolute
    planned_horizon_days: int = 28

    def __post_init__(self) -> None:
        total = sum(a.share for a in self.arms)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"arm shares must sum to 1.0, got {total}")

    @property
    def arm_names(self) -> list[str]:
        return [a.name for a in self.arms]


# The shipped design. Three arms, because two would not separate "the agent
# helped" from "any nudge helped".
DEFAULT_EXPERIMENT = Experiment(
    id="genius-concierge-2026q4",
    arms=(
        Arm("agent_concierge", 0.40, "Uplift-targeted, agent-written grounded explanation"),
        Arm("generic_upsell", 0.40, "Uplift-targeted, existing static upsell copy"),
        Arm("holdout", 0.20, "Eligible and deliberately not contacted"),
    ),
)


def bucket(user_id: str, experiment_id: str) -> int:
    digest = hashlib.sha256(f"{experiment_id}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS


def assign(user_id: str, experiment: Experiment = DEFAULT_EXPERIMENT) -> str:
    b = bucket(user_id, experiment.id)
    edge = 0.0
    for arm in experiment.arms:
        edge += arm.share
        if b < edge * BUCKETS:
            return arm.name
    return experiment.arms[-1].name


def assign_many(user_ids: Sequence[str], experiment: Experiment = DEFAULT_EXPERIMENT) -> dict[str, str]:
    return {uid: assign(uid, experiment) for uid in user_ids}
