"""Feature 002 — estimators and the model registry.

These train on a small cohort so the suite stays fast; the full-scale numbers
live in `artifacts/reports/model_evaluation.md`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f2g import config
from f2g.data.generate import generate_cohort
from f2g.data.schema import FEATURES
from f2g.ml.features import FeatureError, FeaturePipeline
from f2g.ml.models import PropensityModel, SLearner, TLearner, XLearner
from f2g.ml.registry import BundleMeta, ModelBundle, data_fingerprint


@pytest.fixture(scope="module")
def cohorts():
    train = generate_cohort(9000, seed=21, cohort="pilot", treatment_share=0.5, id_prefix="a")
    valid = generate_cohort(3000, seed=22, cohort="pilot", treatment_share=0.5, id_prefix="b")
    test = generate_cohort(3000, seed=23, cohort="pilot", treatment_share=0.5, id_prefix="c")
    return train, valid, test


def test_propensity_discriminates(cohorts):
    from sklearn.metrics import roc_auc_score

    train, valid, test = cohorts
    m = PropensityModel(pipeline=FeaturePipeline()).fit(
        train[train.treated == 0], valid[valid.treated == 0], config.RANDOM_SEED
    )
    ctrl = test[test.treated == 0]
    auc = roc_auc_score(ctrl.converted, m.predict_proba(ctrl))
    assert auc > 0.70, f"AUC {auc:.4f} below the SC-001 floor"


def test_t_learner_uplift_is_signed(cohorts):
    """Uplift must be allowed to be negative — the negative region is acted on."""
    train, valid, test = cohorts
    m = TLearner(pipeline=FeaturePipeline()).fit(train, valid, config.RANDOM_SEED)
    tau = m.predict_uplift(test)
    assert (tau < 0).any(), "estimator never predicts negative uplift"
    assert (tau > 0).any()


def test_x_learner_is_less_dispersed_than_unregularised_t(cohorts):
    """The core finding: the X-learner does not blow up the effect range.

    A T-learner on outcome-tuned hyperparameters predicts uplift far outside the
    range that exists. This test pins the fix so a hyperparameter change cannot
    silently reintroduce it.
    """
    from f2g.ml.models import BASE_PARAMS

    train, valid, test = cohorts
    pipe = FeaturePipeline()
    t_unreg = TLearner(pipeline=pipe, arm_params=BASE_PARAMS).fit(train, valid, config.RANDOM_SEED)
    x = XLearner(pipeline=pipe).fit(train, valid, config.RANDOM_SEED)

    true_span = test.true_tau.max() - test.true_tau.min()
    unreg = t_unreg.predict_uplift(test)
    xl = x.predict_uplift(test)
    assert (xl.max() - xl.min()) < (unreg.max() - unreg.min())
    assert (xl.max() - xl.min()) < true_span * 2.0, "X-learner still over-dispersed"


def test_x_learner_recovers_true_tau(cohorts):
    from scipy import stats

    train, valid, test = cohorts
    x = XLearner(pipeline=FeaturePipeline()).fit(train, valid, config.RANDOM_SEED)
    rho = stats.spearmanr(x.predict_uplift(test), test.true_tau).statistic
    assert rho > 0.35, f"Spearman {rho:.3f} — estimator is not recovering the effect"


def test_s_learner_trains_and_toggles_treatment(cohorts):
    train, valid, test = cohorts
    pipe = FeaturePipeline(feature_names=list(FEATURES), treatment_column="treated")
    m = SLearner(pipeline=pipe).fit(train, valid, config.RANDOM_SEED)
    assert m.predict_uplift(test).shape == (len(test),)


def test_t_learner_refuses_a_degenerate_arm(cohorts):
    """A silently-degenerate arm model yields plausible noise. Fail loudly."""
    train, valid, _ = cohorts
    tiny = train[train.treated == 1].head(50)
    mixed = pd.concat([train[train.treated == 0], tiny])
    with pytest.raises(ValueError, match="too little signal"):
        TLearner(pipeline=FeaturePipeline()).fit(mixed, valid, config.RANDOM_SEED)


def test_bundle_roundtrip_reproduces_predictions(cohorts, tmp_path):
    """SC-007: reload-and-score must match training-time predictions exactly."""
    train, valid, test = cohorts
    pipe = FeaturePipeline()
    m = PropensityModel(pipeline=pipe).fit(
        train[train.treated == 0], valid[valid.treated == 0], config.RANDOM_SEED
    )
    before = m.predict_proba(test)

    bundle = ModelBundle(
        BundleMeta(name="tmp_prop", kind="propensity", feature_names=pipe.columns,
                   params={}, data_fingerprint=data_fingerprint(train), n_train=len(train)),
        m,
    )
    bundle.save(tmp_path)
    after = ModelBundle.load("tmp_prop", tmp_path).estimator.predict_proba(test)
    np.testing.assert_array_equal(before, after)


def test_bundle_writes_readable_sidecar(cohorts, tmp_path):
    import json

    pipe = FeaturePipeline()
    bundle = ModelBundle(
        BundleMeta(name="tmp_meta", kind="propensity", feature_names=pipe.columns, params={}),
        None,
    )
    bundle.save(tmp_path)
    meta = json.loads((tmp_path / "tmp_meta.meta.json").read_text(encoding="utf-8"))
    assert meta["feature_names"] == pipe.columns
    assert meta["versions"]["lightgbm"]


def test_feature_contract_mismatch_is_loud():
    """FR-009: a column-order change must fail, not silently mis-score."""
    pipe = FeaturePipeline()
    shuffled = list(reversed(pipe.columns))
    with pytest.raises(FeatureError, match="contract mismatch"):
        pipe.validate_against(shuffled)
    pipe.validate_against(pipe.columns)  # identical is fine


def test_missing_bundle_names_the_fix(tmp_path):
    with pytest.raises(FileNotFoundError, match="f2g.ml.train"):
        ModelBundle.load("nope", tmp_path)


def test_transform_rejects_missing_columns(cohorts):
    train, _, _ = cohorts
    with pytest.raises(FeatureError, match="missing required feature columns"):
        FeaturePipeline().transform(train.drop(columns=["tenure_days"]))
