import { useEffect, useMemo, useState } from "react";
import { api, type CohortResponse, type CohortRow } from "../lib/api";
import { compactInt, DECISION_LABEL, decisionTone, pct, pp, usd } from "../lib/format";
import { Badge, Card, ErrorState, Empty, Loading, Stat } from "./common";
import { CategoryBars } from "./Charts";

const PAGE = 40;

const SORTS = [
  { key: "uplift", label: "Uplift" },
  { key: "propensity", label: "Propensity" },
  { key: "estimated_saving_90d", label: "Est. saving" },
] as const;

const DECISIONS = ["", "selected", "value_fit", "negative_uplift", "budget"];

export function CohortView({ onSelect, selected }: {
  onSelect: (userId: string) => void;
  selected: string | null;
}) {
  const [data, setData] = useState<CohortResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [sortBy, setSortBy] = useState<string>("uplift");
  const [decision, setDecision] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .cohort({ limit: PAGE, offset, sort_by: sortBy, decision: decision || undefined })
      .then((d) => live && (setData(d), setError(null)))
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [offset, sortBy, decision]);

  const suppression = useMemo(() => {
    if (!data) return [];
    const s = data.summary;
    return [
      { label: "selected", value: s.selected },
      ...Object.entries(s.suppressed_by_reason).map(([k, v]) => ({
        label: k.replace(/_/g, " "),
        value: v,
      })),
    ];
  }, [data]);

  if (error) {
    return (
      <ErrorState
        error={error}
        hint="Is the API running? `uvicorn f2g.api.main:app` — and models must be trained first."
      />
    );
  }
  if (!data && loading) return <Loading what="the cohort" />;
  if (!data) return <Empty title="No cohort data" />;

  const s = data.summary;

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid stats">
        <Stat label="Candidates" value={compactInt(s.candidates)} foot="live free users" />
        <Stat
          label="Selected for contact"
          value={compactInt(s.selected)}
          foot={`${pct(s.selected / s.candidates)} of the cohort`}
        />
        <Stat
          label="Binding constraint"
          value={<span style={{ fontSize: 17 }}>{s.binding_constraint.replace(/_/g, " ")}</span>}
          foot={`budget used ${pct(s.budget_used)}`}
        />
        <Stat
          label="Mean est. saving, selected"
          value={usd(s.mean_saving_selected)}
          foot={`threshold ${usd(s.value_fit_threshold_usd)} over 90 days`}
        />
        <Stat
          label="Contact-rate gap"
          value={s.contact_rate_gap.toFixed(3)}
          foot={
            s.fairness_flag ? (
              <Badge tone="bad">above tolerance</Badge>
            ) : (
              <Badge tone="ok">within tolerance</Badge>
            )
          }
        />
      </div>

      <Card
        title="Where the candidate population went"
        hint="The value-fit gate is the honesty check: users the uplift model would happily contact, suppressed because Genius would not pay for itself for them."
      >
        <CategoryBars data={suppression} format={compactInt} highlight="value fit" />
        <div className="legend">
          <span className="item">
            <span className="swatch" style={{ background: "var(--pos)" }} />
            selected
          </span>
          <span className="item">
            <span className="swatch" style={{ background: "var(--series-2)" }} />
            suppressed by value fit
          </span>
          <span className="item">
            <span className="swatch" style={{ background: "var(--reference)" }} />
            other suppression
          </span>
        </div>
      </Card>

      <Card
        title="Cohort"
        hint="Sort by propensity to see the disagreement: users a propensity model ranks highest are often not the ones worth contacting."
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            <select
              className="ghost" value={decision}
              onChange={(e) => { setDecision(e.target.value); setOffset(0); }}
              style={{ padding: "6px 10px", borderRadius: 6 }}
              aria-label="Filter by decision"
            >
              {DECISIONS.map((d) => (
                <option key={d} value={d}>{d ? DECISION_LABEL[d] ?? d : "All decisions"}</option>
              ))}
            </select>
          </div>
        }
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Segment</th>
                {SORTS.map((s2) => (
                  <th
                    key={s2.key}
                    className="sortable num"
                    style={{ textAlign: "right", color: sortBy === s2.key ? "var(--series-1)" : undefined }}
                    onClick={() => { setSortBy(s2.key); setOffset(0); }}
                  >
                    {s2.label} {sortBy === s2.key ? "▼" : ""}
                  </th>
                ))}
                <th style={{ textAlign: "right" }}>Net</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r: CohortRow) => (
                <tr
                  key={r.user_id}
                  className={selected === r.user_id ? "selected" : undefined}
                  onClick={() => onSelect(r.user_id)}
                  style={{ cursor: "pointer" }}
                >
                  <td><span className="uid">{r.user_id}</span></td>
                  <td>{r.segment ?? "—"}</td>
                  <td className="num">{pp(r.uplift)}</td>
                  <td className="num">{r.propensity === null ? "—" : pct(r.propensity)}</td>
                  <td className="num">{usd(r.estimated_saving_90d)}</td>
                  <td
                    className="num"
                    style={{ color: r.net_position_90d >= 0 ? "var(--good)" : "var(--critical)" }}
                  >
                    {usd(r.net_position_90d)}
                  </td>
                  <td>
                    <Badge tone={decisionTone(r.decision)}>
                      {DECISION_LABEL[r.decision] ?? r.decision}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data.rows.some((r) => r.reason_detail) && (
          <p className="note">
            Example suppression reason:{" "}
            <em>{data.rows.find((r) => r.reason_detail)?.reason_detail}</em>
          </p>
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
          <button className="ghost" disabled={offset === 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </button>
          <span className="note" style={{ margin: 0 }}>
            {offset + 1}–{Math.min(offset + PAGE, data.total)} of {compactInt(data.total)}
            {loading && " · updating"}
          </span>
          <button className="ghost" disabled={offset + PAGE >= data.total || loading}
                  onClick={() => setOffset(offset + PAGE)}>
            Next
          </button>
        </div>
      </Card>
    </div>
  );
}
