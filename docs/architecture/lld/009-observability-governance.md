# LLD 009 — Observability, Cost Control & AI Governance

**Domain**: E · **HLD**: [009](../hld/009-observability-governance.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `f2g/api/store.py` | `record_decision`, `record_generation`, `explain`, `generation_telemetry` |
| `f2g/api/telemetry.py` | `summarise` — aggregate agent operational metrics |
| `f2g/governance/model_card.py` | Generate `MODEL_CARD.md` from evaluation artifacts |
| `docs/governance/*.md` | Model card (generated), risk register, consent note |

## Signatures

```python
# store.py
def record_decision(record: dict) -> None      # user, cycle, scores, constraint, versions
def record_generation(generation_id: str, result: dict) -> None
def explain(user_id: str) -> dict              # assignments, decisions, generations, events
def generation_telemetry(limit: int = 1000) -> list[dict]

# telemetry.py
def summarise(rows: list[dict]) -> dict

# model_card.py
CARD_PATH: Path
class ArtifactsMissing(RuntimeError)
def render(model_report, policy_report, eval_report) -> str
def generate() -> str
```

## Telemetry output

```python
{
  "generations": int,
  "latency_s": {"p50", "p90", "p99", "mean"},
  "tokens": {"prompt_total", "completion_total", "completion_per_generation"},
  "providers": {name: count},
  "prompt_versions": {version: count},
  "repair_attempts": {"mean", "any"},
  "degradation": {"rate", "reasons": {reason_prefix: count}},
  "guardrails": {"block_rate", "failures_by_check", "block_rate_threshold": 0.15, "flagged": bool},
}
```

`prompt_versions` is what makes "did that prompt change help?" answerable after the fact, and it
is why `PROMPT_VERSION` is recorded on every generation rather than inferred from a deploy time.

Degradation reasons are truncated at the first `:` so `guardrail_block: <long span>` aggregates
to `guardrail_block` instead of producing one bucket per message.

## Model card generation

Inputs, all produced by the pipeline:

| Artifact | Supplies |
|---|---|
| `artifacts/reports/model_evaluation.json` | Discrimination, calibration, Qini, recovery, deciles, fingerprint, seed |
| `artifacts/reports/policy_report.json` | Selection counts, binding constraint, gate cost, fairness gaps |
| `artifacts/evals/latest.json` | Agent safety rates (optional; omitted if absent) |

The staleness test strips only the `**Generated**` date line before comparing, so everything
substantive must match:

```python
def strip_date(text):
    return [ln for ln in text.splitlines() if not ln.startswith("**Generated**")]
assert strip_date(generate()) == strip_date(CARD_PATH.read_text())
```

## Risk register structure

Each risk carries: severity, a **Control** (code path plus the test that exercises it) or an
explicit **acceptance**, and a **Residual** where one remains. A parsing test enforces the
shape:

```python
for section in register.split("\n## ")[…]:
    assert "**Control**" in section or "accepted" in section.lower()
```

That test caught a real gap — the register had no risk covering out-of-scope financial advice
even though `f2g/agent/scope.py` existed to control it. Added as R7a with the evidence that
motivated it: the evaluation gate failing at a 0.00 refusal rate.

## Cost accounting

Local inference has no per-token bill, so cost per nudge is approximated from wall-clock compute
rather than metered. Hosted providers report token cost. Both are surfaced on the same axis so
the comparison is honest rather than flattering to whichever is being defended.

## Tests that pin behaviour

| Test | Pins |
|---|---|
| `test_model_card_matches_current_evaluation_output` | The card cannot go stale |
| `test_model_card_names_its_limitations` | Required sections exist |
| `test_model_card_generation_fails_loudly_without_artifacts` | No half-built card |
| `test_every_risk_names_a_control_or_an_acceptance` | No hand-waved mitigations |
| `test_risk_register_links_controls_to_code` | Controls point at real files |
| `test_consent_note_covers_the_required_ground` | Purpose, basis, retention, rights |
| `test_governance_docs_state_synthetic_provenance` | Principle VIII |
| `test_telemetry_flags_a_high_block_rate` | The drift signal fires |
