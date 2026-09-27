# Demo script — ten minutes

> Open with the honesty, don't bury it: **"Everything you're about to see runs on synthetic
> data I generated, and on an open-weights model running on this laptop. No API key, no
> network."** That framing buys credibility for everything that follows.

## Before you start

```bash
make all      # ~3 minutes: data, models, policy, safety gate, demo experiment
make api      # terminal 1
make web      # terminal 2 → http://127.0.0.1:5173
```

---

## 1 · The problem, in one table (90 seconds)

Open `artifacts/reports/model_evaluation.md`, scroll to **"Where propensity ranking spends its
budget"**.

> "Both rankings get a 10% contact budget. The uplift model spends 77% of it on users the nudge
> actually moves. The propensity model spends **97%** of it on users who were converting
> anyway — and then books their conversions as programme impact."

Then the budget sweep just above it.

> "The advantage isn't a constant. It's +115% at a 5% budget and **negative** at 50%. That's
> why the operating budget in this system is 20% — the number came out of this table, not out
> of a planning meeting."

**If they ask why not just use propensity:** the bottom-decile row. −2.39 pp realised uplift.
Those users are *less* likely to convert after being contacted. A propensity model has no way
to say "don't".

---

## 2 · The targeting decision (2 minutes)

Console → **Targeting**.

Point at the binding constraint tile: **value fit**, not budget.

> "The budget allows 2,400 contacts. We're sending 1,801 — not because we ran out of users, but
> because 7,530 candidates failed an honesty check."

Sort by **propensity**, descending. Point at rows marked *Suppressed · value fit*.

> "These are the users a conversion model ranks highest. We're not contacting them. Before
> anyone is contacted, the system computes from their own 90 days of fees what Genius would
> actually save them. If it doesn't clear the $44.97 it costs over the same period, they're
> suppressed regardless of how movable the model thinks they are."

The two numbers to land:

> "Mean estimated saving of the people we do contact: **$70.21**. With the gate switched off:
> **$34.75**. The gate costs us 95 expected conversions, and we report that cost — it's a real
> trade, not a free win."

**The sentence to say out loud:** *"This system structurally cannot hit its conversion target by
mis-selling, because the honesty check is inside the targeting decision rather than beside it."*

---

## 3 · The agent (3 minutes — the centrepiece)

Click any contacted user. Console → **Concierge**.

Let them read the message. Then click a dollar figure.

> "Every number is a chip. Click one and you get the tool call that produced it and the raw
> result. Grounding you can inspect, not grounding I'm asserting."

Point at the six green badges.

> "Six independent checks, reported separately — not one aggregate. If one fails you know which
> property broke."

Now switch the provider dropdown to **Local model** and regenerate. It takes 30–60 seconds; use
the time:

> "This is a 1.5-billion-parameter open-weights model running in this process. No API. The
> reason that's viable is the next thing you'll see."

**When it finishes**, one of two things happens, and *both* are the demo:

- **It degrades.** The banner names the reason — a figure the model invented that isn't in this
  user's data. > "In development this model fabricated seven dollar figures in a single message.
  All seven were blocked. The user got a correct templated message instead. That's the system
  working — the guardrail isn't a filter on a good model, it's what makes a weak model safe."
- **It passes.** > "Clean this time. The point is that it doesn't have to be — every number was
  still checked against the ledger before you saw it."

### The question that lands hardest

In the chat box, click **"Should I invest my savings instead?"**

> "Declined in one sentence. And notice what didn't happen: no tool calls, no account data read,
> no model inference at all. Scope is decided before the model runs. A refusal that depends on
> the model cooperating isn't a control — the evaluation gate caught exactly that and failed the
> build until it was fixed."

---

## 4 · The experiment (2 minutes)

Console → **Experiment**.

> "Verdict: **continue**. Conversion is +0.55 points, and the interval still contains zero. The
> system will not call it."

Then the retention chart:

> "But the guardrail *has* separated. The agent arm retains 6.3 points better, and that interval
> is entirely above zero. That's the value-fit gate showing up in the data — that arm only
> contacts people the gate judged would genuinely benefit, and they stay."

Scroll to the interval comparison:

> "Two intervals on the same estimate. The wider one is always-valid. Under no true effect, with
> someone checking this page 200 times, the naive test declares a winner **49%** of the time at a
> nominal 5%. The sequential bound holds at 3%. Telling a growth team not to peek is a process
> control, and process controls fail."

---

## 5 · Close (90 seconds)

Two files.

`docs/governance/RISK_REGISTER.md`:

> "Thirteen risks. Every one names either a control with a test that runs in CI, or an explicit
> acceptance. 'We're careful about this' isn't in here."

`specs/002-propensity-uplift-models/spec.md`, the SC-004 note:

> "The specs got corrected by their own implementation, and I left the corrections in. The first
> uplift model I built ranked *worse* than the propensity baseline it was supposed to beat —
> classic T-learner variance, predicting effects three times wider than the ones that exist. The
> ADR had pre-declared the trigger for moving to an X-learner, so the decision was made on
> measurement. The broken version still runs as an ablation on every training run, so the claim
> can't quietly stop being true."

**The close:**

> "The interesting engineering here isn't the model. It's that every claim the system makes
> about someone's money is mechanically checked before they see it, and that the growth metric
> is constrained by whether the product actually helps them."

---

## Questions you should expect

**"Why not use GPT-4 / Claude for the agent?"**
Two reasons, and the second matters more. The data is financial PII, and local inference means
it never leaves the boundary. But the real reason is cost per evaluation: local inference is
free, so the grounding gate runs over the entire case set on every commit. With a metered API
I'd have to sample, and a sampled safety gate isn't a gate. The provider abstraction is one
interface — swapping to a frontier model is a config change and no agent code moves.

**"Isn't the value-fit gate just leaving money on the table?"**
Yes, 95 expected conversions in this cycle, and it's reported. The counter is in the retention
chart: the arm that only contacts people who benefit retains 6.3 points better. A conversion
you have to refund or that churns in 30 days isn't revenue.

**"How do you know the uplift model works?"** The data is synthetic, so I know each user's true
treatment effect. Spearman 0.633 against ground truth, and the doubly-robust policy-value
interval covers the true value for all five candidate policies. That's a check on the
*estimator*, and no real dataset can give it to you — which is the actual argument for building
the simulator first.

**"What breaks first at scale?"** SQLite and single-process serving. Both are behind interfaces.
The thing that *wouldn't* break is the guardrail — it's a set membership test per number, no
extra inference, which is why it can run on every request rather than on a sample.

**"What would you do next?"** Three things, in order: a human review loop on generated messages
before any real rollout; per-user message caching keyed on fee-history changes rather than a
flat TTL; and replacing the pattern-based scope check with a small trained classifier, since
patterns will miss creative phrasings and the output-side check is currently the only backstop.
