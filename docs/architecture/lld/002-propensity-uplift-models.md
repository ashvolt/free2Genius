# LLD 002 — Propensity & Uplift Models

**Domain**: B · **HLD**: [002](../hld/002-propensity-uplift-models.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/ml/features.py` | `FeaturePipeline`, `FORBIDDEN_COLUMNS`, `CATEGORY_LEVELS`, `FeatureError` |
| `f2g/ml/models.py` | Estimators and the three hyperparameter sets |
| `f2g/ml/evaluate.py` | All metrics; no I/O, no model imports — pure functions over arrays |
| `f2g/ml/charts.py` | Figure construction only |
| `f2g/ml/registry.py` | `BundleMeta`, `ModelBundle`, `data_fingerprint` |
| `f2g/ml/train.py` | Orchestration, report generation, CLI |
| `f2g/viz.py` | Palette, matplotlib style, `end_labels`, `rounded_bars`, `caption` |

`evaluate.py` deliberately imports no model code. Metrics are testable against analytically
known cases without constructing an estimator, which is why the metric tests can prove a
metric bug is not a model bug.

## Signatures

```python
# features.py
@dataclass
class FeaturePipeline:
    feature_names: list[str] = FEATURES
    treatment_column: str | None = None
    @property
    def columns(self) -> list[str]
    def transform(self, df: pd.DataFrame) -> pd.DataFrame
    def validate_against(self, recorded: list[str]) -> None     # raises FeatureError

# models.py
BASE_PARAMS: dict            # outcome models
UPLIFT_ARM_PARAMS: dict      # uplift arm models
XLEARNER_STAGE2_PARAMS: dict # imputed-effect regressors

class PropensityModel: fit(train, valid, seed); predict_proba(df) -> ndarray
class SLearner:        fit(...); predict_uplift(df) -> ndarray
class TLearner:        arm_params: dict | None; fit(...); predict_uplift(df) -> ndarray
class XLearner:        treatment_propensity: float = 0.5; fit(...); predict_uplift(df) -> ndarray

# evaluate.py
classification_metrics(y, p) -> dict
calibration_table(y, p, bins=10) -> DataFrame
calibration_error(y, p, bins=10) -> float
qini_curve(y, t, score, steps=100) -> QiniResult
uplift_decile_table(y, t, score, k=10) -> DataFrame
tau_recovery(tau_hat, tau_true) -> dict
incremental_conversions_at_budget(y, t, score, budget) -> dict
policy_comparison(y, t, scores: dict, budget, seed=0) -> DataFrame
budget_sweep(y, t, scores: dict, budgets=(...), seed=0) -> DataFrame
segment_mix_of_selection(df, score, budget) -> DataFrame
slice_metrics(df, values, by, metric_fn, min_count=200) -> DataFrame
MIN_RATIO_DENOMINATOR = 0.005
```

## Algorithms

### Qini

For users sorted by score descending, at each prefix of size *n*:

```text
Qini(n) = Y_t(n) − Y_c(n) · N_t(n) / N_c(n)
```

`Y_t`, `Y_c` are cumulative conversions per arm; `N_t`, `N_c` cumulative counts. The
rescaling factor makes the arms comparable at every prefix, including early prefixes where
the arm split is uneven by chance. Undefined until both arms are represented — returned as
0 for that prefix, not silently treated as a real value.

```text
coefficient = (area_model − area_random) / (|total_incremental| · 0.5)
```

`total_incremental` is score-independent, so coefficients from different rankings on the
same data are directly comparable. The coefficient is **not** bounded at 1; on this data the
oracle reaches 1.2815, which is why the oracle is reported as the ceiling rather than
assumed to be 1.

### X-learner

```text
stage 1   mu1 = P(Y | X, T=1)   fitted on the treated arm
          mu0 = P(Y | X, T=0)   fitted on the control arm

stage 2   treated i :  D_i = Y_i − mu0(X_i)
          control i :  D_i = mu1(X_i) − Y_i
          tau1 = regress D on X over treated users
          tau0 = regress D on X over control users

combine   tau(x) = g · tau0(x) + (1 − g) · tau1(x),   g = P(T=1) = 0.5 (known)
```

Lower variance than a T-learner because stage 2 fits a model *directly to an effect-shaped
target*, which can be regularised toward zero. A T-learner can only regularise its two
halves independently; it has no handle on their difference.

With observational data `g` would itself be a fitted model and its error would propagate
into τ̂. Here randomisation makes `g` a known constant — recorded as a limitation, because
it is the assumption most likely to be violated in a real deployment.

### Measured dispersion (why the parameters differ)

| estimator | min τ̂ | max τ̂ | std |
|---|---|---|---|
| true τ | −0.0444 | +0.1346 | 0.0317 |
| X-learner | −0.0807 | +0.1250 | 0.0264 |
| T-learner, regularised | −0.1947 | +0.2390 | 0.0459 |
| T-learner, outcome-tuned | −0.3463 | +0.3770 | 0.0578 |

### Ratio guard

```python
if abs(denominator) >= MIN_RATIO_DENOMINATOR:  # 0.5 pp
    ratio = value / denominator - 1
else:
    ratio = nan            # pp difference is always reported regardless
```

Exists because a propensity baseline whose uplift was −0.24 pp produced a headline of
**−2577%** during development. A meaningless number is worse than an absent one.

### Label de-collision (`viz.end_labels`)

Sort endpoint labels by y, push each up to a minimum gap of 7.5% of the axis span, clamp
into the axes, and draw a hairline connector wherever a label moved more than 1.5% of span
from its series.

The subtle bug here, caught by rendering and looking: the de-collided positions must be used
as the annotation **anchor**. Computing `y_at` and then annotating at `y_true` silently
discards the spacing — the labels still overlap and the code looks correct.

## Data shapes

```python
# BundleMeta
{"name", "kind", "feature_names": [...26 or 27...], "params", "metrics",
 "data_fingerprint", "n_train", "seed", "created_at", "versions", "notes"}

# QiniResult
{"fractions": [...], "qini": [...], "random_baseline": [...],
 "coefficient": float, "max_qini": float, "max_qini_at_fraction": float}
```

## Error paths

| Condition | Exception | Message contains |
|---|---|---|
| Label/oracle column as a feature | `FeatureError` | the offending column names |
| Missing feature column at transform | `FeatureError` | the missing list |
| Column order mismatch on load | `FeatureError` | both directional differences |
| Arm with < 500 rows or < 20 valid positives | `ValueError` | `too little signal`, with counts |
| Model bundle absent | `FileNotFoundError` | `python -m f2g.ml.train` |

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_features_exclude_labels_and_oracles` | The leakage invariant |
| `test_pipeline_refuses_forbidden_columns` | Each forbidden column individually |
| `test_treatment_admitted_only_when_explicit` | `treated` is S-learner-only |
| `test_bundle_roundtrip_reproduces_predictions` | SC-007, exact equality |
| `test_feature_contract_mismatch_is_loud` | Order drift raises |
| `test_t_learner_refuses_a_degenerate_arm` | No silent noise-fitting |
| `test_x_learner_is_less_dispersed_than_unregularised_t` | The regularisation fix cannot regress |
| `test_x_learner_recovers_true_tau` | Spearman floor |
| `test_qini_of_inverted_score_is_negative` | The metric has correct sign behaviour |
| `test_calibration_error_detects_bias` | The metric is not vacuous |
| `test_ratio_is_suppressed_when_denominator_near_zero` | The −2577% artifact cannot return |
| `test_budget_sweep_shape` | Advantage shrinks with reach |
| `test_slice_metrics_flags_low_confidence` | Small bands marked, not dropped |
