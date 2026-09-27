# HLD 005 — Genius Concierge Agent & Safety Guardrails

**Domain**: C · **Spec**: [005](../../../specs/005-concierge-agent-guardrails/spec.md) · **Status**: Implemented

## Responsibility

Produce a specific, true, per-user explanation of whether a paid subscription would save this
person money — built on the assumption that **the model will sometimes be confidently wrong**,
and designed so that being wrong cannot reach a user.

## Component decomposition

```mermaid
graph TB
  input(["user_id · optional question"])
  scope["<b>scope policy</b><br/><i>decided before any inference</i>"]
  tools["<b>ConciergeTools</b><br/><i>bound to one user_id</i><br/>6 tools · value ledger"]

  subgraph loop["bounded tool loop"]
    d["runtime.decide_or_degrade"]
    rep{"repeat?"}
    ev{"required evidence<br/>gathered?"}
    d --> rep --> ev
  end

  force["<b>forced evidence</b><br/><i>agent fetches what the<br/>model declined to</i>"]
  prose["runtime.complete_or_degrade"]

  subgraph gates["output gates — each reported separately"]
    g1["numeric grounding"]
    g2["prohibited advice"]
    g3["feature names"]
    g4["no pressure"]
    g5["coherence"]
    g6["disclosure"]
  end

  det["deterministic writer<br/><i>grounded by construction</i>"]
  out(["AgentResult<br/><i>message · evidence · verdicts · telemetry</i>"])

  input --> scope
  scope -->|out of scope| refuse(["decline<br/><i>no tools, no model</i>"])
  scope -->|in scope| loop
  loop --> tools
  ev -->|missing| force --> prose
  ev -->|complete| prose
  prose --> gates
  gates -->|all pass| out
  gates -->|any block| det --> gates

  classDef core fill:#1f6feb,stroke:#0b3d91,color:#fff
  classDef gate fill:#8250df,stroke:#4c2889,color:#fff
  classDef safe fill:#1a7f37,stroke:#0f5323,color:#fff
  class d,tools,force core
  class g1,g2,g3,g4,g5,g6 gate
  class det,refuse safe
```

## The three defences, and why each exists

```mermaid
graph LR
  subgraph structural["Structural — the model cannot express the failure"]
    s1["user_id bound at construction,<br/>absent from every tool schema"]
    s2["catalog enum in the decode grammar"]
  end
  subgraph procedural["Procedural — the agent acts, not the model"]
    p1["scope decided before inference"]
    p2["required evidence fetched if skipped"]
    p3["arithmetic only in estimate_savings"]
  end
  subgraph detective["Detective — checked before a human sees it"]
    d1["value ledger membership"]
    d2["advice · features · pressure · coherence"]
  end
  structural --> procedural --> detective

  classDef best fill:#1a7f37,stroke:#0f5323,color:#fff
  class s1,s2 best
```

Structural beats procedural beats detective, so the design reaches for the leftmost available
option each time. Prompt instructions appear nowhere on this diagram: they reduce how often
gates fire, they are not controls.

## Interface contracts

| Contract | Guarantee |
|---|---|
| `ConciergeAgent(user_id, provider=None)` | Raises on an unknown user; identity fixed for the session |
| `.generate_nudge() → AgentResult` | Message plus tool calls, evidence, per-check verdicts, telemetry |
| `.chat(text) → AgentResult` | Same, and out-of-scope questions decline without touching account data |
| `AgentResult.evidence[i].tools` | Provenance for every figure — the console's chip contract |
| `AgentResult.guardrails["checks"]` | One boolean per check, never one aggregate |
| `AgentResult.degraded` / `forced_evidence` | Degradation and under-investigation are visible, not silent |

## Failure modes

| Failure | Control | Result |
|---|---|---|
| Invented figure | Value-ledger membership | Blocked; degrade to the template |
| Invented feature | Grammar enum + name check | Unrepresentable; blocked if paraphrased |
| Model does arithmetic | Grounding blocks derived numbers | Deliberate false positive; `estimate_savings` is the answer |
| Out-of-scope advice | Scope policy, pre-inference | Declined in one sentence |
| Injection | Identity bound structurally | Nothing to redirect; attempt logged |
| Answering without looking | Required-evidence precondition | Agent fetches it and records `forced_evidence` |
| Repetition loop | Coherence check | Blocked; degrade |
| Model calls one tool forever | Round cap + repeat detection | Forced to answer |
| All drafts blocked | Deterministic writer, then a safe refusal | Never an unchecked message |

## The degradation path is the design

```mermaid
sequenceDiagram
  participant M as Model
  participant G as Guardrails
  participant D as Deterministic writer
  participant U as User

  M->>G: draft containing "$100"
  G->>G: $100 ∉ value ledger
  G-->>M: BLOCKED
  G->>D: compose from the same tool results
  D->>D: finish any investigation the model skipped
  D->>G: templated draft
  G->>G: every figure is in the ledger
  G->>U: correct, grounded message
  Note over U: the user never sees the rejected text,<br/>and never sees nothing
```

A blocked message is not an error state. The user gets a correct explanation and we get a logged
reason — which is precisely what makes a strict, absolute grounding gate affordable.

## Key decisions

1. **Identity is structural.** The single most important line in the feature is that `user_id`
   is a constructor argument, not a tool parameter.
2. **Refusal does not depend on the model.** Scope is decided in the agent, so every provider
   declines identically, for free.
3. **Evidence gathering is a protocol precondition.** Both model tiers answered from
   `get_account_summary` alone and reached confident wrong conclusions. The prompt asks; the
   loop enforces.
4. **Every check reports independently.** A composite pass/fail tells an operator something
   broke without saying what, and the per-check block rate is what detects prompt drift.
