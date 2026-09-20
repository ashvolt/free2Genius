"""Central configuration and path handling.

Every path is derived from the repository root so the package behaves the same
whether it is driven from the CLI, from pytest, or from the FastAPI process.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("F2G_DATA_DIR", ROOT / "data"))
ARTIFACT_DIR = Path(os.environ.get("F2G_ARTIFACT_DIR", ROOT / "artifacts"))
DB_PATH = Path(os.environ.get("F2G_DB_PATH", DATA_DIR / "events.db"))

# --- Synthetic data -------------------------------------------------------
N_USERS = int(os.environ.get("F2G_N_USERS", 60_000))
RANDOM_SEED = int(os.environ.get("F2G_SEED", 20260920))

# Share of the historical pilot population that received the nudge. The pilot
# was randomised, which is what makes the uplift target identifiable.
PILOT_TREATMENT_SHARE = 0.5

# --- Modelling ------------------------------------------------------------
TEST_SIZE = 0.25
VALID_SIZE = 0.15  # carved out of the training portion for early stopping

# --- Targeting policy -----------------------------------------------------
# Users are nudged when predicted uplift clears this threshold. The default is
# calibrated in `f2g.ml.targeting` against the contact budget below.
DEFAULT_CONTACT_BUDGET = 0.30  # nudge at most 30% of eligible free users

# --- Agent ----------------------------------------------------------------
AGENT_MODEL = os.environ.get("F2G_AGENT_MODEL", "claude-opus-5")
JUDGE_MODEL = os.environ.get("F2G_JUDGE_MODEL", "claude-opus-5")
AGENT_MAX_TOKENS = int(os.environ.get("F2G_AGENT_MAX_TOKENS", 4096))
AGENT_MAX_TOOL_ROUNDS = int(os.environ.get("F2G_AGENT_MAX_TOOL_ROUNDS", 6))


def has_anthropic_key() -> bool:
    """True when a live Claude call is possible.

    The whole product degrades to a deterministic template engine without a
    key, so the demo, the tests and CI all run offline.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
