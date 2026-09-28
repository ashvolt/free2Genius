# Part 7 — Demo and Q&A

**Written for: you, preparing to present this.** Previous: [build journey](06-build-journey.md) · [back to index](README.md)

---

## 7.1 Pre-flight

```bash
python run.py all       # ~4 min — do this BEFORE the call, not during
python run.py api       # terminal 1
python run.py web       # terminal 2 → http://localhost:5173
```

Have open:
- the console at `localhost:5173`
- `artifacts/reports/model_evaluation.md`
- `docs/governance/RISK_REGISTER.md`

**Open with the honesty.** It buys credibility for everything after:

> Everything you are about to see runs on synthetic data I generated, and on an
> open-weights model running on this laptop. No API key, no network.

---

## 7.2 The ten-minute demo

### Beat 1 — the problem, in one table (90 s)

`artifacts/reports/model_evaluation.md` → *"Where propensity ranking spends its budget"*.

> Both rankings get a 10% contact budget. The uplift model spends 77% of it on users the
> nudge actually moves. The propensity model spends **96.7%** of it on users who were
> converting anyway — and then books their conversions as programme impact.

Then the budget sweep just above it.

> And the advantage is not a constant. It is +4.6 points per contact at a 5% budget and
> **negative** at 50%. That is why the operating budget is 20% — the number came out of
> this table, not a planning meeting.

**If they ask why not just use propensity:** the bottom-decile row. **−2.39 pp** realised
uplift. Those users are *less* likely to convert after being contacted. A propensity model
has no way to say "do not".

---

### Beat 2 — the targeting decision (2 min)

Console → **Targeting**. Point at the binding-constraint tile: **value fit**, not budget.

> The budget allows 2,400 contacts. We are sending 1,801 — not because we ran out of
> budget, but because 7,530 candidates failed an honesty check.

Sort by **propensity** descending. Point at rows marked *Suppressed · value fit*.

> These are the users a conversion model ranks highest. We are not contacting them.
> Before anyone is contacted, the system computes from their own 90 days of fees what
> Genius would actually save them. If it does not clear the $44.97 it costs over the same
> period, they are suppressed — regardless of how movable the model thinks they are.

The two numbers to land:

> Mean estimated saving of the people we *do* contact: **$70.21**. With the gate switched
> off: **$34.75**. The gate costs us 95 expected conversions, and we report that cost.
> It is a real trade, not a free win.

**The sentence to say out loud:**

> This system structurally cannot hit its conversion target by mis-selling, because the
> honesty check sits inside the targeting decision rather than beside it.

---

### Beat 3 — the agent (3 min, the centrepiece)

Click a contacted user → **Concierge**. Let them read the message. Then **click a dollar
figure**.

> Every number is a chip. Click one and you get the tool call that produced it and the raw
> result. Grounding you can inspect, not grounding I am asserting.

Point at the six green badges.

> Six independent checks, reported separately — not one aggregate. If one fails you know
> which property broke.

**Now the killer comparison.** Go back to Targeting, pick `l0010925` — second-highest
uplift of 12,000 — and show its nudge:

> Over the same 90 days Genius costs $44.97, which is more than the $33.78 it would have
> saved you. On your recent activity it would not pay for itself, so it is probably not
> worth it right now.

> An upsell agent that recommends against buying. That is the whole project in one screen.

**If you have model weights installed**, switch the provider to *Local model* and
regenerate. 60–110 s; use the time to explain local-first. Then whichever happens:

- **It degrades** → *"In development this model fabricated seven dollar figures in a
  single message. All seven were blocked. The guardrail is not a filter on a good model —
  it is what makes a weak model safe to deploy."*
- **It passes** → *"Clean this time. The point is it does not have to be. Every number was
  still checked against the ledger before you saw it."*

---

### Beat 4 — the question that lands hardest (30 s)

In the chat box: **"Should I invest my savings instead?"**

> Declined in one sentence. Notice what did *not* happen: no tool calls, no account data
> read, no model inference at all. Scope is decided before the model runs. The evaluation
> gate caught exactly this — it failed the build at a 0.00 refusal rate until it was fixed.

---

### Beat 5 — the experiment (2 min)

Console → **Experiment**.

> Verdict: **continue**. Conversion is +0.55 points and the interval still contains zero.
> The system will not call it.

Then the retention chart:

> But the guardrail *has* separated. The agent arm retains **6.3 points better**, and that
> interval is entirely above zero. That is the value-fit gate showing up in the data —
> that arm only contacts people the gate judged would genuinely benefit, and they stay.

Scroll to the interval comparison:

> Two intervals on the same estimate. The wider one is always-valid. Under no true effect,
> with someone checking this page 200 times, the naive test declares a winner **45%** of
> the time at a nominal 5%. The sequential bound holds at **2%**. Telling a growth team
> not to peek is a process control, and process controls fail.

---

### Beat 6 — close (90 s)

`docs/governance/RISK_REGISTER.md`:

> Fourteen risks. Every one names either a control with a test that runs in CI, or an
> explicit acceptance. "We are careful about this" is not in here.

`specs/002-propensity-uplift-models/spec.md`, the SC-004 note:

> The specs got corrected by their own implementation, and I left the corrections in. My
> first uplift model ranked *worse* than the propensity baseline it was supposed to beat —
> classic T-learner variance, predicting effects three times wider than the ones that
> exist. The ADR had pre-declared the trigger for moving to an X-learner, so the decision
> was made on measurement. The broken version still runs as an ablation on every training
> run, so the claim cannot quietly stop being true.

**The close:**

> The interesting engineering here is not the model. It is that every claim the system
> makes about someone's money is mechanically checked before they see it, and that the
> growth metric is constrained by whether the product actually helps them.

---

## 7.3 Questions you will be asked

### On the ML

**"Your propensity AUC is 0.86. Why isn't that enough?"**
> AUC measures the wrong thing for this decision. It is high *because* it ranks
> sure-things first, and those are exactly the users where contact adds nothing. At a 10%
> budget, propensity ranking puts 96.7% of its spend into users who were already
> converting. It is not wrong about who converts; it is answering a question nobody should
> have asked.

**"Why can't you use AUC for the uplift model?"**
> τ is never observed for an individual — you see one arm per user, so there is no label
> to compute AUC against. Ranking quality is Qini and realised uplift by decile, which
> compare treated and control outcomes *within* score strata. Reporting AUC against
> `converted` would be a reassuring number about the wrong quantity.

**"How do you know the uplift model works?"**
> The data is synthetic, so I know every user's true τ. Spearman 0.633 against ground
> truth, and the doubly-robust policy-value interval covers the true value for all five
> candidate policies. That last one validates the *estimator*, not just the policy, and no
> real dataset can give you it — which is the actual argument for building the simulator
> first.

**"Walk me through a modelling mistake you made."**
> My first uplift estimator ranked worse than the propensity baseline. Qini 0.5596 against
> 0.6725, and a *positive* bottom decile when it must be negative. The cause was
> T-learner variance: outcome-tuned hyperparameters fit a 15% conversion rate, but a
> treatment effect here is 1 to 8 points, and a T-learner subtracts two such fits so their
> errors compound. It predicted τ spanning [−0.35, +0.38] against a true range of
> [−0.04, +0.13]. Regularising the arm models took it to 0.7533; the X-learner, which
> regresses imputed effects and can be regularised toward zero, reached 0.7822. The broken
> variant still runs as an ablation on every training pass so the claim stays checked.

**"Why X-learner over T-learner or causal forest?"**
> Measured, not assumed — all three meta-learners are trained and the production one is
> selected by Qini at training time. Causal forest would be the next step if the X-learner
> plateaued; it has not, so adopting it would be speculative machinery. The honest caveat
> is that the X-learner needs the treatment propensity, and ours is a known constant only
> because the pilot was randomised.

---

### On the agent

**"Why not use a frontier model?"**
> Two reasons, and the second matters more. The data is financial PII, and local inference
> means it never leaves the trust boundary. But the real reason is cost per evaluation:
> local inference is free, so the grounding gate runs over the entire golden case set on
> every commit. With a metered API I would have to sample, and a sampled safety gate is
> not a gate. The provider abstraction is one interface — swapping to a frontier model is
> a config change and no agent code moves.

**"How do you stop it hallucinating a fee?"**
> Not with a prompt. Every numeric value any tool returns is recorded in a per-session
> ledger, and every number in the draft must be a member of that set or the message is
> blocked and the turn degrades to a templated writer. It is set membership, so it costs
> nothing and runs on every request rather than a sample. In testing the 1.5B model
> fabricated seven dollar figures in one message; none of them could reach a user.

**"What about prompt injection?"**
> Structural, not detective. `user_id` is bound at session construction and appears in no
> tool schema, so the model has no way to *express* a request for another user's data
> however it is asked. Injection attempts are additionally logged for review, but the
> logging is not the defence.

**"Isn't blocking a correctly-derived number a bug?"**
> It is a deliberate false positive, and it is why `estimate_savings` exists. I cannot
> distinguish correct arithmetic from confident fabrication by looking at the output, so
> derivation belongs in Python. The guardrail's strictness is what forced the better tool
> design — softening it would undo that. I also fixed the most common cause rather than
> the check: the prompt now forbids rounding, because `$45` for `$44.97` is
> indistinguishable from an invented figure.

**"What is the hardest failure mode you found?"**
> The 3B model answered from the account summary alone and wrote "there are no significant
> fees" for a user carrying $136.93 in fees. Every number it printed was real, so no
> grounding check catches it. It is a tool-*selection* failure, and a grammar cannot
> prevent it — a grammar guarantees the call is well-formed, not that the model chose to
> look. The fix was to make required evidence a protocol precondition the loop enforces
> rather than something the prompt asks for.

**"How do you know the agent is good?"**
> Thirty golden cases across eight categories, selected by criteria rather than hardcoded
> ids so the set cannot silently stop covering what it claims to. Programmatic checks are
> absolute and gate the build; LLM-judge scores are tracked against a baseline and never
> gate, because a model's opinion is not a release gate. When the judge disagrees with the
> ledger I report it as a judge-calibration finding — the mechanical check wins.

---

### On the product and experiment

**"Isn't the value-fit gate leaving money on the table?"**
> Yes — 95.3 expected conversions this cycle, and I report it. The counter is in the
> retention chart: the arm that only contacts people who benefit retains 6.3 points
> better. A conversion you refund, or that churns in thirty days, is not revenue. And the
> gate is what makes the system defensible: it structurally cannot hit its target by
> mis-selling.

**"Why three arms?"**
> Two would confound "the agent helped" with "any nudge helped". Agent minus holdout is
> the total programme effect, which justifies the programme; agent minus generic is the
> incremental value of the agent, which justifies the engineering. The holdout is also the
> ethical control — if the nudge harms retention, it shows what would have happened
> without it.

**"Your p-value is 0.152. Isn't the experiment a failure?"**
> It is unresolved, and the system says so rather than reaching for a slice that clears
> 0.05. What *has* separated is the guardrail — retention is +6.3 points with its
> sequential interval entirely above zero. The correct read is: the retention story is
> real at this sample size, the conversion story is not yet, keep running. A system that
> refuses to call an unresolved result is the behaviour I want to demonstrate.

**"Why sequential testing? Isn't that over-engineering?"**
> It is the difference between a valid result and an invalid one under the behaviour that
> will actually occur. Simulated on this repo: under no true effect, with the dashboard
> read 200 times, the naive fixed-horizon test declares a winner 45% of the time at a
> nominal 5%. The sequential bound holds at 2%. It costs about 20% more sample for the
> same power, and that is stated up front. There is also an ethical argument specific to
> this test — one arm may be harming users, and being contractually unable to stop early
> is not a neutral property.

---

### On the engineering

**"What breaks first at scale?"**
> SQLite and single-process serving. Both sit behind interfaces so the swap is bounded.
> Also the single `llama.cpp` context is serialised behind a lock, which is a real
> throughput ceiling. What would *not* break is the guardrail — it is a set membership
> test per number with no extra inference, which is why it can run on every request rather
> than a sample.

**"How do you know the system still works after a change?"**
> 207 tests, plus three gates that can fail a build: zero grounding violations on the
> golden set, model metrics against a recorded baseline, and a fairness slice report. The
> model card is *generated* from evaluation output and a test asserts the committed copy
> matches, so a stale card is a failing build rather than something found in review.

**"Tell me about a bug that embarrassed you."**
> Two, both only visible on a different machine. The entire `f2g/data` package was missing
> from the repository — `.gitignore` had a bare `data/`, which gitignore matches at any
> depth, so it swallowed `f2g/data/` along with the generated directory it was meant for.
> `git status` stayed clean because ignored files are not reported. And `Path.write_text`
> uses the locale encoding, which on Windows is cp1252 and cannot encode the arrows in the
> generated reports — the pipeline died after training had already completed. Neither a
> test suite nor a code review would have found either one. Only running it somewhere else
> did.

---

### On judgment

**"What would you do next?"**
> Three things in order. A human review loop on generated messages before any real
> rollout — the model card names its absence as a limitation. Per-user message caching
> keyed on fee-history changes rather than a flat TTL. And replacing the pattern-based
> scope check with a small trained classifier, because patterns will miss creative
> phrasings and the output-side check is currently the only backstop.

**"What is not finished?"**
> One success criterion is unmet: median generation latency is 62 to 110 seconds against a
> 20-second target. It is not user-visible because nudges are async and cached, but
> caching is a mitigation, not a fix. The levers are a smaller round budget now that
> evidence gathering is enforced, or moving the fast tier to a GPU through the existing
> OpenAI-compatible provider. There is also no retention or deletion policy on stored
> records, which a real deployment needs.

**"What would you remove if you had to ship in a week?"**
> The S-learner and the T-learner from production — keep them as the comparison that
> justifies the X-learner, but only one estimator needs to serve. The chat surface, keeping
> the nudge. And the parity-cap mode, which is currently unused. I would not remove the
> grounding gate, the value-fit gate, or the holdout arm; those are the parts that make it
> defensible rather than merely functional.

---

## 7.4 Questions to ask them

Asking good questions is half the interview.

- How do you currently decide who sees an upsell, and do you hold out a control group?
- Do you have a randomised historical cohort? Without one, uplift modelling needs an
  assumption I would rather not make.
- What is your counter-metric for conversion today, and who owns it?
- Where does the line sit between a growth experiment and a decision that needs
  compliance review?
- How are generated customer-facing messages reviewed before they go out?

---

## 7.5 Self-test drills

Do these without looking. If you cannot, reread the part named.

| # | drill | part |
|---|---|---|
| 1 | Explain uplift vs propensity in 60 seconds to a non-technical PM | 1 |
| 2 | Draw the container diagram from memory and name the one backwards edge | 2 |
| 3 | Explain Qini to someone who knows AUC | 3 |
| 4 | Recite the four policy constraints in order, and why value fit precedes budget | 3 |
| 5 | Explain the T-learner failure: symptom, mechanism, fix | 3 |
| 6 | Explain how grounding is enforced without using the word "prompt" | 4 |
| 7 | Name the three defence tiers and give an example of each | 4 |
| 8 | Explain why a blocked message counts as a *pass* for the grounding metric | 4 |
| 9 | Explain sequential testing and quote the two false-positive numbers | 5 |
| 10 | Name the four stopping rules in order and say why harm is first | 5 |
| 11 | Recount three defects found only by running the code elsewhere | 6 |
| 12 | Name the unmet success criterion and its levers | 6 |

---

## 7.6 If something breaks during the demo

It probably will. Handle it well and it helps you.

| symptom | say this | then |
|---|---|---|
| Agent degrades to the template | *"That is the designed failure path — the model produced something the guardrails rejected, so the user gets a correct templated message instead of the rejected text."* | show the banner naming the reason |
| Local generation is slow | *"CPU inference, about 90 seconds. That is the latency gap I have recorded as an unmet criterion."* | use the time to explain local-first |
| API not running | *"Startup fails loudly when artifacts are missing rather than serving wrong numbers."* | `python run.py all` |
| Charts look empty | *"No events seeded yet."* | `python scripts/seed_experiment.py` |

**The general principle:** never explain a failure away. Name it, say what the system does
about it, and say what you would do next. That is the whole posture this project is built
to demonstrate.

---

[Back to index](README.md)
