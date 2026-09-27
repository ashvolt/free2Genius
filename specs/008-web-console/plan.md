# Implementation Plan: Web Console

**Feature**: `008` · **Date**: 2026-09-27 · **Spec**: [spec.md](spec.md) · **Status**: Implemented

See the architecture documents for the full design:
**[HLD](../../docs/architecture/hld/008-web-console.md)** · **[LLD](../../docs/architecture/lld/008-web-console.md)**

## Summary

A three-view single-page console that renders the machinery rather than only the output:
clickable evidence chips, per-check guardrail badges, visible degradation, and an experiment
dashboard that overlays both intervals.

## Technical Context

**Language/Version**: TypeScript 5.6, React 18, Vite 5 · **Dependencies**: react, react-dom only
**Testing**: `tsc --noEmit` strict; visual verification by Playwright screenshot in both schemes
**Performance**: 54.66 KB gzipped against a 500 KB budget
**Constraints**: no SSR, no authentication, desktop-first and phone-legible

## Constitution Check

| Principle | Satisfied by |
|---|---|
| VIII. Synthetic data stated | A banner on every view, not only a landing page |
| I. Evidence over persuasion | Evidence chips make grounding inspectable rather than asserted |
| V. Counter-metric visible | Retention charted beside conversion, with its margin drawn |

**Result**: Pass.

## Technical approach

Charts are hand-built SVG. The colour rules and the three-series cap are enforced in code, every
mark carries a tooltip and direct labels, and the bundle stays small. The validated palette is
expressed as CSS custom properties with dark values declared under both the OS media query and
an explicit theme stamp.

Verification is by rendering and looking — a typecheck cannot see a label collision.

## Complexity Tracking

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| No chart library | Palette rules and series caps must be enforced, not configured | A library's defaults would have to be overridden per chart and would still permit a fourth series |
| Hand-written API types | The console should be readable on its own | Codegen adds a build step; the OpenAPI schema remains the contract of record |
| Label de-collision helper | Direct labels replace the legend, so overlap destroys identity | Leaving overlaps makes converging series unreadable exactly where it matters |
