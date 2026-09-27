/** Typed client for the Free2Genius API.
 *
 * The types here mirror the service's pydantic models. They are written by hand
 * rather than generated so the console can be read on its own, but the OpenAPI
 * schema at /docs is the contract of record.
 */

const BASE = import.meta.env.DEV ? "/api" : "";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(await describe(res), res.status);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(await describe(res), res.status);
  return res.json() as Promise<T>;
}

async function describe(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/* ---------- types ---------- */

export interface ValueFit {
  estimated_saving_90d: number;
  genius_cost_90d: number;
  net_position_90d: number;
  passes: boolean;
}

export interface CohortRow {
  user_id: string;
  segment: string | null;
  income_band: string | null;
  uplift: number;
  propensity: number | null;
  estimated_saving_90d: number;
  net_position_90d: number;
  decision: string;
  reason_detail: string;
}

export interface PolicySummary {
  candidates: number;
  selected: number;
  budget_slots: number;
  budget_used: number;
  binding_constraint: string;
  suppressed_by_reason: Record<string, number>;
  mean_uplift_selected: number;
  mean_saving_selected: number;
  expected_incremental_conversions: number;
  contact_rate_gap: number;
  eligible_rate_gap: number;
  fairness_flag: boolean;
  value_fit_threshold_usd: number;
  backfilled_by_gate?: number;
}

export interface CohortResponse {
  total: number;
  offset: number;
  limit: number;
  rows: CohortRow[];
  summary: PolicySummary;
}

export interface ScoreResponse extends Omit<CohortRow, "net_position_90d" | "estimated_saving_90d"> {
  value_fit: ValueFit;
  model_versions: Record<string, string>;
}

export interface Evidence {
  value: number;
  rendered: string;
  tools: string[];
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  forced?: boolean;
}

export interface GuardrailFinding {
  check: string;
  severity: string;
  message: string;
  span: string;
}

export interface AgentResult {
  user_id: string;
  message: string;
  tool_calls: ToolCall[];
  evidence: Evidence[];
  guardrails: {
    passed: boolean;
    blocked: boolean;
    checks: Record<string, boolean>;
    findings: GuardrailFinding[];
  };
  input_guardrails: { findings?: GuardrailFinding[] };
  telemetry: Record<string, number | string>;
  degraded: boolean;
  degraded_reason: string;
  prompt_version: string;
  rounds_used: number;
  forced_evidence: string[];
  refused?: boolean;
  refusal_kind?: string;
  cached?: boolean;
}

export interface ArmStats {
  arm: string;
  n: number;
  conversions: number;
  rate: number;
  retained: number;
  converted_with_retention_data: number;
  retention_rate: number;
}

export interface Comparison {
  treatment: string;
  control: string;
  absolute_lift: number;
  relative_lift: number;
  fixed_ci: [number, number];
  sequential_ci: [number, number];
  fixed_p_value: number;
  n_treatment: number;
  n_control: number;
}

export interface ExperimentSummary {
  experiment_id: string;
  arms: ArmStats[];
  conversion: Comparison;
  retention_guardrail: Comparison & { margin: number };
  verdict: { verdict: string; rule: string; detail: string };
  timeseries: { day: string; variant: string; event_type: string; n: number }[];
}

export interface Health {
  status: string;
  models: { available: boolean; detail: unknown };
  data: { available: boolean; users: number };
  llm: { provider?: string; model?: string; available: boolean; detail?: string; egress?: string };
  notice: string;
}

/* ---------- endpoints ---------- */

export const api = {
  health: () => get<Health>("/health"),
  cohort: (params: {
    limit?: number; offset?: number; decision?: string; segment?: string; sort_by?: string;
  }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, String(v)));
    return get<CohortResponse>(`/cohort?${q}`);
  },
  score: (userId: string) => get<ScoreResponse>(`/score/${userId}`),
  nudge: (userId: string, provider?: string, refresh = false) =>
    post<AgentResult>(`/agent/nudge/${userId}`, { provider, refresh }),
  chat: (userId: string, message: string, provider?: string) =>
    post<AgentResult>("/agent/chat", { user_id: userId, message, provider }),
  experiment: () => get<ExperimentSummary>("/experiment/summary"),
  telemetry: () => get<Record<string, unknown>>("/telemetry"),
};
