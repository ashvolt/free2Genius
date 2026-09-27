"""Shared fixtures.

The first thing this module does is redirect the event store to a temporary
database. Without it the suite writes into `data/events.db` — the same file the
demo and the console use — which both pollutes the demo and makes the tests
order-dependent: a test asserting that an event is newly recorded passes once
and fails on every subsequent run because the idempotency key is already there.
That is exactly how it was caught.

The environment variable has to be set before `f2g.config` is imported, since
paths are resolved at import time. conftest is imported before any test module,
so this is the right place for it.


Cohort loading and ledger building are both `lru_cache`d for serving
performance. That is correct in production and a trap in tests: a test that
regenerates data reads the previously cached population unless the caches are
cleared. The autouse fixture below removes the trap rather than relying on every
test author remembering it.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / f"f2g-test-{uuid.uuid4().hex}.db"
os.environ["F2G_DB_PATH"] = str(_TEST_DB)

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


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(_TEST_DB) + suffix)
        if candidate.exists():
            candidate.unlink()


@pytest.fixture
def unique_key() -> str:
    """A fresh idempotency key, so a test never collides with its own history."""
    return f"test-{uuid.uuid4().hex[:12]}"


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
