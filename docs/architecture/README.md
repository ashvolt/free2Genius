# Architecture documentation

Start with **[system-context.md](system-context.md)** — the whole system on one page
(C4 Level 1 and 2, the end-to-end decision sequence, the trust boundary, the CI gates).

Then, per feature:

- `hld/NNN-*.md` — **High-Level Design**: responsibilities, component decomposition,
  interface contracts, data flow, failure modes, and the decisions that shaped it.
- `lld/NNN-*.md` — **Low-Level Design**: module layout, function signatures, data shapes,
  algorithms with their maths, error paths, and the tests that pin each behaviour.

Decisions with rejected alternatives live in [../adr/](../adr/). Governance artifacts —
model card, risk register, fairness audit — live in [../governance/](../governance/).

Diagrams are Mermaid so they render directly on GitHub and stay reviewable in diffs; a
picture that cannot be diffed rots.
