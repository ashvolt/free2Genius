export const usd = (n: number, dp = 2) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

export const pct = (n: number, dp = 1) => `${(n * 100).toFixed(dp)}%`;

/** Percentage points — for differences, where "%" would be ambiguous. */
export const pp = (n: number, dp = 2) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(dp)} pp`;

export const compactInt = (n: number) => n.toLocaleString("en-US");

export const DECISION_LABEL: Record<string, string> = {
  selected: "Contact",
  value_fit: "Suppressed · value fit",
  negative_uplift: "Suppressed · negative uplift",
  budget: "Suppressed · budget",
  parity_cap: "Suppressed · parity cap",
  no_data: "Suppressed · no data",
};

export const decisionTone = (decision: string): "ok" | "warn" | "neutral" =>
  decision === "selected" ? "ok" : decision === "value_fit" ? "warn" : "neutral";

export const CHECK_LABEL: Record<string, string> = {
  numeric_grounding: "Numbers grounded",
  prohibited_advice: "No prohibited advice",
  feature_names: "Features exist",
  no_pressure: "No pressure",
  coherence: "Coherent",
  disclosure: "Disclosure present",
};
