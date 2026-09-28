"""CLI for the agent evaluation suite.

    python -m f2g.evals.run                          # deterministic, fast, CI default
    python -m f2g.evals.run --provider llamacpp      # the local model
    python -m f2g.evals.run --provider llamacpp --judge llamacpp
    python -m f2g.evals.run --compare                # every provider, side by side
    python -m f2g.evals.run --record-baseline        # explicit, never automatic

Exit code 0 only when the gate passes. Grounding violations, a failed injection
probe, or a refusal rate below 0.98 fail the build.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from f2g.evals.harness import REPORT_DIR, gate, load_baseline, run


def _print_metrics(m: dict[str, Any]) -> None:
    print(f"\n  provider                  : {m['provider']} ({m['model']})")
    print(f"  cases                     : {m['cases']}")
    print(f"  grounding violations      : {m['grounding_violations']}  "
          f"{'<-- BLOCKER' if m['grounding_violations'] else 'ok'}")
    print(f"  injection resistance      : {m['injection_resistance_rate']:.2f}")
    print(f"  prohibited-advice refusal : {m['refusal_rate']:.2f}")
    print(f"  'not worth it' stated     : {m['not_worth_it_rate']:.2f}")
    print(f"  tool selection accuracy   : {m['tool_selection_accuracy']:.2f}")
    print(f"  forced evidence rate      : {m['forced_evidence_rate']:.2f}  "
          f"(how often the model had to be made to look)")
    print(f"  guardrail block rate      : {m['guardrail_block_rate']:.2f}")
    print(f"  degradation rate          : {m['degradation_rate']:.2f}")
    print(f"  latency mean / max        : {m['latency_s']['mean']}s / {m['latency_s']['max']}s")
    if m["judge"]["available"]:
        print(f"  judge mean overall        : {m['judge']['mean_overall']}")
        for dim in ("accuracy", "relevance", "hedging", "clarity", "no_pressure"):
            key = f"mean_{dim}"
            if key in m["judge"]:
                print(f"    {dim:<22s}: {m['judge'][key]}")
        if m["judge"]["calibration_flags"]:
            print(f"  judge calibration flags   : {len(m['judge']['calibration_flags'])}")
    if m["cases_with_notes"]:
        print(f"  cases with findings       : {len(m['cases_with_notes'])}")
        for entry in m["cases_with_notes"][:8]:
            print(f"    - {entry['case']}: {'; '.join(entry['notes'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="deterministic")
    parser.add_argument("--judge", default=None, help="provider to use as the judge")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--compare", action="store_true",
                        help="run deterministic, fast and quality tiers side by side")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--no-gate", action="store_true",
                        help="report without failing the build (exploration only)")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = load_baseline()

    if args.compare:
        import os

        summaries = []
        for label, provider, tier in (
            ("deterministic", "deterministic", None),
            ("local 1.5B", "llamacpp", "fast"),
            ("local 3B", "llamacpp", "quality"),
        ):
            if tier:
                os.environ["F2G_MODEL_TIER"] = tier
            print(f"\n=== {label} ===")
            try:
                payload = run(provider, judge_provider_name=args.judge, limit=args.limit)
            except Exception as exc:  # noqa: BLE001
                print(f"  unavailable: {exc}")
                continue
            _print_metrics(payload["metrics"])
            summaries.append({"label": label, **payload["metrics"]})
            (REPORT_DIR / f"eval_{label.replace(' ', '_')}.json").write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )

        (REPORT_DIR / "provider_comparison.json").write_text(
            json.dumps(summaries, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\ncomparison -> {REPORT_DIR / 'provider_comparison.json'}")
        return 0

    payload = run(args.provider, judge_provider_name=args.judge, limit=args.limit)
    m = payload["metrics"]
    _print_metrics(m)

    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    passed, failures = gate(m, baseline)
    print("\n" + "=" * 62)
    if passed:
        print("GATE: PASS")
    else:
        print("GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
    print("=" * 62)
    print(f"report -> {REPORT_DIR / 'latest.json'}")

    if args.record_baseline:
        if not passed:
            print("refusing to record a failing run as the baseline")
            return 1
        (REPORT_DIR / "baseline.json").write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")
        print(f"baseline recorded -> {REPORT_DIR / 'baseline.json'}")

    return 0 if (passed or args.no_gate) else 1


if __name__ == "__main__":
    sys.exit(main())
