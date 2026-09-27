import { useEffect, useState } from "react";
import { api, type ExperimentSummary } from "../lib/api";
import { compactInt, pct, pp } from "../lib/format";
import { Card, ErrorState, Loading, Stat } from "./common";
import { BarsWithCI, IntervalPlot } from "./Charts";

const ARM_LABEL: Record<string, string> = {
  agent_concierge: "Agent concierge",
  generic_upsell: "Generic upsell",
  holdout: "Holdout",
};

export function ExperimentDashboard() {
  const [data, setData] = useState<ExperimentSummary | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    api.experiment().then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, []);

  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading what="experiment results" />;

  const totalN = data.arms.reduce((a, b) => a + b.n, 0);
  if (totalN === 0) {
    return (
      <Card title="Experiment" hint="No events recorded yet.">
        <p className="note" style={{ marginTop: 0 }}>
          Seed a simulated run: <code className="mono">python scripts/seed_experiment.py</code>
        </p>
      </Card>
    );
  }

  const c = data.conversion;
  const r = data.retention_guardrail;
  const v = data.verdict;

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className={`verdict ${v.verdict}`}>
        <div>
          <div className="v-label">Verdict</div>
          <div className="v-rule">{v.verdict.replace(/_/g, " ")} — {v.rule}</div>
          <div className="v-detail">{v.detail}</div>
        </div>
      </div>

      <div className="grid stats">
        <Stat label="Users in experiment" value={compactInt(totalN)} foot={data.experiment_id} />
        <Stat
          label="Conversion lift"
          value={pp(c.absolute_lift)}
          foot={`${pct(c.relative_lift, 1)} relative · agent vs generic`}
        />
        <Stat
          label="Retention guardrail"
          value={pp(r.absolute_lift)}
          foot={`non-inferiority margin −${r.margin.toFixed(3)}`}
        />
        <Stat
          label="Fixed-horizon p-value"
          value={c.fixed_p_value.toFixed(3)}
          foot="not the decision rule — see below"
        />
      </div>

      <div className="grid two">
        <Card
          title="Conversion by arm"
          hint="Three arms: the holdout separates 'the agent helped' from 'any nudge helped'."
        >
          <BarsWithCI
            yTitle="Conversion rate"
            format={(n) => pct(n, 1)}
            data={data.arms.map((a) => ({
              label: ARM_LABEL[a.arm] ?? a.arm,
              value: a.rate,
              sublabel: `n=${compactInt(a.n)}`,
            }))}
          />
          <div className="legend">
            {data.arms.map((a, i) => (
              <span className="item" key={a.arm}>
                <span className="swatch" style={{ background: `var(--series-${i + 1})` }} />
                {ARM_LABEL[a.arm] ?? a.arm} — {compactInt(a.conversions)} conversions
              </span>
            ))}
          </div>
        </Card>

        <Card
          title="30-day retention by arm"
          hint="The counter-metric. A conversion win bought by pushing users who do not benefit shows up here."
        >
          <BarsWithCI
            yTitle="Retention among converters"
            format={(n) => pct(n, 1)}
            data={data.arms.map((a) => ({
              label: ARM_LABEL[a.arm] ?? a.arm,
              value: a.retention_rate,
              sublabel: `${compactInt(a.retained)}/${compactInt(a.converted_with_retention_data)}`,
            }))}
          />
        </Card>
      </div>

      <Card
        title="Fixed-horizon vs always-valid intervals"
        hint="The sequential interval is wider. That width is what makes it valid to read this page whenever you like."
      >
        <IntervalPlot
          xTitle="Difference in conversion rate (agent − generic)"
          format={(n) => pp(n)}
          referenceLabel="no effect"
          rows={[
            { label: "Fixed horizon (95%)", value: c.absolute_lift, ci: c.fixed_ci, color: "var(--reference)" },
            { label: "Always valid", value: c.absolute_lift, ci: c.sequential_ci, emphasis: true },
          ]}
        />
        <p className="note">
          Simulated on this repository: under no true effect, read 200 times, the naive
          fixed-horizon test declares a winner <strong>49%</strong> of the time at a nominal 5%.
          The always-valid bound holds at <strong>3%</strong>. Reproduce with{" "}
          <code className="mono">pytest tests/test_experiment.py -k null_experiment</code>.
        </p>
      </Card>

      <Card
        title="Retention guardrail against its margin"
        hint="Checked before any ship decision. A conversion win must never mask a retention breach."
      >
        <IntervalPlot
          xTitle="Difference in 30-day retention (agent − generic)"
          format={(n) => pp(n)}
          referenceLabel="no difference"
          margin={-r.margin}
          marginLabel="non-inferiority margin"
          rows={[
            { label: "Fixed horizon (95%)", value: r.absolute_lift, ci: r.fixed_ci, color: "var(--reference)" },
            { label: "Always valid", value: r.absolute_lift, ci: r.sequential_ci, emphasis: true, color: "var(--series-3)" },
          ]}
        />
        <p className="note">
          The agent arm targets users the value-fit gate judged would genuinely benefit, so a
          retention gap in its favour is the gate showing up in the data rather than a
          separate effect.
        </p>
      </Card>
    </div>
  );
}
