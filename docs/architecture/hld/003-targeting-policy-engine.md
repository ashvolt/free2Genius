# HLD 003 — Targeting Policy Engine & Offline Policy Evaluation

**Domain**: B · **Spec**: [003](../../../specs/003-targeting-policy-engine/spec.md) · **Status**: Implemented

## Responsibility

Convert a per-user effect estimate into a decision that can be defended to a user, an analyst
and a regulator — and estimate what that decision would have achieved before it ships.

## Component decomposition

```mermaid
graph TB
  cand[("scored candidates<br/><i>uplift · propensity</i>")]

  subgraph gate["Value-fit assessment"]
    vec["estimate_value_fit_vectorized<br/><i>batch, from aggregates</i>"]
    ref["ConciergeTools.estimate_savings<br/><i>reference, per user</i>"]
    vec -.->|"pinned by test<br/>to the cent"| ref
  end

  subgraph sel["select() — constraints in order"]
    c1["1 · positivity<br/><i>tau &gt; 0, unconditional</i>"]
    c2["2 · value fit<br/><i>saving ≥ cost × margin</i>"]
    c3["3 · budget<br/><i>top-k by tau, ties by id</i>"]
    c4["4 · parity cap<br/><i>optional, by RATE</i>"]
    c1 --> c2 --> c3 --> c4
  end

  log[("decision log<br/><i>every user, with reasons</i>")]
  fair["fairness table<br/><i>contact rate vs eligible rate</i>"]

  subgraph ope["Offline policy evaluation"]
    ips["IPS"]
    snips["SNIPS"]
    dr["doubly robust"]
    orc["oracle<br/><i>from true tau</i>"]
  end

  cand --> sel
  gate --> c2
  sel --> log & fair
  sel --> ope
  orc -.->|"validates the<br/>estimators"| dr

  log --> api(["→ 007 API /score, /audit"])
  fair --> gov(["→ 009 fairness audit"])

  classDef core fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef gate fill:#8250df,stroke:#4c2889,color:#fff
  classDef store fill:#eef2f7,stroke:#8899aa,color:#1b2733
  classDef oracle fill:#fff8c5,stroke:#9a6700
  class c1,c2,c3,c4 core
  class vec,ref gate
  class cand,log store
  class orc oracle
```

## Why the constraints are ordered this way

The order is load-bearing, not incidental.

**Positivity first**, because contacting someone whom contact harms is not a budget question.

**Value fit before budget.** If the budget ran first, a user could be excluded for ranking
poorly and the gate would never evaluate them — the suppression log would show `budget` where
the truthful answer is `value_fit`, and the fairness report would understate how often the gate
binds. Running the gate first means the log records the *real* reason and the freed slots are
visibly redistributed.

**Parity last**, because it should only ever trim a selection the other constraints already
approved.

## The coupling to the agent layer

```mermaid
sequenceDiagram
  participant P as Targeting policy
  participant T as ConciergeTools<br/><i>deterministic</i>
  participant A as Concierge agent

  Note over P,T: eligibility — no model inference
  P->>T: estimate_savings(user)
  T-->>P: saving_90d, cost_90d
  P->>P: suppress if saving < cost × margin

  Note over P,A: only then, for selected users
  P->>A: generate a message
  A->>T: the same tools
  T-->>A: the same figures
```

The gate calls the **tool layer**, not the agent. Three consequences: it needs no inference, so
it runs over 12,000 users in seconds; it is exactly reproducible; and the number that decides
eligibility is the same number the user is later shown — the decision and the explanation
cannot disagree.

## Interface contracts

| Contract | Guarantee |
|---|---|
| `select(candidates, uplift, propensity, cfg, value_fit) → PolicyResult` | Deterministic; ties broken by `user_id` |
| `PolicyResult.decisions` | One row per candidate, every row carrying a decision and a reason |
| `PolicyResult.summary["binding_constraint"]` | Which constraint actually bound, not which was configured |
| `estimate_value_fit_vectorized(frame)` | Agrees with the per-user tool path to the cent |
| `evaluate_policy(frame, pi, mu0, mu1) → DataFrame` | One row per estimator, each with an interval |

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| Every candidate has negative uplift | Empty eligible set | Return empty; never contact the "least bad" to fill a budget |
| Gate suppresses more than the budget | `len(eligible) <= n_budget` | Report `value_fit` as the binding constraint and the budget underuse |
| User has no account data | `has_data` false | Fails the gate — absence of evidence is not evidence of benefit |
| Extreme importance weights in OPE | Weight clipping | Clip at a recorded threshold and report the clipped fraction |
| Fast value-fit path drifts from the agent | `test_value_fit_paths_agree` | Build fails |

## Key decisions

1. **The gate is a constraint, not a feature.** A feature can be traded off against others; a
   constraint cannot. That difference is the entire point.
2. **Parity caps by rate, not count.** Capping counts across bands of unequal size equalises the
   wrong quantity and measurably widened the gap it was meant to close.
3. **The oracle is reported beside the estimators.** It validates the estimator rather than the
   policy — the one check synthetic data uniquely permits.
4. **Both sides of the gate are always reported.** Users suppressed, conversions forgone, mean
   benefit with and without. A trade reported in one direction only is advocacy.
