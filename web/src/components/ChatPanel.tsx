import { useRef, useState } from "react";
import { api, type AgentResult } from "../lib/api";
import { CHECK_LABEL } from "../lib/format";
import { Badge, Card } from "./common";

interface Turn {
  role: "user" | "agent";
  text: string;
  result?: AgentResult;
}

const SUGGESTIONS = [
  "Why am I paying express delivery fees?",
  "Would Genius actually be worth it for me?",
  "Should I invest my savings instead?",
];

export function ChatPanel({ userId, provider }: { userId: string | null; provider: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    if (!userId || !text.trim() || busy) return;
    setTurns((t) => [...t, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const result = await api.chat(userId, text, provider);
      setTurns((t) => [...t, { role: "agent", text: result.message, result }]);
    } catch (e) {
      setTurns((t) => [
        ...t,
        { role: "agent", text: `Request failed: ${e instanceof Error ? e.message : String(e)}` },
      ]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() =>
        logRef.current?.scrollTo({ top: logRef.current.scrollHeight }),
      );
    }
  }

  return (
    <Card
      title="Concierge chat"
      hint="The same tools and the same guardrails as the nudge. Try the investment question — the refusal is decided before any model runs."
    >
      {!userId && <p className="note">Select a user first.</p>}

      <div className="chat-log" ref={logRef}>
        {turns.length === 0 && (
          <div className="note" style={{ marginTop: 0 }}>
            No messages yet.
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} style={{ display: "contents" }}>
            <div className={`bubble ${t.role}`}>{t.text}</div>
            {t.result && (
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: -4 }}>
                {Object.entries(t.result.guardrails.checks).map(([name, passed]) => (
                  <Badge key={name} tone={passed ? "ok" : "bad"}>
                    {CHECK_LABEL[name] ?? name}
                  </Badge>
                ))}
                {t.result.refused && <Badge tone="warn">declined · {t.result.refusal_kind}</Badge>}
                {t.result.tool_calls.length > 0 && (
                  <Badge tone="neutral">
                    {t.result.tool_calls.map((c) => c.tool).join(" → ")}
                  </Badge>
                )}
                {(t.result.input_guardrails.findings?.length ?? 0) > 0 && (
                  <Badge tone="warn">injection attempt logged</Badge>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="bubble agent pending">
            <span className="spinner" aria-hidden="true" />
            Reading the account and checking the answer…
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
        {SUGGESTIONS.map((s) => (
          <button key={s} className="ghost" disabled={!userId || busy} onClick={() => send(s)}>
            {s}
          </button>
        ))}
      </div>

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your fees, advances or whether Genius is worth it…"
          disabled={!userId || busy}
          aria-label="Message"
        />
        <button className="primary" type="submit" disabled={!userId || busy || !input.trim()}>
          Send
        </button>
      </form>
    </Card>
  );
}
