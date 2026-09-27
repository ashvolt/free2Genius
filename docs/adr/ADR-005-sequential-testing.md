# ADR-005 — Sequential (always-valid) inference for the A/B test

**Status**: Accepted · **Date**: 2026-09-27 · **Domain**: D (Product Surface)

## Context

The rollout needs an experiment comparing the uplift-targeted nudge against the current
generic upsell. The textbook design is fixed-horizon: compute a sample size, wait, run
one test at the end.

That design survives contact with a growth team for about a day. Someone will open the
dashboard on day three. If a decision is made on what they see, the reported p-value is
invalid — repeatedly testing accumulated data inflates the false-positive rate well
beyond the nominal α, often past 20% with daily looks. Telling people not to look is a
process control, and process controls fail.

There is also an ethical asymmetry specific to this test. One arm may be *harming* users
(the sleeping-dog effect). Being contractually unable to stop early is not a neutral
property.

## Decision

**Report always-valid sequential confidence sequences alongside the fixed-horizon
design.** The fixed-horizon sample size is still computed and published — it sets the
expected duration and is what a reviewer asks for. But the monitoring surface reports a
sequential bound that is valid at every look.

Method: a mixture sequential probability ratio test for two proportions, exposed as an
anytime-valid confidence sequence on the difference in conversion rates.

Stopping rules, declared before launch:

- **Ship** when the sequential lower bound on conversion lift exceeds zero *and* the
  retention guardrail's lower bound clears its non-inferiority margin.
- **Stop for harm** when the retention guardrail's sequential upper bound breaches the
  margin — regardless of what conversion is doing. This rule is checked first.
- **Stop for futility** at the planned horizon if the sequence has not separated.

## Consequences

**Gained**

- The dashboard can be read by anyone, at any time, without invalidating the analysis.
  The statistical property matches how humans actually behave.
- Harm can be stopped the moment it is detectable, which for an experiment that may
  degrade retention is the decisive argument.
- Expected duration shortens when the effect is real, because we do not wait out the
  horizon.

**Paid**

- Wider intervals than fixed-horizon at the planned sample size — the price of validity
  under continuous monitoring, roughly a 15–25% sample-size premium for the same power.
  Stated in the experiment design rather than buried.
- More machinery than `scipy.stats.proportions_ztest`, and it has to be tested against
  simulation to show the coverage claim holds.
- Two numbers on screen (fixed and sequential) need explaining. Handled with a tooltip
  and a line in the demo script.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Fixed-horizon only | Invalid under the peeking that will certainly happen; cannot stop early for harm |
| Bayesian posterior on lift | Defensible and intuitive, but requires a prior conversation the team has not had, and loses the frequentist guarantee a reviewer expects |
| Group-sequential (O'Brien–Fleming) | Valid only at pre-planned interim analyses — still breaks under ad-hoc dashboard reads |
| Bandit allocation | Optimizes cumulative reward, not inference. We need a clean effect estimate to decide whether the programme ships at all, and a bandit muddies the guardrail reading |
