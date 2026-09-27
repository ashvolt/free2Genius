"""Scoring and generation services behind the HTTP layer.

Models and cohorts load once per process. The alternative — loading per request
— turns a 40 ms scoring call into a 3 s one and makes the API useless for the
console.

Startup is deliberately strict: if the model artifacts are missing, the service
refuses to start and names the command that builds them. A service that starts
happily and serves wrong numbers is worse than one that will not start.
"""
from __future__ import annotations

import functools
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from f2g import config
from f2g.agent.concierge import ConciergeAgent
from f2g.data.accounts import repository
from f2g.ml.policy import PolicyConfig, Reason, estimate_value_fit_vectorized, select
from f2g.ml.registry import ModelBundle


@dataclass
class ScoringService:
    propensity: Any
    uplift: Any
    meta: dict[str, str]

    @classmethod
    def load(cls) -> "ScoringService":
        prop = ModelBundle.load("propensity")
        upl = ModelBundle.load("uplift_x")
        return cls(
            propensity=prop.estimator,
            uplift=upl.estimator,
            meta={
                "propensity": f"{prop.meta.name}@{prop.meta.data_fingerprint}",
                "uplift": f"{upl.meta.name}@{upl.meta.data_fingerprint}",
            },
        )

    def score_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["uplift"] = self.uplift.predict_uplift(frame)
        out["propensity"] = self.propensity.predict_proba(frame)
        return out


@functools.lru_cache(maxsize=1)
def scoring() -> ScoringService:
    return ScoringService.load()


@functools.lru_cache(maxsize=1)
def scored_live() -> pd.DataFrame:
    """The live cohort, scored and decided, cached for the process lifetime."""
    frame = repository().frame
    live = frame[frame.cohort == "live"].reset_index(drop=True)
    scored = scoring().score_frame(live)
    value_fit = estimate_value_fit_vectorized(scored)
    result = select(scored, scored["uplift"].to_numpy(), scored["propensity"].to_numpy(),
                    PolicyConfig(), value_fit=value_fit)
    return result.decisions


@functools.lru_cache(maxsize=1)
def live_policy_summary() -> dict[str, Any]:
    frame = repository().frame
    live = frame[frame.cohort == "live"].reset_index(drop=True)
    scored = scoring().score_frame(live)
    value_fit = estimate_value_fit_vectorized(scored)
    result = select(scored, scored["uplift"].to_numpy(), scored["propensity"].to_numpy(),
                    PolicyConfig(), value_fit=value_fit)
    return {"summary": result.summary, "fairness": result.fairness.to_dict("records")}


def score_user(user_id: str) -> dict[str, Any]:
    decisions = scored_live()
    row = decisions[decisions.user_id == user_id]
    if row.empty:
        # A pilot-cohort user can still be scored on demand; only the live
        # cohort is precomputed.
        user = repository().get(user_id)
        if user is None:
            raise KeyError(user_id)
        frame = pd.DataFrame([user])
        scored = scoring().score_frame(frame)
        vf = estimate_value_fit_vectorized(scored)
        res = select(scored, scored["uplift"].to_numpy(), scored["propensity"].to_numpy(),
                     PolicyConfig(), value_fit=vf)
        row = res.decisions
    r = row.iloc[0]
    return {
        "user_id": r["user_id"],
        "segment": r.get("segment"),
        "income_band": r.get("income_band"),
        "propensity": float(r["propensity"]) if pd.notna(r["propensity"]) else None,
        "uplift": float(r["uplift"]),
        "decision": r["decision"],
        "reason_detail": r["reason_detail"],
        "value_fit": {
            "estimated_saving_90d": float(r["estimated_saving_90d"]),
            "genius_cost_90d": float(r["genius_cost_90d"]),
            "net_position_90d": float(r["net_position_90d"]),
            "passes": bool(r["decision"] != Reason.VALUE_FIT),
        },
        "model_versions": scoring().meta,
    }


# --- agent generation, with a cache ---------------------------------------
# Local generation takes tens of seconds, so a repeat request inside the window
# must not pay that again. The cache key includes the prompt version so a policy
# change invalidates every cached message rather than serving stale copy.

_NUDGE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
NUDGE_TTL_S = float(config.__dict__.get("NUDGE_TTL_S", 900))


def _cache_key(user_id: str, provider: str | None) -> str:
    from f2g.agent import prompts

    raw = f"{user_id}:{provider or config.LLM_PROVIDER}:{prompts.PROMPT_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def nudge(user_id: str, provider: str | None = None, *, refresh: bool = False) -> dict[str, Any]:
    key = _cache_key(user_id, provider)
    now = time.time()
    if not refresh and key in _NUDGE_CACHE:
        ts, payload = _NUDGE_CACHE[key]
        if now - ts < NUDGE_TTL_S:
            return {**payload, "cached": True}

    from f2g.llm.runtime import build_provider

    agent = ConciergeAgent(user_id, provider=build_provider(provider) if provider else None)
    result = agent.generate_nudge().to_dict()
    result["cached"] = False
    _NUDGE_CACHE[key] = (now, result)
    return result


def chat(user_id: str, message: str, history: list[dict[str, str]] | None = None,
         provider: str | None = None) -> dict[str, Any]:
    from f2g.llm.runtime import build_provider

    agent = ConciergeAgent(user_id, provider=build_provider(provider) if provider else None)
    return agent.chat(message, history=history).to_dict()


def health() -> dict[str, Any]:
    from f2g.llm.runtime import build_provider

    try:
        models_ok = bool(scoring().meta)
        models_detail = scoring().meta
    except FileNotFoundError as exc:
        models_ok, models_detail = False, str(exc)

    try:
        provider = build_provider()
        llm = provider.health()
    except Exception as exc:  # noqa: BLE001 - health must never raise
        llm = {"available": False, "detail": str(exc), "provider": config.LLM_PROVIDER}

    try:
        n_users = len(repository().frame)
        data_ok = True
    except FileNotFoundError as exc:
        n_users, data_ok = 0, False
        models_detail = str(exc)

    return {
        "status": "ok" if (models_ok and data_ok) else "degraded",
        "models": {"available": models_ok, "detail": models_detail},
        "data": {"available": data_ok, "users": n_users},
        "llm": llm,
    }
