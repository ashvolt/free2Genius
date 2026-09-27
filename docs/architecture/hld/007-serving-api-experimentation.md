# HLD 007 — Serving API & Experimentation Platform

**Domain**: D · **Spec**: [007](../../../specs/007-serving-api-experimentation/spec.md) · **Status**: Implemented

## Responsibility

Expose the models and the agent over HTTP, assign users to arms in a way that cannot drift,
capture the funnel without double-counting, and analyse the result so it stays valid when
someone reads it every day.

## Component decomposition

```mermaid
graph TB
  client(["console · client"])

  subgraph api["FastAPI — typed in and out"]
    score["/score · /cohort<br/>/policy/summary"]
    agent["/agent/nudge · /agent/chat"]
    exp["/experiment/*"]
    ops["/health · /audit · /telemetry"]
  end

  subgraph svc["service layer — loaded once"]
    sc["ScoringService"]
    sl["scored_live()<br/><i>cohort + policy, cached</i>"]
    nc["nudge cache<br/><i>keyed on user + provider + prompt version</i>"]
  end

  subgraph ana["experiment"]
    asg["assign()<br/><i>sha256(exp:user), pure</i>"]
    seq["sequential analysis<br/><i>always-valid bounds</i>"]
    rule["stopping rules<br/><b>harm checked first</b>"]
  end

  store[("EventStore — SQLite<br/><i>assignments · events<br/>decisions · generations</i>")]
  reg[("model registry")]

  client --> api
  score --> svc --> reg
  agent --> nc
  exp --> asg & seq --> rule
  api --> store
  store --> seq
  api -.->|"startup: fail loudly<br/>if models are missing"| reg

  classDef core fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef store fill:#eef2f7,stroke:#8899aa,color:#1b2733
  class score,agent,exp,ops,sc,asg,seq,rule core
  class store,reg store
```

## Assignment is a pure function

```mermaid
graph LR
  u["user_id"] --> h["sha256(experiment_id + ':' + user_id)"]
  e["experiment_id<br/><i>the salt</i>"] --> h
  h --> b["bucket 0..9999"] --> arm["arm by cumulative share"]
```

Nothing is read to decide an assignment, so it is identical on every request, in every process,
after any restart, and whether or not the store was reachable. An assignment that can drift
invalidates the experiment silently.

The experiment id as salt means successive experiments partition independently. Without it, a
user unlucky in one test is unlucky in all of them — correlated assignment nobody notices until
results stop reproducing.

## Event capture

```mermaid
sequenceDiagram
  participant C as Client
  participant A as API
  participant S as Store

  C->>A: POST /experiment/events {idempotency_key, user, type}
  A->>S: look up the assignment
  alt no assignment
    S-->>A: KeyError
    A-->>C: 409 — cannot attribute this event to an arm
  else assigned
    S->>S: INSERT OR IGNORE on the idempotency key
    S-->>A: {recorded, duplicate, variant}
    A-->>C: 200
  end
```

Both behaviours protect the analysis. At-least-once delivery is normal, so a double-counted
conversion is an invented result; and accepting an event from an unassigned user would bias
whichever arm it was guessed into.

Events carry the variant recorded **at assignment**, so the event side of the analysis never
needs to join back — which is also what made the fast `counts()` possible.

## Analysis: two intervals, one decision rule

```mermaid
graph TB
  d["accumulated events"] --> f["fixed-horizon interval<br/><i>published — what a reviewer asks for</i>"]
  d --> s["always-valid sequence<br/><i>the decision rule</i>"]
  s --> r{"stopping rules<br/><b>in order</b>"}
  r -->|1| harm(["stop for harm"])
  r -->|2| ship(["ship"])
  r -->|3| fut(["stop for futility"])
  r -->|4| cont(["continue"])

  classDef danger fill:#ffebe9,stroke:#cf222e,color:#82071e
  class harm danger
```

Harm is checked **first**. Checking success first would let a conversion win mask a retention
breach for as long as the win held — exactly the failure the guardrail exists to catch.

## Interface contracts

| Endpoint | Guarantee |
|---|---|
| `GET /score/{id}` | Full decision with the binding constraint and the value-fit figures; 404, never a default score |
| `GET /cohort` | Paginated, filterable, with the policy summary attached |
| `POST /agent/nudge/{id}` | Cached by user + provider + **prompt version**, so a policy change invalidates every cached message |
| `POST /experiment/events` | Idempotent; 409 for an unassigned user |
| `GET /experiment/summary` | Both intervals, the guardrail against its margin, and a verdict with its governing rule |
| `GET /audit/{id}` | Every decision, generation, assignment and event for one user |
| `GET /health` | Per-subsystem, including the LLM provider's **egress** statement |

## Failure modes

| Failure | Response |
|---|---|
| Model artifacts missing | Startup fails, naming the command that builds them |
| LLM provider unavailable | Nudge degrades and returns 200 marked `degraded` — a model outage is not a product outage for this surface |
| Duplicate event | Counted once, reported as `duplicate` |
| Event for an unassigned user | 409 |
| Unknown user | 404 |
| Concurrent identical nudge requests | Served from cache after the first |

## A performance defect worth recording

The first `counts()` joined `assignments` to `events` with `COUNT(DISTINCT CASE WHEN …)`. At
45,000 assignments against 59,000 events it did not return within ten minutes, because it built
the full arm × event cross product before aggregating.

Rewritten as two indexed aggregations combined in Python: **125 ms**. A dashboard query has to
be fast enough to read casually — which is the entire premise of the always-valid analysis it
feeds.
