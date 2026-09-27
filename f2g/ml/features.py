"""The single feature pipeline, shared by training and serving.

There is exactly one of these on purpose. Training/serving skew — a column added
in a notebook, a category encoded differently at inference — is the most common
way a model that scored well offline behaves badly in production. The only
defence that works is having one code path that both sides call.

Two invariants this module enforces:

1. **Column order is recorded.** LightGBM consumes positional arrays. If the
   serving frame presents the same columns in a different order, every
   prediction is quietly wrong, with no error. So the ordered list is part of
   the model bundle and is checked on load.
2. **No label, treatment or oracle column can enter.** Not by convention: the
   groups are declared in `f2g.data.schema` and the exclusion is asserted by a
   test. Leakage from `p0` or `true_tau` would produce a spectacular AUC and a
   worthless model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from f2g.data.schema import (
    ACQUISITION_CHANNELS,
    AGE_BANDS,
    BINARY_FEATURES,
    CATEGORICAL_FEATURES,
    FEATURES,
    INCOME_BANDS,
    LABEL_COLUMNS,
    NUMERIC_FEATURES,
    ORACLE_COLUMNS,
    PLATFORMS,
)

# Fixed category levels. Declared rather than learned from data, so an unseen
# level at serving time becomes NaN (which LightGBM handles natively) instead of
# shifting every subsequent code and corrupting the whole row.
CATEGORY_LEVELS: dict[str, list[str]] = {
    "income_band": INCOME_BANDS,
    "age_band": AGE_BANDS,
    "platform": PLATFORMS,
    "acquisition_channel": ACQUISITION_CHANNELS,
}

FORBIDDEN_COLUMNS = set(LABEL_COLUMNS) | set(ORACLE_COLUMNS) | {"user_id", "cohort"}


class FeatureError(RuntimeError):
    """Raised when a frame cannot be safely turned into model input."""


@dataclass
class FeaturePipeline:
    """Deterministic, stateless-by-design transform to model input.

    It carries no learned parameters — only the ordered column list, which is
    what makes the training/serving contract checkable.
    """

    feature_names: list[str] = field(default_factory=lambda: list(FEATURES))
    treatment_column: str | None = None

    def __post_init__(self) -> None:
        leaked = FORBIDDEN_COLUMNS & set(self.feature_names)
        # The treatment column is a legitimate feature for an S-learner, and
        # only for an S-learner, so it is admitted explicitly and never by
        # accident.
        if self.treatment_column:
            leaked.discard(self.treatment_column)
        if leaked:
            raise FeatureError(
                f"refusing to build a pipeline containing label/oracle columns: {sorted(leaked)}"
            )

    @property
    def columns(self) -> list[str]:
        cols = list(self.feature_names)
        if self.treatment_column and self.treatment_column not in cols:
            cols.append(self.treatment_column)
        return cols

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in self.columns if c not in df.columns]
        if missing:
            raise FeatureError(f"frame is missing required feature columns: {missing}")

        out = df.loc[:, self.columns].copy()

        for col in CATEGORICAL_FEATURES:
            if col in out.columns:
                out[col] = pd.Categorical(out[col], categories=CATEGORY_LEVELS[col])

        for col in NUMERIC_FEATURES + BINARY_FEATURES:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        if self.treatment_column and self.treatment_column in out.columns:
            out[self.treatment_column] = pd.to_numeric(out[self.treatment_column], errors="coerce")

        return out

    def validate_against(self, recorded: list[str]) -> None:
        """Fail loudly when a loaded model's columns disagree with this pipeline.

        Called at model load. A mismatch here is the difference between an
        obvious startup failure and months of silently wrong predictions.
        """
        if list(recorded) != self.columns:
            only_recorded = [c for c in recorded if c not in self.columns]
            only_current = [c for c in self.columns if c not in recorded]
            raise FeatureError(
                "feature contract mismatch between saved model and current pipeline.\n"
                f"  in model only  : {only_recorded}\n"
                f"  in pipeline only: {only_current}\n"
                f"  order changed  : {only_recorded == [] and only_current == []}"
            )


def categorical_feature_names() -> list[str]:
    return [c for c in CATEGORICAL_FEATURES]
