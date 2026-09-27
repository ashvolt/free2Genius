"""Estimators: one propensity model and two uplift meta-learners.

The propensity model answers "will this user convert?". The uplift models answer
"does contacting this user change whether they convert?". Those are different
questions with different right answers, and conflating them is the mistake this
whole feature exists to avoid — see
`docs/adr/ADR-002-uplift-over-propensity.md`.

Two uplift estimators are implemented because they fail differently:

* **S-learner** — one model with treatment as an input feature. Efficient, but
  gradient boosting will happily ignore a single weak binary feature when the
  other 26 explain the outcome better, so it can estimate tau ~ 0 everywhere and
  still report excellent outcome accuracy. That failure is invisible if you only
  look at AUC.
* **T-learner** — one model per arm, tau as their difference. Cannot ignore
  treatment because treatment *is* the split. Pays for it in variance: two
  estimates subtracted, each fitted on half the data.

Both are trained and compared. Expecting one to win a priori would be a guess;
measuring which does is the job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from f2g.ml.features import FeaturePipeline

# Shared defaults. `deterministic` + `force_row_wise` + fixed threads are what
# make repeated runs bit-identical; without them LightGBM's histogram
# construction varies with thread scheduling and metrics drift run to run.
BASE_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "n_estimators": 600,
    "learning_rate": 0.045,
    "num_leaves": 31,
    "min_child_samples": 60,
    "subsample": 0.85,
    "subsample_freq": 1,
    "colsample_bytree": 0.85,
    "reg_lambda": 1.0,
    "verbose": -1,
    "n_jobs": 4,
    "deterministic": True,
    "force_row_wise": True,
}


# Uplift arm models need far heavier regularisation than an outcome model.
# The signal they must resolve (tau, a few percentage points) is an order of
# magnitude smaller than the outcome they are fitted on (conversion, ~15%), and a
# T-learner SUBTRACTS two such fits — so any noise each model carries is
# amplified, not cancelled. Measured on this population, default LightGBM
# settings produced tau in [-0.35, +0.38] against a true range of [-0.04, +0.13]:
# almost 3x over-dispersed, with the extreme deciles populated by noise rather
# than by real effect. Smoother arm models are not a nicety here, they are the
# difference between a usable estimator and a random one.
UPLIFT_ARM_PARAMS: dict[str, Any] = {
    "n_estimators": 400,
    "learning_rate": 0.030,
    "num_leaves": 8,
    "min_child_samples": 300,
    "colsample_bytree": 0.70,
    "reg_lambda": 20.0,
}

# Stage-2 models of the X-learner regress *imputed* treatment effects, which are
# noisy by construction, so they are regularised harder still.
XLEARNER_STAGE2_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "n_estimators": 300,
    "learning_rate": 0.030,
    "num_leaves": 8,
    "min_child_samples": 400,
    "colsample_bytree": 0.70,
    "reg_lambda": 30.0,
    "verbose": -1,
    "n_jobs": 4,
    "deterministic": True,
    "force_row_wise": True,
}


def _fit_regressor(
    X: pd.DataFrame,
    y: np.ndarray,
    X_valid: pd.DataFrame,
    y_valid: np.ndarray,
    seed: int,
) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**{**XLEARNER_STAGE2_PARAMS, "random_state": seed})
    model.fit(
        X,
        y,
        eval_X=X_valid,
        eval_y=y_valid,
        eval_metric="l2",
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )
    return model


def _fit_one(
    X: pd.DataFrame,
    y: np.ndarray,
    X_valid: pd.DataFrame,
    y_valid: np.ndarray,
    seed: int,
    params: dict[str, Any] | None = None,
) -> lgb.LGBMClassifier:
    p = {**BASE_PARAMS, **(params or {}), "random_state": seed}
    model = lgb.LGBMClassifier(**p)
    model.fit(
        X,
        y,
        eval_X=X_valid,
        eval_y=y_valid,
        eval_metric="binary_logloss",
        callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)],
    )
    return model


@dataclass
class PropensityModel:
    """P(convert | x), fitted on the untreated arm.

    Deliberately trained on control only. Fitted on the pooled population it
    would absorb the average treatment effect and become a blend of "will
    convert" and "was contacted" — useless as a baseline for the comparison in
    `evaluate.py`, because it would already contain part of the answer.
    """

    pipeline: FeaturePipeline
    model: lgb.LGBMClassifier | None = None

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame, seed: int) -> "PropensityModel":
        self.model = _fit_one(
            self.pipeline.transform(train),
            train["converted"].to_numpy(),
            self.pipeline.transform(valid),
            valid["converted"].to_numpy(),
            seed,
        )
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model is not None, "model not fitted"
        return self.model.predict_proba(self.pipeline.transform(df))[:, 1]

    @property
    def feature_importance(self) -> dict[str, float]:
        assert self.model is not None
        return dict(
            sorted(
                zip(self.pipeline.columns, self.model.feature_importances_.astype(float)),
                key=lambda kv: -kv[1],
            )
        )


@dataclass
class SLearner:
    """Single model with treatment as a feature; tau by counterfactual toggle."""

    pipeline: FeaturePipeline  # must carry treatment_column
    model: lgb.LGBMClassifier | None = None

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame, seed: int) -> "SLearner":
        self.model = _fit_one(
            self.pipeline.transform(train),
            train["converted"].to_numpy(),
            self.pipeline.transform(valid),
            valid["converted"].to_numpy(),
            seed,
        )
        return self

    def predict_uplift(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model is not None, "model not fitted"
        tcol = self.pipeline.treatment_column
        assert tcol is not None
        treated = df.copy()
        treated[tcol] = 1
        control = df.copy()
        control[tcol] = 0
        p1 = self.model.predict_proba(self.pipeline.transform(treated))[:, 1]
        p0 = self.model.predict_proba(self.pipeline.transform(control))[:, 1]
        return p1 - p0

    def predict_proba_treated(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model is not None
        tcol = self.pipeline.treatment_column
        treated = df.copy()
        treated[tcol] = 1
        return self.model.predict_proba(self.pipeline.transform(treated))[:, 1]


@dataclass
class TLearner:
    """One model per arm; tau = P(Y|x, T=1) − P(Y|x, T=0).

    `arm_params` is explicit so the regularisation ablation in `train.py` can fit
    this estimator both ways — default settings and regularised — and report the
    difference as a measured result rather than a remembered one.
    """

    pipeline: FeaturePipeline
    arm_params: dict[str, Any] | None = None
    model_treated: lgb.LGBMClassifier | None = None
    model_control: lgb.LGBMClassifier | None = None

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame, seed: int) -> "TLearner":
        for arm, attr in ((1, "model_treated"), (0, "model_control")):
            tr = train[train["treated"] == arm]
            va = valid[valid["treated"] == arm]
            if len(tr) < 500 or va["converted"].sum() < 20:
                # Fail loudly. A degenerate arm model produces a plausible-looking
                # tau that is pure noise, and nothing downstream would notice.
                raise ValueError(
                    f"arm treated={arm} has too little signal to fit "
                    f"(n_train={len(tr)}, valid_positives={int(va['converted'].sum())})"
                )
            setattr(
                self,
                attr,
                _fit_one(
                    self.pipeline.transform(tr),
                    tr["converted"].to_numpy(),
                    self.pipeline.transform(va),
                    va["converted"].to_numpy(),
                    seed + arm,
                    params=self.arm_params if self.arm_params is not None else UPLIFT_ARM_PARAMS,
                ),
            )
        return self

    def _arm_proba(self, model: lgb.LGBMClassifier, df: pd.DataFrame) -> np.ndarray:
        return model.predict_proba(self.pipeline.transform(df))[:, 1]

    def predict_uplift(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model_treated is not None and self.model_control is not None
        return self._arm_proba(self.model_treated, df) - self._arm_proba(self.model_control, df)

    def predict_proba_treated(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model_treated is not None
        return self._arm_proba(self.model_treated, df)

    def predict_proba_control(self, df: pd.DataFrame) -> np.ndarray:
        assert self.model_control is not None
        return self._arm_proba(self.model_control, df)

    @property
    def feature_importance(self) -> dict[str, float]:
        assert self.model_treated is not None and self.model_control is not None
        imp = (
            self.model_treated.feature_importances_.astype(float)
            + self.model_control.feature_importances_.astype(float)
        ) / 2
        return dict(sorted(zip(self.pipeline.columns, imp), key=lambda kv: -kv[1]))


@dataclass
class XLearner:
    """X-learner: the standard remedy for T-learner variance.

    The T-learner's weakness is that it estimates tau as the *difference of two
    outcome models*, so each model's error enters the estimate at full weight. The
    X-learner instead regresses on imputed effects, which is a much smoother
    target:

        Stage 1  fit mu0 on the control arm, mu1 on the treated arm  (outcome models)
        Stage 2  impute a per-user effect using the OPPOSITE arm's model
                    treated i :  D_i = Y_i - mu0(X_i)      # observed minus counterfactual
                    control i :  D_i = mu1(X_i) - Y_i      # counterfactual minus observed
                 then fit tau1 on the treated users' D, tau0 on the control users' D
        Combine  tau(x) = g(x)·tau0(x) + (1 - g(x))·tau1(x)

    where g is the propensity of *treatment*. Our pilot is randomised at a known
    0.5, so g is a constant and needs no model — with observational data it would
    itself have to be estimated, and that is called out as a limitation.

    Why this is lower variance: stage 2 fits a model *directly to an effect-shaped
    target* and can be regularised toward zero, whereas the T-learner has no way
    to regularise the difference — only its two halves, independently.

    Reference: Künzel, Sekhon, Bickel & Yu (2019), PNAS, "Metalearners for
    estimating heterogeneous treatment effects using machine learning".
    """

    pipeline: FeaturePipeline
    treatment_propensity: float = 0.5
    mu0: lgb.LGBMClassifier | None = None
    mu1: lgb.LGBMClassifier | None = None
    tau0: lgb.LGBMRegressor | None = None
    tau1: lgb.LGBMRegressor | None = None

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame, seed: int) -> "XLearner":
        tr_t, tr_c = train[train.treated == 1], train[train.treated == 0]
        va_t, va_c = valid[valid.treated == 1], valid[valid.treated == 0]
        if min(len(tr_t), len(tr_c)) < 500:
            raise ValueError(f"arms too small to fit an X-learner: {len(tr_t)}/{len(tr_c)}")

        # Stage 1 — outcome models per arm.
        self.mu1 = _fit_one(
            self.pipeline.transform(tr_t), tr_t["converted"].to_numpy(),
            self.pipeline.transform(va_t), va_t["converted"].to_numpy(),
            seed + 11, params=UPLIFT_ARM_PARAMS,
        )
        self.mu0 = _fit_one(
            self.pipeline.transform(tr_c), tr_c["converted"].to_numpy(),
            self.pipeline.transform(va_c), va_c["converted"].to_numpy(),
            seed + 12, params=UPLIFT_ARM_PARAMS,
        )

        # Stage 2 — impute effects with the opposite arm's model, then regress.
        d_treated = tr_t["converted"].to_numpy() - self.mu0.predict_proba(
            self.pipeline.transform(tr_t)
        )[:, 1]
        d_control = self.mu1.predict_proba(
            self.pipeline.transform(tr_c)
        )[:, 1] - tr_c["converted"].to_numpy()

        d_valid_treated = va_t["converted"].to_numpy() - self.mu0.predict_proba(
            self.pipeline.transform(va_t)
        )[:, 1]
        d_valid_control = self.mu1.predict_proba(
            self.pipeline.transform(va_c)
        )[:, 1] - va_c["converted"].to_numpy()

        self.tau1 = _fit_regressor(
            self.pipeline.transform(tr_t), d_treated,
            self.pipeline.transform(va_t), d_valid_treated, seed + 13,
        )
        self.tau0 = _fit_regressor(
            self.pipeline.transform(tr_c), d_control,
            self.pipeline.transform(va_c), d_valid_control, seed + 14,
        )
        return self

    def predict_uplift(self, df: pd.DataFrame) -> np.ndarray:
        assert self.tau0 is not None and self.tau1 is not None
        X = self.pipeline.transform(df)
        g = self.treatment_propensity
        return g * self.tau0.predict(X) + (1.0 - g) * self.tau1.predict(X)

    def predict_proba_treated(self, df: pd.DataFrame) -> np.ndarray:
        assert self.mu1 is not None
        return self.mu1.predict_proba(self.pipeline.transform(df))[:, 1]

    def predict_proba_control(self, df: pd.DataFrame) -> np.ndarray:
        assert self.mu0 is not None
        return self.mu0.predict_proba(self.pipeline.transform(df))[:, 1]

    @property
    def feature_importance(self) -> dict[str, float]:
        assert self.tau0 is not None and self.tau1 is not None
        imp = (
            self.tau0.feature_importances_.astype(float)
            + self.tau1.feature_importances_.astype(float)
        ) / 2
        return dict(sorted(zip(self.pipeline.columns, imp), key=lambda kv: -kv[1]))
