# LLD 003 — Targeting Policy Engine & Offline Policy Evaluation

**Domain**: B · **HLD**: [003](../hld/003-targeting-policy-engine.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/ml/policy.py` | `PolicyConfig`, `select`, value-fit estimation (both paths), fairness table |
| `f2g/ml/ope.py` | IPS, SNIPS, doubly robust, oracle, bootstrap intervals |
| `f2g/ml/run_policy.py` | Batch orchestration, reports, charts |

## Signatures

```python
# policy.py
GENIUS_COST_90D: float                 # catalog price × 3
DEFAULT_VALUE_FIT_MARGIN = 1.0
VALUE_FIT_FEATURES = ["instant_delivery", "overdraft_shield", "subscription_watch"]
VECTORISED_FEATURES = ["instant_delivery", "overdraft_shield"]

class Reason:  SELECTED | NEGATIVE_UPLIFT | VALUE_FIT | BUDGET | PARITY_CAP | NO_DATA

@dataclass
class PolicyConfig:
    contact_budget: float = 0.20
    value_fit_margin: float = 1.0
    value_fit_enabled: bool = True
    parity_enabled: bool = False
    parity_tolerance: float = 0.10
    fairness_attribute: str = "income_band"

def estimate_value_fit(user_ids) -> DataFrame          # reference, per-user, via tools
def estimate_value_fit_vectorized(frame) -> DataFrame  # batch, from aggregate columns
def select(candidates, uplift, propensity=None, cfg=None, value_fit=None) -> PolicyResult

# ope.py
MIN = DEFAULT_WEIGHT_CLIP = 20.0
def ips(y, t, pi, e=0.5, *, clip, seed) -> PolicyValue
def snips(y, t, pi, e=0.5, *, clip, seed) -> PolicyValue
def doubly_robust(y, t, pi, mu0, mu1, e=0.5, *, clip, seed) -> PolicyValue
def oracle_value(p0, tau, pi) -> PolicyValue
def evaluate_policy(frame, pi, mu0=None, mu1=None, *, treatment_propensity, seed) -> DataFrame
def oracle_within_interval(table, estimator="DR") -> bool | None
```

## Algorithms

### Value fit

```text
saving_90d = instant_transfer_fees_90d
           + overdraft_fees_90d × coverage_rate          # 0.70, from the catalog
           [+ flagged_subscription_monthly × 3 × cancel_rate]   # reference path only
cost_90d   = GENIUS_MONTHLY_PRICE × 3                    # 44.97
passes     ⟺ saving_90d ≥ cost_90d × margin
```

The subscription term depends on a per-user `looks_unused` draw that exists only inside the
ledger, so the vectorised path omits it. **Omitting it makes the gate stricter, never laxer** —
the safe direction for a suppression decision — and `VECTORISED_FEATURES` names exactly the
subset the equivalence test compares.

### Two paths, one answer

| | reference | vectorised |
|---|---|---|
| Source | `ConciergeTools.estimate_savings` per user | aggregate feature columns |
| Cost | builds a ledger per user | one pass over a frame |
| Use | what the agent will say; single-user API calls | batch policy cycles |
| Equivalence | `tests/test_policy.py::test_value_fit_paths_agree`, 60 users, tolerance $0.011 | |

### Selection

```python
df["decision"] = SELECTED
df.loc[uplift <= 0]                            = NEGATIVE_UPLIFT
df.loc[~has_data & still_selected]             = NO_DATA
df.loc[saving < cost*margin & still_selected]  = VALUE_FIT

eligible = still_selected.sort_values(["uplift", "user_id"], ascending=[False, True])
if len(eligible) <= n_budget:
    binding = VALUE_FIT            # the budget was not the constraint
else:
    keep = eligible.head(n_budget); rest -> BUDGET; binding = BUDGET
```

Ties are broken by `user_id` so that two runs on identical input produce an identical list —
without it, pandas' sort stability across differing input orders is not a contract worth
relying on.

### Fairness decomposition

```text
contact_rate(band)  = contacted(band) / n(band)          # what the policy did
eligible_rate(band) = mean(uplift > 0 | band)            # a property of the population
policy_induced_gap  = contact_rate_gap − eligible_rate_gap × contact_budget
```

Reporting only `contact_rate_gap` conflates a gap we inherited with one we created, and that
conflation is how fairness reporting becomes theatre.

### Parity cap

```python
band_cap = floor(contact_budget × n_users_in_band)   # a RATE cap
```

The earlier implementation used `floor(n_budget / n_bands)` — an equal *count* per band. With
unequal band sizes that equalises counts while diverging rates, and measured worse than no cap
at all (gap 0.064 against 0.040).

### Off-policy estimators

```text
e_i          = P(T_i = 1) = 0.5                    # known by randomisation
prob_taken_i = e_i if pi_i = 1 else (1 − e_i)
w_i          = 1{t_i = pi_i} / prob_taken_i,  clipped at 20

IPS   = mean(w · y)
SNIPS = Σ(w · y) / Σ(w)
DR    = mean( mu_pi + w · (y − mu_obs) )
oracle= mean( p0 + tau · pi )
```

`mu0`/`mu1` come from the X-learner's stage-1 arm models, which already exist — no extra fit.

Intervals are bootstrap (400 resamples) for the three estimators; the oracle uses a normal
interval since it is a plain mean with no importance weights.

## Data shapes

```python
# PolicyResult.decisions — one row per candidate
["user_id", "segment", "income_band", "uplift", "propensity",
 "estimated_saving_90d", "genius_cost_90d", "net_position_90d", "has_data",
 "decision", "reason_detail"]

# PolicyResult.summary
{"candidates", "selected", "budget_slots", "budget_used", "binding_constraint",
 "suppressed_by_reason", "mean_uplift_selected", "mean_saving_selected",
 "expected_incremental_conversions", "contact_rate_gap", "eligible_rate_gap",
 "policy_induced_gap", "fairness_flag", "value_fit_threshold_usd",
 "backfilled_by_gate"}
```

`backfilled_by_gate` counts users selected under the gate who would have been budget-cut
without it — the metric that makes the "not a subset" property visible instead of surprising.

## Measured outcome

| | |
|---|---|
| Candidates / selected | 12,000 / 1,801 |
| Binding constraint | `value_fit` |
| Suppressed: value fit / negative uplift | 7,530 / 2,669 |
| Mean saving of contacted, gate on / off | $70.21 / $34.75 |
| Conversions forgone to the gate | 95.3 |
| Contact-rate gap | 0.021 (tolerance 0.10) |
| DR interval covers the oracle | all 5 policies |

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_never_contacts_negative_uplift` | Do-no-harm, unconditional |
| `test_high_uplift_zero_fee_user_is_suppressed` | The headline claim |
| `test_missing_data_fails_the_gate_rather_than_passing` | Absence ≠ benefit |
| `test_gate_backfills_freed_budget_rather_than_shrinking` | The corrected invariant |
| `test_parity_cap_reduces_the_gap` | The count-vs-rate fix |
| `test_value_fit_paths_agree` | Fast path cannot drift from the agent |
| `test_selection_is_deterministic` | Reproducible lists |
| `test_dr_interval_covers_the_oracle` | The estimator itself works |
| `test_clipped_fraction_is_reported` | Clipping is never silent |
