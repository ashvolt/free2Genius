/** Hand-built SVG charts.
 *
 * No chart library, for three reasons: the colour rules and the three-series
 * cap are enforced here rather than configured; every mark carries a hover
 * tooltip and a direct label without fighting a default theme; and the bundle
 * stays small enough to matter.
 *
 * Rules applied throughout: one axis only, thin marks, 4px rounded data-ends
 * anchored to the baseline, a 2px surface gap between adjacent fills, recessive
 * grid, and a legend whenever two or more series are present.
 */
import { useId, useState } from "react";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export const seriesColor = (i: number) => SERIES[i % SERIES.length];

/** A bar with a rounded data-end and a square baseline end. */
function barPath(x: number, y: number, w: number, h: number, r: number, up: boolean): string {
  const radius = Math.min(r, w / 2, Math.abs(h));
  if (Math.abs(h) < 0.5) return "";
  return up
    ? `M${x},${y + h} L${x},${y + radius} Q${x},${y} ${x + radius},${y} ` +
      `L${x + w - radius},${y} Q${x + w},${y} ${x + w},${y + radius} L${x + w},${y + h} Z`
    : `M${x},${y} L${x},${y + h - radius} Q${x},${y + h} ${x + radius},${y + h} ` +
      `L${x + w - radius},${y + h} Q${x + w},${y + h} ${x + w},${y + h - radius} L${x + w},${y} Z`;
}

export interface GroupedBar {
  label: string;
  value: number;
  ci?: [number, number];
  color?: string;
  sublabel?: string;
}

/** Conversion-by-variant style chart: one measure, one axis, error bars. */
export function BarsWithCI({
  data,
  format,
  yTitle,
  height = 260,
}: {
  data: GroupedBar[];
  format: (n: number) => string;
  yTitle: string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const pad = { top: 18, right: 16, bottom: 46, left: 58 };
  const width = 560;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const lo = Math.min(0, ...data.map((d) => d.ci?.[0] ?? d.value));
  const hi = Math.max(...data.map((d) => d.ci?.[1] ?? d.value)) * 1.08;
  const y = (v: number) => pad.top + innerH - ((v - lo) / (hi - lo || 1)) * innerH;

  const slot = innerW / data.length;
  const barW = Math.min(64, slot * 0.52);
  const ticks = 4;

  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`${yTitle} by arm`}>
        {Array.from({ length: ticks + 1 }, (_, i) => {
          const v = lo + ((hi - lo) / ticks) * i;
          return (
            <g key={i}>
              <line className="grid-line" x1={pad.left} x2={width - pad.right}
                    y1={y(v)} y2={y(v)} />
              <text className="axis-label" x={pad.left - 8} y={y(v)} textAnchor="end"
                    dominantBaseline="middle">
                {format(v)}
              </text>
            </g>
          );
        })}

        {data.map((d, i) => {
          const cx = pad.left + slot * i + slot / 2;
          const top = y(d.value);
          const base = y(Math.max(lo, 0));
          const color = d.color ?? seriesColor(i);
          return (
            <g key={d.label}
               onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* Hit target larger than the mark. */}
              <rect x={cx - slot / 2} y={pad.top} width={slot} height={innerH} fill="transparent" />
              <path d={barPath(cx - barW / 2, top, barW, base - top, 4, true)}
                    fill={color} opacity={hover === null || hover === i ? 1 : 0.55} />
              {d.ci && (
                <g stroke={"var(--text-primary)"} strokeWidth={1.5} opacity={0.75}>
                  <line x1={cx} x2={cx} y1={y(d.ci[0])} y2={y(d.ci[1])} />
                  <line x1={cx - 7} x2={cx + 7} y1={y(d.ci[0])} y2={y(d.ci[0])} />
                  <line x1={cx - 7} x2={cx + 7} y1={y(d.ci[1])} y2={y(d.ci[1])} />
                </g>
              )}
              <text className="value-label" x={cx} y={top - 8} textAnchor="middle">
                {format(d.value)}
              </text>
              <text className="axis-label" x={cx} y={height - pad.bottom + 18}
                    textAnchor="middle" style={{ fontWeight: 600 }}>
                {d.label}
              </text>
              {d.sublabel && (
                <text className="axis-label" x={cx} y={height - pad.bottom + 32}
                      textAnchor="middle">
                  {d.sublabel}
                </text>
              )}
            </g>
          );
        })}

        <text className="axis-title" x={0} y={0}
              transform={`translate(13, ${pad.top + innerH / 2}) rotate(-90)`}
              textAnchor="middle">
          {yTitle}
        </text>
        <title id={id}>{yTitle}</title>
      </svg>
      {hover !== null && data[hover].ci && (
        <div className="note">
          <strong>{data[hover].label}</strong> — {format(data[hover].value)} (95% CI{" "}
          {format(data[hover].ci![0])} to {format(data[hover].ci![1])})
        </div>
      )}
    </div>
  );
}

export interface IntervalRow {
  label: string;
  value: number;
  ci: [number, number];
  color?: string;
  emphasis?: boolean;
}

/** Interval comparison: the shape for "two ways of measuring the same thing". */
export function IntervalPlot({
  rows,
  format,
  xTitle,
  reference = 0,
  referenceLabel,
  margin,
  marginLabel,
  height,
}: {
  rows: IntervalRow[];
  format: (n: number) => string;
  xTitle: string;
  reference?: number;
  referenceLabel?: string;
  margin?: number;
  marginLabel?: string;
  height?: number;
}) {
  const pad = { top: 22, right: 24, bottom: 58, left: 132 };
  const width = 560;
  const rowH = 42;
  const h = height ?? pad.top + pad.bottom + rows.length * rowH;
  const innerW = width - pad.left - pad.right;

  const values = rows.flatMap((r) => [...r.ci, r.value]).concat([reference]);
  if (margin !== undefined) values.push(margin);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = (v: number) => pad.left + ((v - lo + span * 0.08) / (span * 1.16)) * innerW;

  return (
    <svg className="chart" viewBox={`0 0 ${width} ${h}`} role="img" aria-label={xTitle}>
      <line className="zero-line" x1={x(reference)} x2={x(reference)}
            y1={pad.top} y2={h - pad.bottom} />
      {referenceLabel && (
        <text className="axis-label" x={x(reference)} y={h - pad.bottom + 16}
              textAnchor="middle">
          {referenceLabel}
        </text>
      )}
      {margin !== undefined && (
        <>
          <line className="ref-line" stroke="var(--critical)" x1={x(margin)} x2={x(margin)}
                y1={pad.top} y2={h - pad.bottom} />
          {marginLabel && (
            <text className="axis-label" fill="var(--critical)" x={x(margin)}
                  y={pad.top - 4} textAnchor="middle" style={{ fontWeight: 600 }}>
              {marginLabel}
            </text>
          )}
        </>
      )}

      {rows.map((r, i) => {
        const cy = pad.top + rowH * i + rowH / 2;
        const color = r.color ?? seriesColor(i);
        return (
          <g key={r.label}>
            <text className="axis-label" x={pad.left - 12} y={cy} textAnchor="end"
                  dominantBaseline="middle"
                  style={{ fontWeight: r.emphasis ? 700 : 500 }}>
              {r.label}
            </text>
            <line x1={x(r.ci[0])} x2={x(r.ci[1])} y1={cy} y2={cy}
                  stroke={color} strokeWidth={r.emphasis ? 3 : 2} strokeLinecap="round" />
            <circle cx={x(r.value)} cy={cy} r={5} fill={color}
                    stroke="var(--surface-1)" strokeWidth={2} />
            <text className="value-label" x={x(r.ci[1]) + 9} y={cy} dominantBaseline="middle">
              {format(r.value)}
            </text>
          </g>
        );
      })}

      <text className="axis-title" x={pad.left + innerW / 2} y={h - 8} textAnchor="middle">
        {xTitle}
      </text>
    </svg>
  );
}

/** Diverging bars for a signed quantity, e.g. suppression counts by reason. */
export function CategoryBars({
  data,
  format,
  highlight,
  height = 230,
}: {
  data: { label: string; value: number }[];
  format: (n: number) => string;
  highlight?: string;
  height?: number;
}) {
  const pad = { top: 22, right: 12, bottom: 52, left: 52 };
  const width = 560;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const hi = Math.max(...data.map((d) => d.value)) * 1.15 || 1;
  const y = (v: number) => pad.top + innerH - (v / hi) * innerH;
  const slot = innerW / data.length;
  const barW = Math.min(56, slot * 0.6);

  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Category counts">
      {[0, 0.5, 1].map((f) => (
        <line key={f} className="grid-line" x1={pad.left} x2={width - pad.right}
              y1={y(hi * f)} y2={y(hi * f)} />
      ))}
      {data.map((d, i) => {
        const cx = pad.left + slot * i + slot / 2;
        const top = y(d.value);
        const color =
          highlight && d.label === highlight ? "var(--series-2)"
          : i === 0 ? "var(--pos)" : "var(--reference)";
        return (
          <g key={d.label}>
            <path d={barPath(cx - barW / 2, top, barW, y(0) - top, 4, true)} fill={color} />
            <text className="value-label" x={cx} y={top - 7} textAnchor="middle">
              {format(d.value)}
            </text>
            {d.label.split(" ").map((word, wi, arr) => (
              <text key={wi} className="axis-label" x={cx}
                    y={height - pad.bottom + 16 + wi * 12} textAnchor="middle"
                    style={{ fontWeight: arr.length === 1 ? 600 : 500 }}>
                {word}
              </text>
            ))}
          </g>
        );
      })}
    </svg>
  );
}
