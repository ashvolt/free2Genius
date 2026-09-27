# Implementation Plan: Serving Api Experimentation

**Feature**: `007` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/007-serving-api-experimentation.md)** · **[LLD](../../docs/architecture/lld/007-serving-api-experimentation.md)**

## Summary

One FastAPI process serving scoring, agent generation, assignment, event capture, always-valid
analysis, audit and telemetry, over a SQLite store, with models loaded once and startup that
fails loudly when artifacts are missing.

## Technical Context

**Language/Version**: Python 3.11 · **Dependencies**: FastAPI, uvicorn, pydantic v2, SQLite, SciPy
**Testing**: pytest + `TestClient`; every endpoint has an integration test
**Performance**: single-user scoring p95 under 50 ms warm; cached nudge under 20 ms; the
experiment summary at 125 ms over 45k assignments
**Constraints**: no authentication (stated everywhere); single process

## Constitution Check

| Principle | Satisfied by |
|---|---|
| V. Goal metric with counter-metric | Retention guardrail is first-class, checked before any ship verdict |
| VI. Reproducible | Assignment is a pure function; events are idempotent |
| IV. Guardrails as code | Sequential coverage verified by simulation, not asserted |
| VIII. Synthetic data stated | In the OpenAPI description, `/health`, and every summary payload |

**Result**: Pass, with one accepted violation.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| No authentication | Demonstration scope | Nothing simpler; the risk is **accepted** and stated in the README, OpenAPI description, console footer and risk register R12 rather than hidden |
| SQLite rather than Postgres | Right at this scale | Postgres would add operational surface with no benefit; the store sits behind an interface so the swap is bounded |
| Two code paths for event writes | Request path needs idempotency and concurrency safety; backfill needs throughput | One path is either slow enough to make seeding unusable or unsafe in the request path |
