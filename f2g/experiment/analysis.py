"""Experiment analysis that stays valid when someone looks at it every day.

The textbook design is fixed-horizon: compute a sample size, wait, test once.
That design does not survive contact with a growth team. Someone will open the
dashboard on day three, and if a decision follows from what they see, the
reported p-value is meaningless — repeated testing on accumulating data inflates
the false-positive rate far past the nominal alpha.

So this module reports both:

* the **fixed-horizon** interval, which sets the expected duration and is what a
  reviewer asks for; and
* an **always-valid confidence sequence**, which may be read at any time, any
  number of times, without inflating error.

There is also an ethical reason specific to this experiment. One arm may be
harming users through the sleeping-dog effect. Being contractually unable to
stop early is not a neutral property, so the stopping rules below check for harm
*before* they check for success.

Method: an asymptotic normal-mixture confidence sequence (Howard, Ramdas,
McAuliffe & Sekhon, 2021, "Time-uniform, nonparametric, nonasymptotic confidence
sequences"). The fixed-horizon critical value is replaced by a time-uniform one
that grows slowly with the number of observations. Coverage is verified by
simulation in `tests/test_experiment.py` rather than asserted here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
from scipy import stats


@dataclass
class ArmStats:
    arm: str
    n: int
    conversions: int
    rate: float
    retained: int = 0
    converted_with_retention_data: int = 0
    retention_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Comparison:
    treatment: str
    control: str
    absolute_lift: float
    relative_lift: float
    fixed_ci: tuple[float, float]
    sequential_ci: tuple[float, float]
    fixed_p_value: float
    n_treatment: int
    n_control: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fixed_ci"] = list(self.fixed_ci)
        d["sequential_ci"] = list(self.sequential_ci)
        return d


def arm_stats(arm: str, n: int, conversions: int, retained: int = 0,
              converted_with_retention_data: int = 0) -> ArmStats:
    return ArmStats(
        arm=arm, n=n, conversions=conversions,
        rate=conversions / n if n else 0.0,
        retained=retained,
        converted_with_retention_data=converted_with_retention_data,
        retention_rate=(
            retained / converted_with_retention_data if converted_with_retention_data else 0.0
        ),
    )


def _pooled_se(p1: float, n1: int, p0: float, n0: int) -> float:
    if n1 == 0 or n0 == 0:
        return float("inf")
    return math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)


def sequential_z(n: int, alpha: float = 0.05, rho: float = 0.05) -> float:
    """Time-uniform critical value at sample size `n`.

    Replaces the fixed 1.96. It grows like sqrt(log n), which is the price of
    being allowed to look whenever you like. `rho` tunes where the sequence is
    tightest — smaller values favour later sample sizes.
    """
    if n <= 1:
        return float("inf")
    nr = n * rho**2
    return math.sqrt((2 * (nr + 1) / nr) * math.log(math.sqrt(nr + 1) / alpha))


def compare(
    treatment: ArmStats, control: ArmStats, *, alpha: float = 0.05, rho: float = 0.05
) -> Comparison:
    se = _pooled_se(treatment.rate, treatment.n, control.rate, control.n)
    diff = treatment.rate - control.rate

    if not math.isfinite(se) or se == 0:
        wide = (float("-inf"), float("inf"))
        return Comparison(treatment.arm, control.arm, diff, 0.0, wide, wide, 1.0,
                          treatment.n, control.n)

    z_fixed = stats.norm.ppf(1 - alpha / 2)
    z_seq = sequential_z(treatment.n + control.n, alpha, rho)
    p_value = 2 * (1 - stats.norm.cdf(abs(diff / se)))

    return Comparison(
        treatment=treatment.arm,
        control=control.arm,
        absolute_lift=diff,
        relative_lift=(diff / control.rate) if control.rate else 0.0,
        fixed_ci=(diff - z_fixed * se, diff + z_fixed * se),
        sequential_ci=(diff - z_seq * se, diff + z_seq * se),
        fixed_p_value=float(p_value),
        n_treatment=treatment.n,
        n_control=control.n,
    )


def sample_size(
    baseline_rate: float, mde_relative: float, *, alpha: float = 0.05, power: float = 0.80
) -> dict[str, Any]:
    """Fixed-horizon sample size per arm for a two-proportion test."""
    p0 = baseline_rate
    p1 = baseline_rate * (1 + mde_relative)
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    p_bar = (p0 + p1) / 2
    numerator = (
        z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    ) ** 2
    n = numerator / ((p1 - p0) ** 2)
    per_arm = int(math.ceil(n))
    return {
        "baseline_rate": p0,
        "target_rate": p1,
        "mde_relative": mde_relative,
        "mde_absolute": p1 - p0,
        "alpha": alpha,
        "power": power,
        "n_per_arm_fixed": per_arm,
        # Always-valid inference costs roughly a fifth more sample for the same
        # power. Stated up front rather than discovered mid-test.
        "n_per_arm_sequential": int(math.ceil(per_arm * 1.2)),
        "sequential_premium": 0.20,
    }


class Verdict:
    CONTINUE = "continue"
    SHIP = "ship"
    STOP_FOR_HARM = "stop_for_harm"
    STOP_FOR_FUTILITY = "stop_for_futility"


def stopping_verdict(
    conversion: Comparison,
    retention: Comparison,
    *,
    guardrail_margin: float = 0.03,
    horizon_reached: bool = False,
) -> dict[str, Any]:
    """Apply the pre-declared stopping rules, harm first.

    Order matters and is deliberate. Checking for success first would let a
    conversion win mask a retention breach for as long as the win holds, which
    is precisely the failure mode the guardrail exists to catch.
    """
    # 1. Harm. The guardrail is retention among converters; a sequential upper
    #    bound below the negative margin means we are confident it is worse.
    if retention.sequential_ci[1] < -guardrail_margin:
        return {
            "verdict": Verdict.STOP_FOR_HARM,
            "rule": "retention guardrail breached",
            "detail": (
                f"sequential upper bound on retention difference "
                f"{retention.sequential_ci[1]:+.4f} is below the "
                f"-{guardrail_margin:.3f} non-inferiority margin"
            ),
        }

    # 2. Success. Conversion must have separated AND retention must be
    #    non-inferior. Both, not either.
    if conversion.sequential_ci[0] > 0 and retention.sequential_ci[0] > -guardrail_margin:
        return {
            "verdict": Verdict.SHIP,
            "rule": "conversion lift established with retention non-inferior",
            "detail": (
                f"conversion sequential lower bound {conversion.sequential_ci[0]:+.4f} > 0; "
                f"retention lower bound {retention.sequential_ci[0]:+.4f} clears the margin"
            ),
        }

    # 3. Futility, only at the planned horizon.
    if horizon_reached:
        return {
            "verdict": Verdict.STOP_FOR_FUTILITY,
            "rule": "planned horizon reached without separation",
            "detail": (
                f"conversion sequential CI "
                f"[{conversion.sequential_ci[0]:+.4f}, {conversion.sequential_ci[1]:+.4f}] "
                "still contains zero"
            ),
        }

    return {
        "verdict": Verdict.CONTINUE,
        "rule": "no stopping condition met",
        "detail": (
            f"conversion sequential CI "
            f"[{conversion.sequential_ci[0]:+.4f}, {conversion.sequential_ci[1]:+.4f}]"
        ),
    }


def false_positive_simulation(
    n_looks: int = 200, n_per_look: int = 60, true_rate: float = 0.15,
    trials: int = 400, alpha: float = 0.05, seed: int = 0,
) -> dict[str, float]:
    """Simulate a null experiment read repeatedly, both ways.

    This is the evidence for the design choice rather than an appeal to
    authority: under no true effect, how often does each method declare a
    winner when someone checks the dashboard `n_looks` times?
    """
    rng = np.random.default_rng(seed)
    fixed_false, seq_false = 0, 0

    for _ in range(trials):
        na = nb = ca = cb = 0
        fixed_hit = seq_hit = False
        for _ in range(n_looks):
            ca += int(rng.binomial(n_per_look, true_rate))
            cb += int(rng.binomial(n_per_look, true_rate))
            na += n_per_look
            nb += n_per_look
            a = arm_stats("a", na, ca)
            b = arm_stats("b", nb, cb)
            cmp_ = compare(b, a, alpha=alpha)
            if not fixed_hit and cmp_.fixed_p_value < alpha:
                fixed_hit = True
            if not seq_hit and (cmp_.sequential_ci[0] > 0 or cmp_.sequential_ci[1] < 0):
                seq_hit = True
            if fixed_hit and seq_hit:
                break
        fixed_false += fixed_hit
        seq_false += seq_hit

    return {
        "trials": trials,
        "looks_per_trial": n_looks,
        "alpha": alpha,
        "fixed_horizon_false_positive_rate": fixed_false / trials,
        "sequential_false_positive_rate": seq_false / trials,
    }
