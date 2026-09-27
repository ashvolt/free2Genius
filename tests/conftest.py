"""Shared fixtures.

Cohort loading and ledger building are both `lru_cache`d for serving
performance. That is correct in production and a trap in tests: a test that
regenerates data reads the previously cached population unless the caches are
cleared. The autouse fixture below removes the trap rather than relying on every
test author remembering it.
"""
from __future__ import annotations

import pytest

from f2g import config
from f2g.data import accounts


@pytest.fixture(autouse=True)
def _clear_caches():
    accounts.repository.cache_clear()
    accounts.build_ledger.cache_clear()
    yield
    accounts.repository.cache_clear()
    accounts.build_ledger.cache_clear()


@pytest.fixture(scope="session")
def pilot():
    import pandas as pd

    path = config.DATA_DIR / "pilot_users.csv"
    if not path.exists():
        pytest.skip("run `python -m f2g.data.generate` first")
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def small_cohort():
    """A fast, self-contained cohort for tests that do not need 60k users."""
    from f2g.data.generate import generate_cohort

    return generate_cohort(6000, seed=1234, cohort="pilot", treatment_share=0.5, id_prefix="t")
