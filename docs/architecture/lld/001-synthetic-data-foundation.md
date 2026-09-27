# LLD 001 — Synthetic Data Foundation

**Domain**: A · **HLD**: [001](../hld/001-synthetic-data-foundation.md) · **Status**: Implemented

## Module map

| Module | Lines of responsibility |
|---|---|
| `f2g/config.py` | Root-relative paths, seed, cohort sizes, model tiers, `has_anthropic_key()`, `ensure_dirs()` |
| `f2g/data/schema.py` | Column group constants only. No logic — a contract file that can be imported by tests without side effects |
| `f2g/data/generate.py` | The structural causal model and the CLI |
| `f2g/data/accounts.py` | `AccountRepository`, `build_ledger`, deterministic per-user RNG |
| `f2g/data/catalog.py` | Pricing constants, feature definitions, disclosure |

## Signatures

```python
# f2g/data/generate.py
def _draw_segments(rng: np.random.Generator, n: int) -> np.ndarray
def _behaviour_frame(rng: np.random.Generator, segment: np.ndarray) -> pd.DataFrame
def _baseline_and_effect(df, segment, rng) -> tuple[np.ndarray, np.ndarray]   # (p0, tau)
def _value_fit(df: pd.DataFrame) -> np.ndarray                                # [0, 1]
def generate_cohort(n_users: int, seed: int, cohort: str,
                   treatment_share: float, id_prefix: str) -> pd.DataFrame
def build(n_users=None, seed=None, n_live=None) -> tuple[pd.DataFrame, pd.DataFrame]
def main() -> None

# f2g/data/accounts.py
def _user_rng(user_id: str) -> np.random.Generator
def _spread_dates(rng, count: int, window_days: int = 90) -> list[str]
class AccountRepository:
    def get(self, user_id: str) -> dict[str, Any] | None
    def exists(self, user_id: str) -> bool
    def ids(self, cohort: str | None = None, limit: int | None = None) -> list[str]
@functools.lru_cache(maxsize=1)
def repository() -> AccountRepository
@functools.lru_cache(maxsize=4096)
def build_ledger(user_id: str) -> dict[str, Any]

# f2g/data/catalog.py
def get_catalog() -> dict[str, Any]
def get_feature(feature_id: str) -> dict[str, Any] | None
```

## Algorithms

### Baseline conversion index

```text
z = -3.05
  + 0.55 · direct_deposit_active
  + 0.030 · min(dd_consecutive_months, 18)
  + 0.045 · min(budget_sessions_30d, 12)
  + 0.021 · min(app_opens_30d, 30)
  + 0.085 · min(prior_upsell_views_90d, 8)
  - 0.030 · days_since_last_open
  + 0.0016 · min(overdraft_fees_90d, 300)
  + 0.0090 · min(instant_transfer_fees_90d, 80)
  + 0.30  · savings_auto_enabled
  - 0.045 · min(support_contacts_90d, 6)
  + segment_offset            # sure_thing +1.45, lost_cause −0.85, sleeping_dog −0.25
p0 = clip(sigmoid(z + N(0, 0.25)), 0.002, 0.92)
```

Caps (`min(...)`) keep single extreme features from dominating the index — the same reason a real
scorecard caps its inputs.

### Treatment effect

```text
fee_pain  = clip(instant_transfer_fees/30 + overdraft_fees/120, 0, 3)
reachable = sigmoid(0.18 · app_opens − 1.1) · (1 if push_enabled else 0.7)

tau = persuadable  :  0.030 + 0.045 · fee_pain · reachable + 0.020 · direct_deposit
      sure_thing   :  0.004 + 0.004 · reachable
      lost_cause   :  0.001 + 0.002 · reachable
      sleeping_dog : −0.012 − 0.018 · clip(support_contacts/4, 0, 1)
tau += N(0, 0.004)
tau  = clip(tau, −0.9·p0, 1 − p0 − 1e−6)          # keeps p0+tau a probability
```

`fee_pain × reachable` is the product structure that makes uplift *learnable but non-trivial*:
effect requires both a reason to switch and the ability to receive the message. Neither feature
alone predicts it.

### Retention with the push mechanism

```text
p_convert = p0 + tau·T
pushed    ~ Bernoulli(tau / p_convert)  where T = 1     # was this conversion caused by contact?
retain_p  = clip(0.58 + 0.34·value_fit
                 − 0.22 · pushed · (1 − value_fit), 0.05, 0.97)
R         ~ Bernoulli(retain_p)   only where Y = 1, else sentinel −1
```

The interaction term is the point: being *pushed* only hurts retention when value fit is poor.
A nudged user who genuinely benefits retains normally.

### Ledger reconciliation

| Collection | Reconciliation mechanism |
|---|---|
| Fee events | Emit exactly `_instant_transfer_count_90d` at $4.99 and `_overdraft_count_90d` at $34.00. Sum is arithmetically forced |
| Subscriptions | Draw merchant prices, then multiply every price by `target_total / raw_total`. Exact by construction |
| Advances | Count from `advances_90d`; amounts drawn around `advance_amount_avg`. Total is *not* pinned to an aggregate, because no aggregate for it is used as a model feature |
| Deposits | Three half-month deposits at `dd_amount_monthly / 2`, only when direct deposit is active |

`_spread_dates` samples **without replacement** from the trailing window, so two fee events never
land on the same date — which would read as a duplicate charge to a user.

## Data shapes

```python
# Ledger
{
  "user_id": "u0000035", "as_of": "2026-09-01", "window_days": 90,
  "fee_events": [{"date": "2026-08-29", "type": "instant_transfer",
                  "amount_usd": 4.99, "description": str, "charged_by": "albert"}],
  "advances":   [{"date": str, "amount_usd": float,
                  "delivery": "instant"|"standard", "repaid_on_time": bool}],
  "subscriptions": [{"merchant": str, "monthly_usd": float,
                     "last_charged": str, "looks_unused": bool}],
  "direct_deposits": [{"date": str, "amount_usd": float, "source": str}],
}
```

Label sentinel: `-1` for unobserved, used for live-cohort labels and for retention of
non-converters. Chosen over `NaN` because `NaN` silently vanishes from a `mean()` while `-1`
produces an obviously wrong number that a test catches.

## Error paths

| Condition | Behaviour |
|---|---|
| Cohort CSVs absent | `repository()` raises `FileNotFoundError` naming the generate command |
| Unknown user id | `build_ledger` raises `KeyError(user_id)` |
| `raw_total == 0` with non-zero target spend | Unreachable: zero subscriptions implies zero aggregate spend in the generator. Scale guarded to 1.0 anyway |
| `advances_90d == 0` | Empty advances list; `average_advance_usd` returns 0.0 rather than dividing by zero |

## Caching

`repository()` is `lru_cache(1)` — one cohort load per process. `build_ledger` is
`lru_cache(4096)` — bounded, and safe to cache because the function is pure in `user_id`.

**Consequence for tests**: a test that regenerates cohorts must clear both caches, or it reads the
previous population. Recorded here because it is the single most likely source of a confusing test
failure in this feature.

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_determinism` | Same seed → identical frames |
| `test_ate_matches_true_tau` | Observed ATE within 2 SE of mean tau (SC-001) |
| `test_segment_separation` | One segment ≥ +0.04, one ≤ −0.01 (SC-003) |
| `test_ledger_reconciles` | Fee events sum to aggregates to the cent (SC-002) |
| `test_ledger_stable` | Repeated builds identical |
| `test_empty_collections` | Zero-fee / no-DD users valid |
| `test_no_oracle_leakage` | `FEATURES ∩ (LABEL ∪ ORACLE) = ∅` |
| `test_live_sentinel` | Live labels are the sentinel, never 0 |
