import { PROVIDERS } from "../lib/providers";
import type { ReactNode } from "react";

export function Loading({ what }: { what: string }) {
  return (
    <div className="state">
      <span className="spinner" aria-hidden="true" />
      Loading {what}…
    </div>
  );
}

/** Never an empty chart that reads as zero — say what failed and how to fix it. */
export function ErrorState({ error, hint }: { error: unknown; hint?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="state error" role="alert">
      <div className="title">Could not load this view</div>
      <div className="mono">{message}</div>
      {hint && <div className="note">{hint}</div>}
    </div>
  );
}

export function Empty({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="state">
      <div className="title">{title}</div>
      {detail && <div>{detail}</div>}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "ok" | "warn" | "bad" | "neutral";
  children: ReactNode;
}) {
  return (
    <span className={`badge ${tone}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  foot,
}: {
  label: string;
  value: ReactNode;
  foot?: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

export function Card({
  title,
  hint,
  children,
  actions,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="card">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h2>{title}</h2>
          {hint && <p className="hint">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Picks which provider the *next* generation uses.
 *
 * Deliberately inert: changing it fires no request. The caller's own action —
 * Regenerate, or Send — is what spends the seconds of local inference, so the
 * choice and the cost stay one click apart.
 */
export function ProviderSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  return (
    <select
      className="provider-select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      aria-label="Generation provider for the next run"
      title="Which provider the next run uses"
    >
      {PROVIDERS.map((p) => (
        <option key={p.id} value={p.id}>{p.label}</option>
      ))}
    </select>
  );
}
