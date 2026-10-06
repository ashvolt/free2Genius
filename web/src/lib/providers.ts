/** The generation providers the console offers.
 *
 * One list, used by every control that lets someone pick a provider, so the
 * nudge card and the chat composer can never drift apart. `anthropic` exists in
 * f2g/llm/runtime.py but is deliberately absent: it sends account data off the
 * machine, which is a decision for whoever deploys the service
 * (F2G_LLM_PROVIDER), not for a click in a demo console.
 */
export const PROVIDERS = [
  { id: "deterministic", label: "Deterministic (instant)" },
  { id: "openai", label: "Ollama / local server (minutes)" },
  { id: "llamacpp", label: "In-process llama.cpp (needs GGUF weights)" },
] as const;
