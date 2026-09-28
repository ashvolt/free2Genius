"""Model persistence with the metadata needed to serve and audit a model.

A pickled estimator on its own is not a shippable artifact. To serve it you need
the exact ordered feature list; to audit it you need to know which data, which
seed, which hyperparameters and which library versions produced it; to compare
it you need the metrics it was accepted on.

So a bundle is the estimator *plus* that record, and loading one validates the
feature contract before it can be used (see `FeaturePipeline.validate_against`).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from f2g import config

MODEL_DIR = config.ARTIFACT_DIR / "models"


def data_fingerprint(df: pd.DataFrame) -> str:
    """A short, stable hash of the training frame.

    Cheap provenance: two bundles with the same fingerprint were trained on the
    same data, so a metric difference is attributable to the model rather than
    to the dataset having quietly moved underneath it.
    """
    h = hashlib.sha256()
    h.update(str(df.shape).encode())
    h.update(",".join(map(str, df.columns)).encode())
    # Sampling keeps this fast on large frames while still catching content drift.
    sample = df.head(500).to_csv(index=False).encode()
    h.update(sample)
    return h.hexdigest()[:16]


@dataclass
class BundleMeta:
    name: str
    kind: str  # "propensity" | "uplift_s" | "uplift_t"
    feature_names: list[str]
    params: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    data_fingerprint: str = ""
    n_train: int = 0
    seed: int = config.RANDOM_SEED
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    versions: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def _library_versions() -> dict[str, str]:
    import lightgbm
    import numpy
    import sklearn

    return {
        "python": platform.python_version(),
        "lightgbm": lightgbm.__version__,
        "numpy": numpy.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
    }


@dataclass
class ModelBundle:
    meta: BundleMeta
    estimator: Any  # PropensityModel | SLearner | TLearner

    def save(self, directory: Path | None = None) -> Path:
        directory = directory or MODEL_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.meta.versions = self.meta.versions or _library_versions()
        path = directory / f"{self.meta.name}.joblib"
        joblib.dump({"meta": asdict(self.meta), "estimator": self.estimator}, path)
        # A sidecar JSON so metadata is greppable and diffable without loading
        # a pickle — useful in review, and in CI where you want the metrics
        # without importing the model.
        (directory / f"{self.meta.name}.meta.json").write_text(
            json.dumps(asdict(self.meta), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, name: str, directory: Path | None = None) -> "ModelBundle":
        directory = directory or MODEL_DIR
        path = directory / f"{name}.joblib"
        if not path.exists():
            raise FileNotFoundError(
                f"no model bundle at {path}. Train models first: `python -m f2g.ml.train`"
            )
        payload = joblib.load(path)
        return cls(meta=BundleMeta(**payload["meta"]), estimator=payload["estimator"])


def list_bundles(directory: Path | None = None) -> list[str]:
    directory = directory or MODEL_DIR
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.joblib"))
