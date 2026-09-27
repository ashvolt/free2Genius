# Consent and Data Use — Free2Genius

> Synthetic project. No real user data exists in this repository. This note describes what a
> real deployment would have to establish, written as the document a privacy reviewer would
> ask for.

## What data the system uses

| Category | Fields | Why it is needed |
|---|---|---|
| Account | tenure, plan, direct deposit status and streak | Establishes engagement and eligibility |
| Cash flow | average daily balance, days under a low-balance threshold | Identifies users under cash-flow stress, whom the advance features serve |
| Advances | count, amounts, delivery method, repayment timeliness | Determines whether advance-related features are relevant |
| Fees | express-delivery and overdraft fee events, dated | The evidence for every savings claim the agent makes |
| Recurring charges | detected merchants and amounts | Only used when discussing subscription tracking |
| Budgeting | session counts, categories tracked | Signals whether budgeting features are relevant |
| Demographic bands | income band, age band | **Monitoring only** — see below |

## Purpose limitation

The data above is used for exactly two things:

1. Deciding whether to invite a user to the paid tier.
2. Explaining, to that user, which features would save them money.

It is not used for credit, lending, underwriting, eligibility, pricing, or any decision with a
legal or similarly significant effect. That boundary is stated as out-of-scope use in the model
card and is the first thing to re-check if anyone proposes reusing these models.

## Demographic attributes

Income band and age band are used to **monitor** the system for disparate treatment. Whether
they should also be model *inputs* is a question this project does not settle: in the synthetic
setting they are available to the model, and a real programme would need a legal decision on
which attributes may be used for monitoring, which for modelling, and which for neither.

A parity-constrained selection mode exists so that, if monitoring reveals a gap the business
judges unacceptable, there is a mechanism to close it with its cost stated.

## Lawful basis a real deployment would need

Marketing a paid tier to existing users based on their account behaviour is ordinarily a
legitimate-interests case, but it requires:

- a documented legitimate interests assessment weighing the benefit against the intrusion;
- a clear, easy opt-out from marketing that is honoured in the targeting pipeline, not only in
  the delivery layer — a suppression list consulted *before* scoring, so opted-out users are
  never scored rather than scored and filtered;
- transparency in the privacy notice that account behaviour informs which offers are shown;
- for any jurisdiction where this constitutes automated decision-making with significant
  effect, a route to human review. This system is deliberately scoped to avoid that
  classification by never touching access to money.

## What the agent may see

The concierge agent reads only the bound user's own account data, through six narrow tools.
It cannot query other users: identity is fixed at session construction and is not a parameter
the model can supply. It cannot mutate anything — the agent is advisory and has no write path.

## Where the data goes

In the default configuration, nowhere. Inference runs in-process against local open-weights
model files, so no account attribute crosses a network boundary to a third party.

Enabling the hosted provider changes this and is deliberately an explicit configuration
change that logs a warning naming the egress. Before enabling it, a real deployment would need
a data-processing agreement, a PII redaction layer, and a re-run of the privacy assessment.
None of those exist here, which is why the default is local.

## Retention

Generated messages, decision records and funnel events are retained for audit — they are what
answers "why was I contacted?". A real deployment would set a retention period aligned to the
complaints window and delete on account closure. The current store has no retention policy,
which is recorded as a gap.

## Rights

A real deployment must support access, deletion and objection. The audit endpoint
(`GET /audit/{user_id}`) is the beginning of an access response: it returns every decision,
generation and event recorded for one user. Deletion is not implemented.
