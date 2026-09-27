# HLD 001 — Synthetic Data Foundation

**Domain**: A · **Spec**: [001](../../../specs/001-synthetic-data-foundation/spec.md) · **Status**: Implemented

## Responsibility

Produce the population every other feature is validated against, with a property no real dataset
can offer: **the true per-user treatment effect is known.** Also produce event-level detail that
reconciles exactly to the aggregates the models consume, and centralise pricing facts so exactly
one file can state a price.

## Component decomposition

```mermaid
graph TB
  cfg["<b>config</b><br/>seeds · paths · sizes"]

  subgraph gen["generate — the causal model"]
    seg["_draw_segments<br/><i>4 latent archetypes</i>"]
    beh["_behaviour_frame<br/><i>26 observable features</i>"]
    eff["_baseline_and_effect<br/><i>p0 and tau</i>"]
    vf["_value_fit"]
    coh["generate_cohort<br/><i>T, Y, R</i>"]
  end

  sch["<b>schema</b><br/>column contract:<br/>FEATURES vs LABEL vs ORACLE"]

  subgraph acc["accounts — the agent's view"]
    repo["AccountRepository<br/><i>cached lookup</i>"]
    led["build_ledger<br/><i>aggregates → dated events</i>"]
  end

  cat["<b>catalog</b><br/>single source of<br/>pricing truth"]

  pilot[("pilot_users.csv<br/><i>labelled, randomised</i>")]
  live[("live_users.csv<br/><i>unlabelled</i>")]

  cfg --> gen
  seg --> beh --> eff --> coh
  beh --> vf --> coh
  coh --> pilot & live
  pilot & live --> repo --> led
  sch -.->|"enforced contract"| gen
  sch -.->|"enforced contract"| repo

  mdl(["→ 002 models"]) 
  agt(["→ 005 agent tools"])
  pilot --> mdl
  led --> agt
  cat --> agt

  classDef core fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef store fill:#eef2f7,stroke:#8899aa,color:#1b2733
  classDef contract fill:#fff8c5,stroke:#9a6700
  class seg,beh,eff,vf,coh,repo,led core
  class pilot,live store
  class sch,cat contract
```

## Interface contracts

| Consumer | Contract | Guarantee relied upon |
|---|---|---|
| 002 models | `pilot_users.csv` + `schema.FEATURES` | No label or oracle column is in `FEATURES` |
| 003 policy | `live_users.csv` | Same feature columns as pilot, labels sentinel-valued |
| 005 agent tools | `build_ledger(user_id)` | Events reconcile to aggregates to the cent; stable across calls |
| 005 guardrails | `catalog.get_catalog()` | Only sanctioned source of prices and fee amounts |
| 009 fairness | `income_band` column | Correlated with segment, so gaps are real and detectable |

## Data flow — why two views must agree

```mermaid
graph LR
  scm["Structural causal model"] --> agg["<b>Aggregate view</b><br/>instant_transfer_fees_90d = 44.91"]
  agg --> mdl["Models see this"]
  agg --> exp["<b>Event view</b><br/>9 × $4.99 on dated events"]
  exp --> ag["Agent cites this"]

  agg -.->|"MUST reconcile<br/>to the cent"| exp

  classDef warn fill:#fff8c5,stroke:#9a6700
  class exp,agg warn
```

If these diverged, the model would score a user on $44.91 of fees while the agent told them about
$39.92 — the same user, two stories. Reconciliation is enforced by *construction* (fee events are
emitted from the same counts that produced the aggregate; subscription prices are rescaled to the
aggregate) rather than checked afterwards, so the inconsistent state is unreachable.

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| Missing cohort CSVs | `repository()` raises on load | Error names `python -m f2g.data.generate` |
| Unknown user id | `build_ledger` raises `KeyError` | Distinguishable from "user has no fees" — never an empty ledger |
| Aggregate/detail drift | pytest reconciliation over a large sample | Build fails |
| Oracle leakage into features | pytest asserts set disjointness | Build fails |
| `p0 + tau` outside [0,1] | `tau` clipped at generation | Unreachable by construction |

## Key decisions

1. **Segments are latent.** Exposing the archetype as a feature would make uplift modelling a
   lookup and prove nothing.
2. **Ledgers are derived, not stored.** Any user id works, including one invented during a demo,
   and there is no fixture that can drift.
3. **Retention depends on value fit, mediated by whether the nudge caused the conversion.** This is
   what gives the counter-metric teeth and makes [ADR-004](../../adr/ADR-004-value-fit-gate.md)
   demonstrable rather than asserted.
4. **One pricing module.** Makes the grounding guardrail auditable against a single file.
