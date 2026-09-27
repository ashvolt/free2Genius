"""Typed request and response models.

Every endpoint is typed, so the published OpenAPI schema is the contract the
front end is written against rather than a document that drifts from it.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ValueFit(BaseModel):
    estimated_saving_90d: float
    genius_cost_90d: float
    net_position_90d: float
    passes: bool


class ScoreResponse(BaseModel):
    user_id: str
    segment: str | None = None
    income_band: str | None = None
    propensity: float | None
    uplift: float
    decision: str
    reason_detail: str = ""
    value_fit: ValueFit
    model_versions: dict[str, str] = Field(default_factory=dict)


class BatchScoreRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=500)


class ChatRequest(BaseModel):
    user_id: str
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)
    provider: str | None = None


class NudgeRequest(BaseModel):
    provider: str | None = None
    refresh: bool = False


class EventRequest(BaseModel):
    user_id: str
    event_type: Literal["impression", "click", "conversion", "retained_30d"]
    idempotency_key: str = Field(min_length=4, max_length=128)
    experiment_id: str | None = None
    value: float | None = None
    out_of_window: bool = False


class PowerRequest(BaseModel):
    baseline_rate: float = Field(gt=0, lt=1)
    mde_relative: float = Field(gt=0, le=2)
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.80, gt=0.5, lt=1)


class CohortRow(BaseModel):
    user_id: str
    segment: str | None = None
    income_band: str | None = None
    uplift: float
    propensity: float | None = None
    estimated_saving_90d: float
    net_position_90d: float
    decision: str
    reason_detail: str = ""


class CohortResponse(BaseModel):
    total: int
    offset: int
    limit: int
    rows: list[CohortRow]
    summary: dict[str, Any] = Field(default_factory=dict)
