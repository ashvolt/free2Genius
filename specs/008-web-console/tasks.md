# Tasks: Web Console

**Feature**: `008` · **Status**: Complete · **Verify**: `cd web && npm run typecheck && npm run build`

## Phase 1: Foundations
- [x] **T001** Vite + React + TypeScript, strict, with a dev proxy to the API
- [x] **T002** Design tokens — validated palette, dark declared under both scopes
- [x] **T003** Typed API client with a single error shape
- [x] **T004** Formatters distinguishing dollars, percentages and percentage points

## Phase 2: Shared components
- [x] **T005** Loading, Error, Empty, Badge, Stat, Card
- [x] **T006** `barPath` — rounded data-end, square baseline end
- [x] **T007** `BarsWithCI`, `IntervalPlot`, `CategoryBars`
- [x] **T008** Three-series cap enforced in code

## Phase 3: Targeting (US1)
- [x] **T009** Sortable, filterable, paginated cohort table
- [x] **T010** Suppression reasons visible per row
- [x] **T011** Policy summary tiles including the binding constraint
- [x] **T012** Suppression chart highlighting the value-fit gate

## Phase 4: Concierge (US2, US3)
- [x] **T013** Chip splitting, longest-match first
- [x] **T014** Evidence popover with the tool call and raw result
- [x] **T015** Unbacked figures rendered in the error style
- [x] **T016** Per-check guardrail badges
- [x] **T017** Degradation banner explaining the designed failure path
- [x] **T018** Chat panel with tool activity and per-turn verdicts
- [x] **T019** Provider selector so a reviewer can see both paths

## Phase 5: Experiment (US4)
- [x] **T020** Verdict banner styled by outcome
- [x] **T021** Conversion and retention by arm
- [x] **T022** Fixed vs always-valid intervals overlaid
- [x] **T023** Guardrail against its margin, drawn as a reference line
- [x] **T024** Cite the reproducible simulation behind the method choice

## Phase 6: Corrections from rendering
- [x] **T025** Capped chart width after viewBox scaling inflated every font by ~2.2x
- [x] **T026** Fixed label anchoring — spacing was computed then discarded
- [x] **T027** Gave the production estimator the prime colour slot
- [x] **T028** Capped the evidence popover height so badges stay in view

## Outcome

| Criterion | Target | Measured | |
|---|---|---|---|
| SC-001 figure traceable in ≤ 2 clicks | yes | 1 click | pass |
| SC-003 loading/empty/error states | all views | all views | pass |
| SC-005 bundle size | < 500 KB gz | 54.66 KB | pass |
| SC-006 legible in both themes | yes | verified by screenshot | pass |
