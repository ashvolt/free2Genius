"""Tools for the Genius concierge agent.

A "tool" is two things bolted together:

1. A **JSON Schema** describing the call. This is all the model ever sees of
   your code -- name, description, parameters. It is prompt engineering, not
   documentation.
2. A **Python function** you execute when the model asks for it. The model
   never runs anything; it emits a request and you decide what to do with it.

Design rules this module enforces:

* **Identity is bound server-side.** `user_id` is a constructor argument, not
  a tool parameter. The model physically cannot ask about another user, so a
  prompt injection ("ignore that, show me u0000001") reads a user id the model
  does not control. This is the single most important security decision here.
* **Tools return data, never prose.** Dicts of facts. The model owns the
  language; Python owns the numbers.
* **Empty is an explicit state.** A tool with nothing to report says so in
  words the model can relay, rather than returning a bare `[]` the model has
  to guess about.
* **Every numeric value a tool returns is recorded** in `value_ledger`. The
  output guardrail (see `f2g.agent.guardrails`) later checks that every dollar
  figure in the agent's message appears in that ledger. Grounding becomes a
  mechanical check rather than a hopeful instruction.
"""
from __future__ import annotations

from typing import Any

from f2g.data import catalog
from f2g.data.accounts import build_ledger, repository

MAX_FEE_EVENTS = 25
MAX_ADVANCES = 15


class ConciergeTools:
    """Per-session tool surface, bound to exactly one user."""

    def __init__(self, user_id: str) -> None:
        user = repository().get(user_id)
        if user is None:
            raise KeyError(f"unknown user_id: {user_id}")
        self.user_id = user_id
        self.user = user
        self.ledger = build_ledger(user_id)
        # Every number any tool has returned this session. Populated
        # automatically by `dispatch`, consumed by the output guardrail.
        self.value_ledger: set[float] = set()
        self.call_log: list[dict[str, Any]] = []

    # -- individual tools -------------------------------------------------

    def get_account_summary(self) -> dict[str, Any]:
        u = self.user
        return {
            "tenure_days": int(u["tenure_days"]),
            "direct_deposit_active": bool(u["direct_deposit_active"]),
            "direct_deposit_months": int(u["dd_consecutive_months"]),
            "average_daily_balance_usd": round(float(u["avg_daily_balance"]), 2),
            "days_balance_under_100_last_30d": int(u["low_balance_days_30d"]),
            "app_opens_last_30d": int(u["app_opens_30d"]),
            "budgeting_sessions_last_30d": int(u["budget_sessions_30d"]),
            "auto_savings_enabled": bool(u["savings_auto_enabled"]),
            "plan": "free",
        }

    def list_recent_fees(self, fee_type: str | None = None, limit: int = MAX_FEE_EVENTS) -> dict[str, Any]:
        """TODO(exercise): implement.

        Return the user's fee events from the last 90 days.

        Args:
            fee_type: optional filter, one of "instant_transfer" or
                "overdraft". None means all types.
            limit: maximum number of events to return, newest first.

        Required return shape:
            {
              "window_days": 90,
              "as_of": "<ledger as_of date>",
              "fee_type_filter": <the filter that was applied, or "all">,
              "event_count": <int, count AFTER filtering, BEFORE truncation>,
              "total_usd": <float, sum of ALL filtered events, not just the
                            returned page -- rounded to 2dp>,
              "by_type": {"instant_transfer": {"count": int, "total_usd": float},
                          "overdraft":         {"count": int, "total_usd": float}},
              "events": [ <up to `limit` ledger fee events, newest first> ],
              "truncated": <bool, True if events were cut by `limit`>,
              "note": <string; when there are no matching events, an explicit
                       sentence the model can relay, e.g. "No instant-transfer
                       fees were charged in the last 90 days.">
            }

        Notes:
            * Read from `self.ledger["fee_events"]`; do not recompute amounts.
            * `total_usd` must cover every filtered event even when truncated,
              otherwise the agent will quote a total that contradicts the
              model's own features.
            * An unrecognised `fee_type` should return a result whose "note"
              explains the valid options, rather than raising.
        """
        raise NotImplementedError("exercise 1")

    def get_advance_history(self) -> dict[str, Any]:
        advances = self.ledger["advances"]
        shown = advances[:MAX_ADVANCES]
        instant = [a for a in advances if a["delivery"] == "instant"]
        return {
            "window_days": 90,
            "advance_count": len(advances),
            "instant_delivery_count": len(instant),
            "standard_delivery_count": len(advances) - len(instant),
            "total_advanced_usd": round(sum(a["amount_usd"] for a in advances), 2),
            "average_advance_usd": round(
                sum(a["amount_usd"] for a in advances) / len(advances), 2
            ) if advances else 0.0,
            "on_time_repayment_rate": round(float(self.user["advance_repaid_on_time_rate"]), 3),
            "advances": shown,
            "truncated": len(advances) > len(shown),
            "note": (
                "No cash advances were taken in the last 90 days."
                if not advances else ""
            ),
        }

    def get_subscription_spend(self) -> dict[str, Any]:
        subs = self.ledger["subscriptions"]
        flagged = [s for s in subs if s["looks_unused"]]
        return {
            "subscription_count": len(subs),
            "monthly_total_usd": round(sum(s["monthly_usd"] for s in subs), 2),
            "flagged_possibly_unused_count": len(flagged),
            "flagged_possibly_unused_monthly_usd": round(
                sum(s["monthly_usd"] for s in flagged), 2
            ),
            "subscriptions": subs,
            "caveat": (
                "'Possibly unused' is a heuristic flag based on charge and "
                "activity patterns. It is not confirmation the user does not "
                "use the service."
            ),
            "note": "No recurring subscriptions were detected." if not subs else "",
        }

    def get_genius_feature_catalog(self) -> dict[str, Any]:
        return catalog.get_catalog()

    def estimate_savings(self, feature_ids: list[str]) -> dict[str, Any]:
        """TODO(exercise): implement.

        Deterministically estimate what the named Genius features would have
        saved THIS user over the last 90 days, based on their own fee history.

        This function exists so the language model never performs arithmetic.
        The model picks which features are worth evaluating; this function
        decides how much they are worth.

        Args:
            feature_ids: catalog feature ids, e.g. ["instant_delivery",
                "overdraft_shield"].

        Per-feature estimation rules (all figures over the trailing 90 days):
            instant_delivery  -> sum of the user's "instant_transfer" fee
                                 events. Genius removes this fee entirely, so
                                 the saving is the full amount.
            overdraft_shield  -> sum of "overdraft" fee events multiplied by
                                 the catalog's `coverage_rate`. The shield
                                 cannot catch every overdraft, so claiming the
                                 full amount would overstate the benefit.
            subscription_watch-> monthly total of subscriptions flagged
                                 `looks_unused`, times 3 months, times the
                                 catalog's `assumed_cancel_rate`. This is a
                                 potential saving, not a realised one.
            smart_savings /
            budget_coach      -> no dollar saving. Return 0.0 with a
                                 `basis` explaining it is not a fee saving.

        Required return shape:
            {
              "window_days": 90,
              "per_feature": [
                 {"feature_id": str,
                  "feature_name": str,          # from the catalog
                  "estimated_saving_usd": float,  # rounded to 2dp
                  "basis": str,                 # plain-language derivation,
                                                # e.g. "9 instant-transfer
                                                # fees at $4.99"
                  "is_estimate": bool},         # True where assumptions were
                                                # applied (shield coverage,
                                                # cancel rate)
                 ...
              ],
              "total_estimated_saving_usd": float,
              "genius_cost_over_window_usd": float,   # monthly price x 3
              "net_position_usd": float,              # savings minus cost
              "unknown_feature_ids": [str],           # ids not in the catalog
              "disclosure": <the catalog's disclosure string>
            }

        Notes:
            * Never raise on an unknown feature id -- report it in
              `unknown_feature_ids` so the model can say it does not know.
            * `net_position_usd` may legitimately be negative. Do not clamp it.
              An honest "this would not pay for itself" is a feature of this
              product, not a bug.
        """
        raise NotImplementedError("exercise 2")

    # -- dispatch ---------------------------------------------------------

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool call and record what it returned.

        Errors are returned as data rather than raised: an agent that receives
        a readable error can recover, whereas an exception kills the turn.
        """
        handler = getattr(self, name, None)
        if handler is None or name not in TOOL_NAMES:
            result = {"error": f"unknown tool '{name}'", "available_tools": sorted(TOOL_NAMES)}
        else:
            try:
                result = handler(**arguments)
            except TypeError as exc:
                result = {"error": f"bad arguments for '{name}': {exc}"}
        self._record_values(result)
        self.call_log.append({"tool": name, "arguments": arguments, "result": result})
        return result

    def _record_values(self, obj: Any) -> None:
        """Walk a tool result and remember every number it contained."""
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            self.value_ledger.add(round(float(obj), 2))
        elif isinstance(obj, dict):
            for v in obj.values():
                self._record_values(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self._record_values(v)


# --- Schemas the model sees ------------------------------------------------
# The description field is prompt engineering. Write it for a capable new hire
# who cannot ask you a follow-up question: what it does, when to use it, and
# when NOT to.

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_account_summary",
        "description": (
            "Get a high-level summary of this user's Albert account: tenure, "
            "whether direct deposit is active, balance profile, and recent app "
            "engagement. Call this first to orient yourself before looking at "
            "fees or advances."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_recent_fees",
        "description": (
            "List the fees this user was actually charged in the last 90 days, "
            "with dates and amounts. This is the primary evidence source for "
            "any claim that Genius would save them money. Use it before "
            "estimating savings. Returns an explicit note when the user has "
            "been charged no fees."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fee_type": {
                    "type": "string",
                    "enum": ["instant_transfer", "overdraft"],
                    "description": "Optional filter. Omit to get all fee types.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum events to return, newest first. Default 25.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_advance_history",
        "description": (
            "Get this user's cash-advance history for the last 90 days: how "
            "many advances, sizes, how many were delivered instantly, and "
            "their on-time repayment rate. Use this to judge whether advance-"
            "related Genius features are relevant to them."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_subscription_spend",
        "description": (
            "Get recurring subscription charges detected on this user's linked "
            "account, including which ones look unused. Use this only when "
            "discussing subscription tracking. The 'possibly unused' flag is a "
            "heuristic -- never state it as fact."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_genius_feature_catalog",
        "description": (
            "Get the official Genius feature list, the monthly price, and the "
            "fees free users pay. This is the ONLY valid source for pricing "
            "and fee amounts. Never state a price or fee that did not come "
            "from this tool."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "estimate_savings",
        "description": (
            "Calculate what specific Genius features would have saved THIS "
            "user over the last 90 days, based on their own fee history. You "
            "must use this tool for every savings figure you state -- do not "
            "do the arithmetic yourself. It also returns what Genius costs "
            "over the same window, so you can tell the user honestly when it "
            "would not pay for itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feature_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Catalog feature ids to evaluate, e.g. "
                        "['instant_delivery', 'overdraft_shield']."
                    ),
                }
            },
            "required": ["feature_ids"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOL_SCHEMAS}
