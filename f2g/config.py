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
# Users are nudged when predicted uplift clears this threshold, subject to the
# contact budget below.
#
# 0.20 is a measured choice, not a round number. The budget sweep in
# `artifacts/reports/model_evaluation.md` shows the advantage of uplift targeting
# over propensity targeting is strongly reach-dependent on this population:
#
#     budget   uplift advantage over propensity (incremental conversions)
#       5%       +4.6 pp per contact
#      15%       +1.7 pp
#      20%       +1.1 pp
#      30%       +0.4 pp
#      50%       -0.3 pp   <- uplift targeting stops paying for itself
#
# Past roughly 30% reach the two rankings converge, because a large budget has to
# include most of the movable population anyway. Below 20% the uplift model is
# clearly worth its complexity. 20% is where the advantage is still substantial
# while contacting enough users for the experiment to reach power in reasonable
# time — the trade is documented in specs/003 rather than left implicit.
DEFAULT_CONTACT_BUDGET = 0.20

# --- LLM runtime ----------------------------------------------------------
# Local open-weights inference is the default and the only configuration needed
# to run this project. See docs/adr/ADR-001-local-first-inference.md.
MODEL_DIR = Path(os.environ.get("F2G_MODEL_DIR", ROOT / "models"))

MODEL_TIERS = {
    "fast": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "quality": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
}
MODEL_TIER = os.environ.get("F2G_MODEL_TIER", "fast")

# One of: llamacpp | openai | deterministic | anthropic
LLM_PROVIDER = os.environ.get("F2G_LLM_PROVIDER", "llamacpp")

OPENAI_COMPAT_BASE_URL = os.environ.get("F2G_OPENAI_BASE_URL", "http://localhost:8000/v1")
OPENAI_COMPAT_MODEL = os.environ.get("F2G_OPENAI_MODEL", "Qwen/Qwen2.5-3B-Instruct")

LLM_N_CTX = int(os.environ.get("F2G_LLM_N_CTX", 8192))
LLM_N_THREADS = int(os.environ.get("F2G_LLM_N_THREADS", 4))
LLM_TIMEOUT_S = float(os.environ.get("F2G_LLM_TIMEOUT_S", 90))
LLM_SEED = int(os.environ.get("F2G_LLM_SEED", 7))

# --- Agent ----------------------------------------------------------------
# The prompt asks for at most six sentences; a large budget invites a small
# model to keep going after it has finished saying anything useful.
AGENT_MAX_TOKENS = int(os.environ.get("F2G_AGENT_MAX_TOKENS", 380))
AGENT_MAX_TOOL_ROUNDS = int(os.environ.get("F2G_AGENT_MAX_TOOL_ROUNDS", 7))
MAX_REPAIR_ATTEMPTS = int(os.environ.get("F2G_MAX_REPAIR_ATTEMPTS", 2))

# Cloud escalation, opt-in only. Disabled by default: enabling it sends user
# financial data outside our trust boundary, so it must be a deliberate act.
ANTHROPIC_MODEL = os.environ.get("F2G_ANTHROPIC_MODEL", "claude-opus-5")


def model_path(tier: str | None = None) -> Path:
    tier = tier or MODEL_TIER
    if tier not in MODEL_TIERS:
        raise ValueError(f"unknown model tier {tier!r}; expected one of {sorted(MODEL_TIERS)}")
    return MODEL_DIR / MODEL_TIERS[tier]


def has_anthropic_key() -> bool:
    """Whether a hosted-model call is possible at all.

    Never consulted to pick a default. The default provider is local, with or
    without a key present.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
