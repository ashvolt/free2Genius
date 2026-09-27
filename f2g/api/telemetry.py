"""Aggregate agent telemetry — the operational view (feature 009).

The single most useful number here is `guardrail_block_rate` by check. A rising
block rate means the prompt, the model or the data moved, and it is visible days
before anyone notices the output getting worse.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

import numpy as np


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"generations": 0, "note": "no generations recorded yet"}

    latencies: list[float] = []
    prompt_tokens, completion_tokens = 0, 0
    providers: Counter[str] = Counter()
    prompt_versions: Counter[str] = Counter()
    repairs: list[int] = []
    degraded = 0
    degrade_reasons: Counter[str] = Counter()
    check_failures: Counter[str] = Counter()
    blocked = 0

    for row in rows:
        tel = json.loads(row.get("telemetry") or "{}")
        guards = json.loads(row.get("guardrails") or "{}")

        latencies.append(float(tel.get("latency_s", 0.0)))
        prompt_tokens += int(tel.get("prompt_tokens", 0))
        completion_tokens += int(tel.get("completion_tokens", 0))
        providers[tel.get("provider", "unknown")] += 1
        repairs.append(int(tel.get("repair_attempts", 0)))
        prompt_versions[row.get("prompt_version") or "unknown"] += 1

        if row.get("degraded"):
            degraded += 1
            reason = (row.get("degraded_reason") or "unknown").split(":")[0]
            degrade_reasons[reason] += 1

        for check, passed in (guards.get("checks") or {}).items():
            if not passed:
                check_failures[check] += 1
        if guards.get("blocked"):
            blocked += 1

    n = len(rows)
    lat = np.array(latencies, dtype=float)
    return {
        "generations": n,
        "latency_s": {
            "p50": float(np.percentile(lat, 50)),
            "p90": float(np.percentile(lat, 90)),
            "p99": float(np.percentile(lat, 99)),
            "mean": float(lat.mean()),
        },
        "tokens": {
            "prompt_total": prompt_tokens,
            "completion_total": completion_tokens,
            "completion_per_generation": round(completion_tokens / n, 1),
        },
        "providers": dict(providers),
        "prompt_versions": dict(prompt_versions),
        "repair_attempts": {
            "mean": round(float(np.mean(repairs)), 3),
            "any": int(sum(1 for r in repairs if r > 0)),
        },
        "degradation": {
            "rate": round(degraded / n, 4),
            "reasons": dict(degrade_reasons),
        },
        "guardrails": {
            "block_rate": round(blocked / n, 4),
            "failures_by_check": dict(check_failures),
            # A block rate above this is treated as a prompt-quality regression
            # rather than background noise (feature 009, FR-009).
            "block_rate_threshold": 0.15,
            "flagged": (blocked / n) > 0.15,
        },
    }
