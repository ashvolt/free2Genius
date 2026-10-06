import { Fragment, useEffect, useMemo, useState } from "react";
import { api, type AgentResult, type Evidence } from "../lib/api";
import { CHECK_LABEL } from "../lib/format";
import { Badge, Card, Empty, ErrorState, ProviderSelect } from "./common";

/* An explicitly chosen provider fails rather than falling back to the
   deterministic writer, so the error has to say what that provider needs. */
const PROVIDER_HINT: Record<string, string | undefined> = {
  openai:
    "This needs an OpenAI-compatible server reachable at F2G_OPENAI_BASE_URL (Ollama's default is http://localhost:11434/v1) serving F2G_OPENAI_MODEL. Check `ollama list` for a model you have.",
  llamacpp:
    "In-process llama.cpp needs the GGUF weights (python run.py models) and llama-cpp-python installed. If you already run Ollama, pick that provider instead — it uses the models you have.",
};

/** Split the message so every figure with provenance becomes a clickable chip.
 *
 * This is the point of the whole screen: a claim that a number is grounded is
 * an assertion, and a number you can click to see the tool call behind it is
 * evidence. Longest-first matching stops "$4.99" from being consumed by a
 * shorter overlapping match.
 */
function useChips(message: string, evidence: Evidence[]) {
  return useMemo(() => {
    if (!evidence.length) return [{ text: message }] as { text: string; ev?: Evidence }[];
    const sorted = [...evidence].sort((a, b) => b.rendered.length - a.rendered.length);
    const pattern = new RegExp(
      `(${sorted.map((e) => e.rendered.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
      "g",
    );
    return message.split(pattern).map((part) => {
      const ev = evidence.find((e) => e.rendered === part);
      return ev ? { text: part, ev } : { text: part };
    });
  }, [message, evidence]);
}

/** The message carries light markdown from the template path. */
function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((chunk, i) => {
    if (chunk.startsWith("**") && chunk.endsWith("**")) {
      return <strong key={i}>{chunk.slice(2, -2)}</strong>;
    }
    if (chunk.startsWith("_") && chunk.endsWith("_") && chunk.length > 2) {
      return <em key={i}>{chunk.slice(1, -1)}</em>;
    }
    return <Fragment key={i}>{chunk}</Fragment>;
  });
}

/** Why the deterministic writer took over. The reason changes what to do next,
 *  so the banner must not assert one cause for every failure. */
function degradedExplanation(reason: string): string {
  if (/timeout|timed out/i.test(reason)) {
    return (
      "The provider did not answer within its budget, so the user received a templated, " +
      "fully grounded message rather than waiting or seeing nothing. A cold local model " +
      "loading its weights is the usual cause; raise F2G_LLM_TIMEOUT_S or warm the model."
    );
  }
  if (/unavailable|unreachable|not found/i.test(reason)) {
    return (
      "The provider could not be reached at all, so the templated writer answered instead. " +
      "This is the path a fresh clone with no model weights takes."
    );
  }
  return (
    "This is the designed failure path: the model produced something the guardrails " +
    "rejected, so the user received a templated, fully grounded message instead of " +
    "nothing — and instead of the rejected text."
  );
}

export function NudgePreview({
  userId,
  provider,
  onProviderChange,
}: {
  userId: string | null;
  provider: string;
  onProviderChange: (next: string) => void;
}) {
  const [result, setResult] = useState<AgentResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<Evidence | null>(null);

  useEffect(() => {
    if (!userId) return;
    let live = true;
    setLoading(true);
    setResult(null);
    setOpen(null);
    api
      .nudge(userId, provider)
      .then((r) => live && (setResult(r), setError(null)))
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
    // `provider` is read here but deliberately not a dependency: changing the
    // dropdown must not fire a run on its own. Regenerate is what does that.
  }, [userId]);

  function regenerate() {
    if (!userId) return;
    setLoading(true);
    setOpen(null);
    api
      .nudge(userId, provider, true)
      .then((r) => (setResult(r), setError(null)))
      .catch(setError)
      .finally(() => setLoading(false));
  }

  /* The picker and Regenerate ride along in every state, including the error
     one: a provider that is unavailable fails loudly by design, and the control
     that got you there has to still be on screen to get you back out. */
  const actions = (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      {result?.cached && <Badge tone="neutral">cached</Badge>}
      <ProviderSelect value={provider} onChange={onProviderChange} disabled={loading} />
      <button className="ghost" onClick={regenerate} disabled={loading || !userId}>
        Regenerate
      </button>
    </div>
  );

  const parts = useChips(result?.message ?? "", result?.evidence ?? []);

  if (!userId) return <Empty title="Select a user" detail="Pick a row in the cohort table." />;
  if (loading) {
    return (
      <Card title="Nudge preview" hint="Generating…" actions={actions}>
        <div className="state">
          <span className="spinner" aria-hidden="true" />
          Running the agent for {userId} with the {provider} provider. Local generation takes a
          few seconds per tool call — this is real inference, not a canned response.
        </div>
      </Card>
    );
  }
  if (error) {
    return (
      <Card title="Nudge preview" actions={actions}>
        <ErrorState error={error} hint={PROVIDER_HINT[provider]} />
      </Card>
    );
  }
  if (!result) return <Empty title="No nudge yet" />;

  const checks = Object.entries(result.guardrails.checks);
  const blocked = result.guardrails.blocked;

  return (
    <Card
      title="Nudge preview"
      hint="Every monetary figure is a chip. Click one to see the tool call that produced it."
      actions={actions}
    >
      {result.degraded && (
        <div className="synthetic-banner" style={{ marginTop: 0 }}>
          <strong>Degraded to the deterministic writer.</strong> {result.degraded_reason}
          <div style={{ marginTop: 4 }}>{degradedExplanation(result.degraded_reason)}</div>
        </div>
      )}

      {result.refused && (
        <p className="note" style={{ marginTop: 0 }}>
          This turn was declined by the scope policy before any model ran
          ({result.refusal_kind}).
        </p>
      )}

      <div className="message">
        {parts.map((p, i) =>
          p.ev ? (
            <button
              key={i}
              className={`chip${p.ev.tools.length === 0 ? " unbacked" : ""}`}
              aria-expanded={open?.rendered === p.ev.rendered}
              onClick={() => setOpen(open?.rendered === p.ev!.rendered ? null : p.ev!)}
              title={p.ev.tools.length ? `from ${p.ev.tools.join(", ")}` : "no provenance"}
            >
              {p.text}
            </button>
          ) : (
            <Fragment key={i}>{renderInline(p.text)}</Fragment>
          ),
        )}
      </div>

      {open && (
        <div className="evidence-pop">
          <div style={{ fontWeight: 650, marginBottom: 6 }}>
            {open.rendered} — traced to {open.tools.length ? open.tools.join(", ") : "nothing"}
          </div>
          {result.tool_calls
            .filter((c) => open.tools.includes(c.tool))
            .map((c, i) => (
              <div key={i} style={{ marginTop: 8 }}>
                <code>
                  {c.tool}({JSON.stringify(c.arguments)})
                </code>
                {c.forced && (
                  <span style={{ marginLeft: 8 }}>
                    <Badge tone="warn">called by the agent, not the model</Badge>
                  </span>
                )}
                <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: "6px 0 0",
                                               maxHeight: 190, overflow: "auto" }}>
                  {JSON.stringify(c.result, null, 1).slice(0, 1400)}
                </pre>
              </div>
            ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 14 }}>
        {checks.map(([name, passed]) => (
          <Badge key={name} tone={passed ? "ok" : "bad"}>
            {CHECK_LABEL[name] ?? name}
          </Badge>
        ))}
        {blocked && <Badge tone="bad">draft blocked</Badge>}
      </div>

      {result.guardrails.findings.length > 0 && (
        <div className="note">
          {result.guardrails.findings.map((f, i) => (
            <div key={i}>
              <strong>{f.check}</strong> [{f.severity}] {f.message}
              {f.span && <> — <code>{f.span}</code></>}
            </div>
          ))}
        </div>
      )}

      <div className="note">
        {String(result.telemetry.provider)} · {String(result.telemetry.model)} ·{" "}
        {result.rounds_used} tool rounds · {String(result.telemetry.latency_s)}s ·{" "}
        prompt {result.prompt_version}
        {result.forced_evidence.length > 0 && (
          <> · evidence the model skipped and the agent fetched: {result.forced_evidence.join(", ")}</>
        )}
      </div>
    </Card>
  );
}
