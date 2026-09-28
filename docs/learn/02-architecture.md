# Part 2 — System architecture (HLD)

**Written for: you, learning the project.** Previous: [why this exists](01-why-this-exists.md) · Next: [decision layer](03-decision-layer.md)

This is the high-level design: what the pieces are, how they connect, and one request
traced all the way through. Part 3 onwards goes inside each piece.

---

## 2.1 Context — who touches the system

```mermaid
graph TB
  user(["Free user<br/><i>mobile app</i>"])
  growth(["Growth analyst<br/><i>experiment console</i>"])
  risk(["Risk &amp; compliance<br/><i>audit reader</i>"])

  sys["<b>Free2Genius</b><br/>propensity + agent<br/>growth system"]

  core[("Core banking / ledger<br/><i>simulated</i>")]
  weights[("Open-weights model files<br/><i>GGUF, on local disk</i>")]

  user -->|"sees a nudge,<br/>chats with the concierge"| sys
  sys -->|"grounded explanation<br/>+ upgrade offer"| user
  growth -->|"conversion by variant,<br/>guardrails, suppression log"| sys
  risk -->|"model card, fairness audit,<br/>per-user decision log"| sys
  core -->|"accounts, advances,<br/>fee events"| sys
  weights -.->|"loaded in-process,<br/>no network"| sys

  classDef system fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef ext fill:#eef2f7,stroke:#8899aa,color:#1b2733
  class sys system
  class core,weights ext
```

Notice what is **absent**: there is no inference vendor in this diagram. Model weights
are read from local disk into the serving process. That is a deliberate decision and
part 4 explains what it buys.

---

## 2.2 Containers — the five tiers

```mermaid
graph TB
  subgraph client["Client tier"]
    web["<b>Web console</b><br/>React + TypeScript + Vite<br/><i>targeting · concierge · experiment</i>"]
  end

  subgraph service["Service tier — one process, one trust boundary"]
    api["<b>Serving API</b> · FastAPI<br/><i>/score /cohort /agent/* /experiment/* /audit</i>"]
    policy["<b>Targeting policy</b><br/><i>constrained selection + value-fit gate</i>"]
    agent["<b>Concierge agent</b><br/><i>tool loop · guardrails</i>"]
    runtime["<b>LLM runtime</b><br/><i>provider abstraction · GBNF grammar · repair</i>"]
    tools["<b>Tool layer</b><br/><i>6 account-data tools · value ledger</i>"]
  end

  subgraph model["Model tier — offline, batch"]
    train["<b>Training</b> · LightGBM<br/><i>propensity · S · T · X learners</i>"]
    evalm["<b>Model evaluation</b><br/><i>AUC · Qini · calibration · fairness</i>"]
    evala["<b>Agent evaluation</b><br/><i>golden set · grounding gate · judge</i>"]
  end

  subgraph data["Data tier"]
    cohorts[("Cohorts<br/><i>pilot + live CSV</i>")]
    ledger[("Account ledger<br/><i>derived, deterministic</i>")]
    reg[("Model registry<br/><i>artifacts/models/</i>")]
    events[("Event store · SQLite<br/><i>assignments · events<br/>decisions · generations</i>")]
    gguf[("GGUF weights<br/><i>1.5B fast · 3B quality</i>")]
  end

  web <-->|JSON over HTTP| api
  api --> policy & agent
  agent --> runtime & tools
  runtime --> gguf
  tools --> ledger & cohorts
  policy --> reg
  policy -->|"value-fit gate calls tools directly.<br/><b>No model inference.</b>"| tools
  api --> events
  cohorts --> train --> reg
  train --> evalm
  agent --> evala

  classDef svc fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef off fill:#8250df,stroke:#4c2889,color:#fff
  classDef store fill:#eef2f7,stroke:#8899aa,color:#1b2733
  classDef ui fill:#1a7f37,stroke:#0f5323,color:#fff
  class api,policy,agent,runtime,tools svc
  class train,evalm,evala off
  class cohorts,ledger,reg,events,gguf store
  class web ui
```

### The one edge worth staring at

`policy → tools` is the value-fit gate from part 1, and it is the architectural
signature of this project.

The policy needs each candidate's grounded savings estimate. It gets it by calling the
**deterministic tool layer**, not the agent. Three consequences:

1. **No inference is needed to decide eligibility**, so the gate runs over 12,000 users
   in seconds and is exactly reproducible.
2. **The number that decides eligibility is the same number the user is later shown.**
   The decision and the explanation cannot disagree.
3. It works with no model weights present at all.

---

## 2.3 The decision pipeline, end to end

This is the spine of the system. If you can narrate this diagram, you can explain the
project.

```mermaid
sequenceDiagram
  autonumber
  participant P as Targeting policy
  participant M as Model registry
  participant T as Tool layer
  participant X as Experiment assigner
  participant A as Concierge agent
  participant R as LLM runtime
  participant G as Guardrails
  participant E as Event store
  participant U as User

  Note over P,E: BATCH — nightly
  P->>M: load propensity + uplift models
  P->>P: score live cohort → tau-hat per user
  P->>P: exclude non-positive uplift
  P->>T: estimate_savings(candidate) — deterministic
  T-->>P: saving_90d, cost_90d
  P->>P: value-fit gate → suppress if saving < cost
  P->>P: rank by uplift, apply contact budget
  P->>P: fairness check across income bands
  P->>E: write decision log (selected AND suppressed, with reasons)

  Note over X,U: ONLINE — on app open
  U->>X: opens app
  X->>X: sha256(experiment:user) → variant
  X->>E: record assignment + impression

  alt variant = agent_concierge
    X->>A: generate(user_id)
    A->>A: scope check — decline out-of-scope before any inference
    A->>T: tools, bound to this user_id
    T-->>A: account facts + value ledger
    loop bounded tool rounds
      A->>R: prompt + tool schemas
      R->>R: grammar-constrained decode
      R-->>A: validated tool call
    end
    A->>A: required evidence gathered? if not, fetch it
    A->>R: final prose generation
    R-->>A: draft message
    A->>G: check numbers / advice / features / pressure / coherence
    alt all checks pass
      G-->>U: grounded explanation
    else any check blocks
      G->>G: degrade to deterministic writer
      G-->>U: templated, grounded explanation
      G->>E: log the block and its reason
    end
  else variant = generic_upsell
    X-->>U: existing static copy
  else variant = holdout
    X-->>U: nothing
  end

  U->>E: click / convert / retain_30d
  E->>E: sequential test updates both arms + guardrail
```

### Five things to notice in that trace

1. **The gate runs before the budget** (steps 6–8). If the budget ran first, a user
   could be excluded for ranking poorly and the gate would never evaluate them — the
   log would say `budget` where the truth is `value_fit`.
2. **Suppressed users are logged too.** "Why was I not contacted?" has a factual answer.
3. **Scope is checked before any inference.** A refusal that depends on the model
   cooperating is not a control.
4. **A guardrail block is not an error.** The user still receives a correct, grounded
   message; we get a logged reason.
5. **Three arms, not two.** The holdout separates "the agent helped" from "any nudge
   helped".

---

## 2.4 Trust boundary

```mermaid
graph LR
  subgraph tb["Trust boundary — our infrastructure"]
    direction TB
    pii[("User financial data<br/>balances · fees · advances")]
    inf["LLM inference<br/><i>in-process, local weights</i>"]
    grd["Guardrails"]
    pii --> inf --> grd
  end

  out(["Generated text<br/><i>every number verified<br/>against the value ledger</i>"])
  grd --> out

  cloud[("Third-party inference API")]
  inf -.->|"DISABLED by default.<br/>Opt-in, config-gated,<br/>logs the egress"| cloud

  classDef danger fill:#ffebe9,stroke:#cf222e,stroke-dasharray:4 3
  class cloud danger
```

Two properties hold in the default configuration, and both are testable:

| property | how it is enforced |
|---|---|
| **No egress** — no user attribute reaches a third-party inference provider | default provider is in-process; a test asserts the agent imports no concrete provider |
| **No unverified number** — nothing leaves unless every numeric token is accounted for | value-ledger set membership, checked before output |

---

## 2.5 How the layers depend on each other

```mermaid
graph LR
  D["<b>A · Data</b><br/>001 synthetic population"]
  M["<b>B · Decision</b><br/>002 models<br/>003 policy + offline eval"]
  AG["<b>C · Agent</b><br/>004 LLM runtime<br/>005 agent + guardrails<br/>006 eval gate"]
  P["<b>D · Product</b><br/>007 API + experiments<br/>008 console"]
  T["<b>E · Trust</b><br/>009 observability<br/>+ governance"]

  D --> M --> P
  D --> AG --> P
  AG -->|"value-fit gate"| M
  M --> T
  AG --> T
  P --> T

  classDef a fill:#eef2f7,stroke:#8899aa,color:#1b2733
  classDef b fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef c fill:#8250df,stroke:#4c2889,color:#fff
  classDef d fill:#1a7f37,stroke:#0f5323,color:#fff
  classDef e fill:#9a6700,stroke:#6b4700,color:#fff
  class D a
  class M b
  class AG c
  class P d
  class T e
```

The edge that runs *backwards* — `Agent → Decision` — is the value-fit gate. Every
other dependency flows the way you would expect.

---

## 2.6 Quality gates in CI

```mermaid
graph LR
  c["commit"] --> t["pytest · 207 tests"]
  t --> g["agent grounding gate<br/><b>zero violations</b>"]
  g --> m["model metrics vs<br/>recorded baseline"]
  m --> f["fairness slice report"]
  f --> d["docs updated<br/>in the same change"]
  d --> ok(["mergeable"])

  g -.->|"any violation"| blk(["BLOCKED"])

  classDef blocked fill:#ffebe9,stroke:#cf222e,color:#82071e
  class blk blocked
```

The grounding gate is **absolute** — one violation fails the build, it is not a
regression to triage later. That is only affordable because local inference costs
nothing per run, so the gate covers *every* case on *every* commit rather than a
sample. A sampled safety gate is not a gate.

---

## 2.7 Where the code lives

| Layer | Package | Entry point |
|---|---|---|
| Data | `f2g/data/` | `python -m f2g.data.generate` |
| Models | `f2g/ml/` | `python -m f2g.ml.train` |
| Policy | `f2g/ml/policy.py`, `ope.py` | `python -m f2g.ml.run_policy` |
| LLM runtime | `f2g/llm/` | library |
| Agent | `f2g/agent/` | library |
| Agent evaluation | `f2g/evals/` | `python -m f2g.evals.run` |
| API + experiment | `f2g/api/`, `f2g/experiment/` | `uvicorn f2g.api.main:app` |
| Console | `web/src/` | `npm run dev` |
| Governance | `f2g/governance/` | `python -m f2g.governance.model_card` |

---

## 2.8 Check your understanding

1. Trace what happens between a user opening the app and seeing a nudge. Which steps
   involve a language model, and which do not?
2. Why does the value-fit gate call the tool layer instead of the agent?
3. The policy applies four constraints. Name them in order and explain why value fit
   comes before budget.
4. What breaks if variant assignment is not a pure function of `(user_id, experiment_id)`?
5. Why can the grounding gate be absolute here when most teams would have to sample?

---

Next: [Part 3 — Decision layer](03-decision-layer.md)
