# Experiment Design — Free2Genius concierge

> Synthetic project. The numbers below are computed from the simulated population and are
> reproducible; they are not a real experiment.

## The question

Does an **uplift-targeted, evidence-grounded agent message** convert more free users to Genius
than the existing generic upsell — *without* degrading 30-day retention?

Two clauses, deliberately. The first alone is satisfied by persuading anyone; the second is
what stops us satisfying it that way.

## Design

| | |
|---|---|
| Unit of randomisation | User |
| Assignment | `sha256(experiment_id:user_id) → bucket`, deterministic and stable |
| Eligibility | Free users selected by the targeting policy (positive uplift, passes the value-fit gate) |
| Primary metric | Conversion to Genius within the experiment window |
| Guardrail metric | 30-day retention among converters, non-inferiority margin **3 pp absolute** |
| Secondary | Click-through on the nudge; grounding block rate; message latency |
| Planned horizon | 28 days |

### Arms

| Arm | Share | What the user gets |
|---|---|---|
| `agent_concierge` | 40% | Grounded, per-user explanation written by the agent |
| `generic_upsell` | 40% | The existing static upsell copy |
| `holdout` | 20% | Eligible, deliberately not contacted |

**Why three arms.** Two arms would confound "the agent helped" with "any nudge helped". The
holdout is what lets us decompose the effect: `agent − holdout` is the total programme effect,
and `agent − generic` is the incremental value of the agent specifically. The second is what
justifies the engineering; the first is what justifies the programme.

The holdout is also the ethical control: if the nudge harms retention, the holdout shows what
would have happened without it.

## Sample size

Computed by `POST /experiment/power`, and reproducible:

```bash
curl -s localhost:8000/experiment/power \
  -H 'content-type: application/json' \
  -d '{"baseline_rate": 0.15, "mde_relative": 0.10}'
```

| | |
|---|---|
| Baseline conversion (generic arm) | 15% |
| Minimum detectable effect | +10% relative (15% → 16.5%) |
| α | 0.05 two-sided · **power** 0.80 |
| **n per arm, fixed horizon** | **9,257** |
| **n per arm, sequential** | **11,109** |

The sequential premium is roughly 20% more sample for the same power. That is the price of
being allowed to look at the dashboard whenever you like, and it is stated up front rather
than discovered mid-test.

At 40/40/20 shares, 11,109 per active arm means about **27,800 eligible users**. With the
policy contacting 20% of the live cohort, that sets the enrolment period.

## Analysis

### Always-valid inference

The dashboard reports the fixed-horizon interval *and* an always-valid confidence sequence,
and the decision rules use the latter.

The reason is empirical, not theoretical. Simulated in `tests/test_experiment.py`: under **no
true effect**, with someone checking the dashboard 200 times,

| method | false-positive rate (nominal 5%) |
|---|---|
| naive fixed-horizon test, re-read each time | **49%** |
| always-valid confidence sequence | **3%** |

Telling people not to look is a process control, and process controls fail. Making the
statistics valid under the behaviour that will actually occur is the more robust fix.

### Stopping rules, declared before launch

Evaluated in this order on every read:

1. **Stop for harm** — the sequential *upper* bound on the retention difference falls below
   −3 pp. Checked **first**, so a conversion win can never mask a retention breach for as long
   as the win holds.
2. **Ship** — the sequential lower bound on conversion lift exceeds 0 **and** the retention
   lower bound clears the non-inferiority margin. Both, not either.
3. **Stop for futility** — at the planned horizon, the conversion sequence still contains zero.
4. Otherwise **continue**.

### What we would *not* do

- Not stop on the primary metric alone.
- Not add arms mid-flight. A configuration change requires a new experiment id, which
  re-partitions the population.
- Not subgroup-hunt after the fact. Pre-registered slices only: income band, and
  fee-burden quartile.

## Rollout plan

| Phase | Traffic | Gate to proceed |
|---|---|---|
| 0 · Shadow | 0% | Agent generates for a sample; messages reviewed by a human, not sent. Grounding violations must be zero over ≥500 generations. |
| 1 · Canary | 5% of eligible | 48 hours. Watch guardrail block rate, degradation rate and latency, not conversion — the sample cannot say anything about conversion yet. |
| 2 · Ramp | 25% | Sequential bounds tracking; no harm signal. |
| 3 · Full | 40/40/20 | Run to horizon or a stopping rule. |
| 4 · Decision | — | Ship, iterate, or stop. A "continue" verdict at the horizon is futility, not an invitation to keep going. |

**Automatic rollback** on any of: a grounding violation reaching a user; guardrail block rate
above 15% sustained over an hour; the retention harm rule firing; p99 generation latency
beyond the budget.

## What would make this experiment invalid

Stated plainly, because these are the ways an experiment like this usually goes wrong:

- **Assignment drift.** Any change to arm shares or the experiment id mid-flight re-partitions
  users. Pinned by `tests/test_experiment.py::test_assignment_is_stable`.
- **Events from unassigned users.** Accepting them would bias whichever arm they were guessed
  into; the API rejects them with a 409.
- **Double-counted conversions.** At-least-once delivery is normal, so events are idempotent on
  a caller-supplied key.
- **Retention measured at request time rather than event time.** Clock skew would silently
  shift the guardrail window.
- **Targeting policy changed mid-experiment.** The eligible population would no longer be the
  one that was randomised. A policy change requires a new experiment.

## Honest reading of the current simulated run

At the seeded sample (18,030 / 18,003 / 8,967):

| | |
|---|---|
| Conversion, agent arm | 16.27% |
| Conversion, generic arm | 15.72% |
| Lift | **+0.55 pp (+3.5% relative)**, fixed-horizon p = 0.15 |
| Sequential CI on lift | [−0.71 pp, +1.81 pp] — **contains zero** |
| Retention, agent arm | 70.5% |
| Retention, generic arm | 64.2% |
| Retention difference | **+6.31 pp**, sequential CI [+2.55, +10.08] — **entirely above zero** |
| **Verdict** | **continue** |

The conversion effect has not separated, and the system says so rather than reaching for the
fixed-horizon p-value or slicing until something clears 0.05. The guardrail *has* separated,
in the agent arm's favour — which is what the value-fit gate predicts, since that arm contacts
only users the gate judged would genuinely benefit.

The correct read is: "the retention story is real at this sample size, the conversion story is
not yet, keep running." That is the answer the design was built to be able to give.
