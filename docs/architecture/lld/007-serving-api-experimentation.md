# LLD 007 — Serving API & Experimentation Platform

**Domain**: D · **HLD**: [007](../hld/007-serving-api-experimentation.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/api/main.py` | Routes, lifespan, CORS |
| `f2g/api/schemas.py` | Typed request/response models |
| `f2g/api/service.py` | Loaded-once scoring, cohort cache, nudge cache, health |
| `f2g/api/store.py` | SQLite schema and access |
| `f2g/api/telemetry.py` | Aggregate agent telemetry |
| `f2g/experiment/assign.py` | Deterministic bucketing, experiment configuration |
| `f2g/experiment/analysis.py` | Comparisons, sequential bounds, power, stopping rules |
| `scripts/seed_experiment.py` | Bulk-load a simulated run |

## Schema

```sql
assignments (user_id, experiment_id, variant, assigned_at)   PK (user_id, experiment_id)
events      (idempotency_key PK, user_id, experiment_id, variant,
             event_type, value, occurred_at, out_of_window)
decisions   (user_id, cycle_id, decision, reason_detail, uplift, propensity,
             estimated_saving_90d, genius_cost_90d, binding_constraint,
             model_versions, decided_at)                     PK (user_id, cycle_id)
generations (generation_id PK, user_id, message, tool_calls, evidence,
             guardrails, telemetry, degraded, degraded_reason,
             prompt_version, generated_at)

INDEX idx_events_exp        ON events (experiment_id, variant, event_type)
INDEX idx_events_user       ON events (user_id, experiment_id)
INDEX idx_assignments_exp   ON assignments (experiment_id, variant)
```

`INSERT OR IGNORE` on both `assignments` and `events` gives idempotency without a read-modify-
write race: the first assignment wins and is never overwritten.

## Sequential inference

```text
z_fixed(α)  = Φ⁻¹(1 − α/2)                                        = 1.96 at α = 0.05
z_seq(n, α) = sqrt( (2(nρ² + 1) / nρ²) · ln( sqrt(nρ² + 1) / α ) )   ρ = 0.05

se   = sqrt( p₁(1−p₁)/n₁ + p₀(1−p₀)/n₀ )
CI   = Δ ± z · se
```

An asymptotic normal-mixture confidence sequence (Howard, Ramdas, McAuliffe & Sekhon 2021).
`z_seq` grows like `sqrt(log n)` — the price of unlimited looks. `ρ` tunes where the sequence is
tightest; smaller values favour later sample sizes.

**Coverage is verified by simulation rather than asserted.** `false_positive_simulation` runs a
null experiment, reads it `n_looks` times, and counts how often each method declares a winner:

| method | 200 looks, no true effect, α = 0.05 |
|---|---|
| naive fixed-horizon, re-read each time | **0.49** |
| always-valid sequence | **0.03** |

## Stopping rules

```python
if retention.sequential_ci[1] < -margin:   return STOP_FOR_HARM      # checked FIRST
if conversion.sequential_ci[0] > 0 \
   and retention.sequential_ci[0] > -margin: return SHIP             # both, not either
if horizon_reached:                         return STOP_FOR_FUTILITY
return CONTINUE
```

Every verdict carries a `rule` and a `detail` so the dashboard can say *why*, not just *what*.

## Power

```text
n = ( z_{α/2}·sqrt(2·p̄(1−p̄)) + z_β·sqrt(p₀(1−p₀) + p₁(1−p₁)) )² / (p₁ − p₀)²
n_sequential = ceil(n × 1.20)
```

At a 15% baseline and a 10% relative MDE: **9,257** per arm fixed, **11,109** sequential.

## The counts query

```python
# Two indexed aggregations, combined in Python.
arm_rows   = "SELECT variant, COUNT(*) FROM assignments WHERE experiment_id=? GROUP BY variant"
event_rows = """SELECT variant, event_type, COUNT(DISTINCT user_id) AS users,
                       SUM(CASE WHEN value = 1 THEN 1 ELSE 0 END) AS positives
                FROM events WHERE experiment_id=? AND out_of_window=0
                GROUP BY variant, event_type"""
```

The event side never joins, because events carry their own `variant`, written at insert from the
assignment. 125 ms against a join formulation that exceeded ten minutes.

## Caching

| Cache | Key | Why |
|---|---|---|
| `scoring()` | process | Per-request model loading turns 40 ms into 3 s |
| `scored_live()` | process | The whole live cohort scored and decided once |
| `_NUDGE_CACHE` | `sha256(user : provider : prompt_version)` | Local generation is tens of seconds; including the prompt version means a policy change invalidates every cached message rather than serving stale copy |

## Test isolation

`tests/conftest.py` sets `F2G_DB_PATH` to a temporary database **before `f2g.config` is
imported**, because paths resolve at import time and conftest loads before any test module.

Without it the suite wrote into `data/events.db` — the same file the demo and console use — so a
test asserting that an event was newly recorded passed once and failed on every rerun. The
symptom was an order-dependent test; the defect was that tests touched demo state at all.

## Bulk loading

The per-event store API is idempotent, single-row and concurrency-safe, which is right for the
request path and wrong for loading 180,000 rows — it spends all its time opening connections.
`seed_experiment.py` uses batched `executemany` on one connection. Backfills and request paths
have different access patterns, and it is worth writing both.

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_assignment_is_stable` | 20 calls, 200 users, one variant each |
| `test_arm_proportions_match_configuration` | Within 1 pp at 10,000 users |
| `test_different_experiments_partition_independently` | The salt works |
| `test_null_experiment_repeated_looks` | The headline statistical claim |
| `test_harm_is_checked_before_success` | Rule ordering |
| `test_event_idempotency` | No double counting |
| `test_event_for_unassigned_user_is_rejected` | 409 |
| `test_nudge_is_grounded_and_cached` | Cache behaviour |
| `test_audit_returns_the_full_record` | The audit answer exists |
