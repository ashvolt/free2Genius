# LLD 008 — Web Console

**Domain**: D · **HLD**: [008](../hld/008-web-console.md) · **Status**: Implemented

## Module map

| Module | Responsibility |
|---|---|
| `web/src/lib/api.ts` | Typed client; `ApiError` carries the status |
| `web/src/lib/format.ts` | `usd`, `pct`, `pp`, decision and check labels |
| `web/src/styles.css` | Design tokens, light and dark |
| `web/src/components/common.tsx` | Loading, Error, Empty, Badge, Stat, Card |
| `web/src/components/Charts.tsx` | `BarsWithCI`, `IntervalPlot`, `CategoryBars` |
| `web/src/components/CohortView.tsx` | Table, filters, pagination, suppression chart |
| `web/src/components/NudgePreview.tsx` | Chip splitting, evidence popover, guardrail badges |
| `web/src/components/ChatPanel.tsx` | Turns, per-turn verdicts, suggestions |
| `web/src/components/ExperimentDashboard.tsx` | Arms, intervals, guardrail, verdict |

## Design tokens

```css
:root                                        { /* light */ }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) { /* OS dark, losable to a light stamp */ }
}
:root[data-theme="dark"]                     { /* explicit toggle, always wins */ }
```

The `:where()` keeps the media block at zero specificity so the explicit stamp beats it, and the
`:not([data-theme="light"])` guard lets a light stamp beat OS dark. Declared twice on purpose.

Series colours, validated on the all-pairs pairlist:

| Slot | Light | Dark |
|---|---|---|
| 1 | `#2a78d6` | `#3987e5` |
| 2 | `#eb6834` | `#d95926` |
| 3 | `#1baf7a` | `#199e70` |

Light CVD ΔE 9.2 / normal-vision ΔE 24.0 · dark CVD ΔE 9.4 / normal-vision ΔE 20.9 — both PASS.
Diverging pair for signed quantities: `--pos` blue ↔ `--neg` red with a neutral midpoint.

## Chart primitives

```ts
function barPath(x, y, w, h, r, up): string
// Rounded data-end, square baseline end. A rounded baseline would read as a
// bar floating above zero.

export function BarsWithCI({ data, format, yTitle, height })
export function IntervalPlot({ rows, format, xTitle, reference, referenceLabel,
                               margin, marginLabel, height })
export function CategoryBars({ data, format, highlight, height })
```

Hit targets are the full column slot, larger than the mark, so hovering is forgiving. Overlapping
markers carry a 2 px surface ring.

## Chip splitting

```ts
const sorted = [...evidence].sort((a, b) => b.rendered.length - a.rendered.length);
const pattern = new RegExp(`(${sorted.map(escapeRegExp).join("|")})`, "g");
message.split(pattern).map(part => ({ text: part, ev: evidence.find(e => e.rendered === part) }));
```

Longest-first ordering matters: with `$4.99` and `$4.99 each` both present, the shorter
alternative would otherwise win and leave a fragment.

## Data flow

```text
CohortView --onSelect--> App state (userId) --> NudgePreview + ChatPanel
                                            \-> tab switches to Concierge
```

`userId` and `provider` live in `App`; views are otherwise self-fetching, each owning its
loading and error state. Every effect carries a `live` flag so a late response from a previous
selection cannot overwrite the current one.

## Verified by rendering

Screenshots captured in both colour schemes via Playwright against the running dev server, at
1320 px and re-checked at phone width. That pass caught the two defects recorded in the HLD;
neither is visible to `tsc`.

## Build

| | |
|---|---|
| Bundle | 168.9 KB raw, **54.66 KB gzipped** (budget 500 KB) |
| CSS | 10.0 KB raw, 2.70 KB gzipped |
| Typecheck | `tsc --noEmit`, strict, `noUnusedLocals`, `noUnusedParameters` |
| Dev proxy | `/api → 127.0.0.1:8000`, so no environment-specific base URL is compiled in |
