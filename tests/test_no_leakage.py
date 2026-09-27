"""Feature 001/002 — task T034. The single most important test in the repository.

A model that sees `true_tau` or `p0` produces a spectacular metric and is
worthless. This test makes that failure impossible to introduce silently.
"""
from __future__ import annotations

import pytest

from f2g.data.schema import FEATURES, LABEL_COLUMNS, ORACLE_COLUMNS
from f2g.ml.features import FORBIDDEN_COLUMNS, FeatureError, FeaturePipeline


def test_features_exclude_labels_and_oracles():
    forbidden = set(LABEL_COLUMNS) | set(ORACLE_COLUMNS)
    assert set(FEATURES).isdisjoint(forbidden), set(FEATURES) & forbidden


def test_pipeline_refuses_forbidden_columns():
    for col in ("true_tau", "p0", "converted", "retained_30d", "value_fit", "user_id"):
        with pytest.raises(FeatureError):
            FeaturePipeline(feature_names=[*FEATURES, col])


def test_treatment_admitted_only_when_explicit():
    """`treated` is a legitimate S-learner feature and nothing else."""
    with pytest.raises(FeatureError):
        FeaturePipeline(feature_names=[*FEATURES, "treated"])
    p = FeaturePipeline(feature_names=list(FEATURES), treatment_column="treated")
    assert "treated" in p.columns


def test_forbidden_set_covers_every_oracle_column():
    assert set(ORACLE_COLUMNS).issubset(FORBIDDEN_COLUMNS)
    assert set(LABEL_COLUMNS).issubset(FORBIDDEN_COLUMNS)


def test_transformed_frame_contains_only_declared_columns(small_cohort):
    p = FeaturePipeline()
    X = p.transform(small_cohort)
    assert list(X.columns) == p.columns
    assert set(X.columns).isdisjoint(set(LABEL_COLUMNS) | set(ORACLE_COLUMNS))
