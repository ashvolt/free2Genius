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

import re
from typing import Any

from f2g.data import catalog
from f2g.data.accounts import build_ledger, repository

_NUMERIC_IN_TEXT = re.compile(r"\d[\d,]*(?:\.\d+)?")

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
        """Fee events charged to this user in the last 90 days.

        The primary evidence source: every savings claim the agent makes traces
        back to rows returned here.

        Note that `total_usd` covers every matching event, not just the page
        returned under `limit`. Summing only the returned page would let the
        agent quote a total that contradicts the aggregate the model scored the
        same user on — detail and headline disagreeing about one user is the
        failure this tool exists to avoid.
        """
        events = self.ledger["fee_events"]
        valid_types = {"instant_transfer", "overdraft"}

        if fee_type is not None and fee_type not in valid_types:
            return {
                "window_days": 90,
                "as_of": self.ledger["as_of"],
                "fee_type_filter": fee_type,
                "event_count": 0,
                "total_usd": 0.0,
                "by_type": {t: {"count": 0, "total_usd": 0.0} for t in sorted(valid_types)},
                "events": [],
                "truncated": False,
                "note": (
                    f"'{fee_type}' is not a fee type on this account. "
                    f"Valid fee types are: {', '.join(sorted(valid_types))}."
                ),
            }

        matching = [e for e in events if fee_type is None or e["type"] == fee_type]
        by_type = {
            t: {
                "count": sum(1 for e in matching if e["type"] == t),
                "total_usd": round(sum(e["amount_usd"] for e in matching if e["type"] == t), 2),
            }
            for t in sorted(valid_types)
        }
        shown = matching[:limit]

        if not matching:
            scope = "fees" if fee_type is None else f"{fee_type.replace('_', '-')} fees"
            note = f"No {scope} were charged in the last 90 days."
        else:
            note = ""

        return {
            "window_days": 90,
            "as_of": self.ledger["as_of"],
            "fee_type_filter": fee_type or "all",
            "event_count": len(matching),
            "total_usd": round(sum(e["amount_usd"] for e in matching), 2),
            "by_type": by_type,
            "events": shown,
            "truncated": len(matching) > len(shown),
            "note": note,
        }

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
        """What the named Genius features would have saved THIS user, in Python.

        This function exists so the language model never performs arithmetic on
        money. The model chooses which features are worth evaluating; this
        decides how much they are worth. That split removes the largest
        hallucination class in a financial agent: a model multiplying $4.99 by
        nine advances and getting it wrong is a compliance incident, whereas
        this getting it wrong is a unit test.

        Estimates are deliberately conservative — the overdraft shield cannot
        catch every overdraft, and a flagged subscription is not a cancelled
        one — so the value-fit gate in feature 003 errs toward suppression.
        """
        fees = self.ledger["fee_events"]
        instant_total = round(
            sum(e["amount_usd"] for e in fees if e["type"] == "instant_transfer"), 2
        )
        instant_count = sum(1 for e in fees if e["type"] == "instant_transfer")
        overdraft_total = round(sum(e["amount_usd"] for e in fees if e["type"] == "overdraft"), 2)
        overdraft_count = sum(1 for e in fees if e["type"] == "overdraft")

        flagged = [s for s in self.ledger["subscriptions"] if s["looks_unused"]]
        flagged_monthly = round(sum(s["monthly_usd"] for s in flagged), 2)

        per_feature: list[dict[str, Any]] = []
        unknown: list[str] = []

        for fid in feature_ids:
            feature = catalog.get_feature(fid)
            if feature is None:
                unknown.append(fid)
                continue

            components: dict[str, Any] = {}
            if fid == "instant_delivery":
                amount, is_estimate = instant_total, False
                unit = feature["unit_saving"]
                components = {"fee_count": instant_count, "unit_fee_usd": unit,
                              "fee_total_usd": instant_total}
                basis = (
                    f"{instant_count} express-delivery "
                    f"{'fee' if instant_count == 1 else 'fees'} at ${unit:.2f} each"
                    if instant_count
                    else "no express-delivery fees were charged in the last 90 days"
                )
            elif fid == "overdraft_shield":
                coverage = feature["coverage_rate"]
                amount, is_estimate = round(overdraft_total * coverage, 2), True
                components = {"fee_count": overdraft_count, "fee_total_usd": overdraft_total,
                              "coverage_rate": coverage}
                basis = (
                    f"{overdraft_count} overdraft "
                    f"{'fee' if overdraft_count == 1 else 'fees'} totalling "
                    f"${overdraft_total:.2f}, of which the shield is assumed to prevent "
                    f"{coverage:.0%}"
                    if overdraft_count
                    else "no overdraft fees were charged in the last 90 days"
                )
            elif fid == "subscription_watch":
                rate = feature["assumed_cancel_rate"]
                amount, is_estimate = round(flagged_monthly * 3 * rate, 2), True
                components = {"flagged_count": len(flagged),
                              "flagged_monthly_usd": flagged_monthly,
                              "months": 3, "assumed_cancel_rate": rate}
                basis = (
                    f"{len(flagged)} subscription(s) flagged as possibly unused at "
                    f"${flagged_monthly:.2f} per month over 3 months, assuming "
                    f"{rate:.0%} are actually cancelled"
                    if flagged
                    else "no subscriptions were flagged as possibly unused"
                )
            else:
                # smart_savings and budget_coach are real features with no fee
                # saving. Reporting 0.0 with a reason is more useful than
                # omitting them, because the agent can still explain them.
                amount, is_estimate = 0.0, False
                basis = "this feature does not reduce fees; it is not a monetary saving"

            per_feature.append(
                {
                    "feature_id": fid,
                    "feature_name": feature["name"],
                    "estimated_saving_usd": amount,
                    "basis": basis,
                    # Every number that appears in `basis` also appears here as a
                    # numeric field. `basis` is a convenience for a human reader;
                    # these are what the value ledger records, so a figure quoted
                    # from the derivation is grounded rather than blocked.
                    "components": components,
                    "is_estimate": is_estimate,
                }
            )

        total = round(sum(f["estimated_saving_usd"] for f in per_feature), 2)
        cost = round(catalog.GENIUS_MONTHLY_PRICE * 3, 2)

        return {
            "window_days": 90,
            "per_feature": per_feature,
            "total_estimated_saving_usd": total,
            "genius_cost_over_window_usd": cost,
            # Deliberately not clamped at zero. A negative net position is the
            # honest answer for many users, and being able to say so is the
            # reason this product is defensible.
            "net_position_usd": round(total - cost, 2),
            "unknown_feature_ids": unknown,
            "disclosure": catalog.get_catalog()["disclosure"],
        }

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

    def provenance(self, value: float) -> list[str]:
        """Which tool call(s) returned this numeric value.

        Powers the evidence chips in the console: a reader clicks a dollar
        figure and sees the call that produced it. Grounding you can *inspect*
        is far more convincing than grounding you are told about.
        """
        target = round(float(value), 2)
        hits: list[str] = []
        for entry in self.call_log:
            found: set[float] = set()
            self._walk(entry["result"], found)
            if target in found:
                hits.append(entry["tool"])
        return hits

    @classmethod
    def _walk(cls, obj: Any, sink: set[float]) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            sink.add(round(float(obj), 2))
        elif isinstance(obj, str):
            for token in _NUMERIC_IN_TEXT.findall(obj):
                try:
                    sink.add(round(float(token.replace(",", "")), 2))
                except ValueError:
                    continue
        elif isinstance(obj, dict):
            for v in obj.values():
                cls._walk(v, sink)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                cls._walk(v, sink)

    def _record_values(self, obj: Any) -> None:
        """Walk a tool result and remember every number it contained.

        Numbers inside returned *strings* are recorded too. That is safe, and
        deliberately so: every string in a tool result is produced by this
        module's own Python from the user's real account data, never by the
        language model. A figure the model quotes out of a tool's own
        explanation is therefore grounded, and blocking it would be a false
        positive. The model can still never introduce a number of its own,
        because it cannot write into a tool result.
        """
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            self.value_ledger.add(round(float(obj), 2))
        elif isinstance(obj, str):
            for token in _NUMERIC_IN_TEXT.findall(obj):
                try:
                    self.value_ledger.add(round(float(token.replace(",", "")), 2))
                except ValueError:
                    continue
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
                    # Enumerating the catalog ids here is not documentation: the
                    # grammar generator turns an enum into literal alternatives,
                    # so the model physically cannot emit a feature that does not
                    # exist. A hallucinated product feature is prevented at the
                    # decoder rather than caught downstream.
                    "items": {"type": "string", "enum": sorted(catalog.FEATURE_IDS)},
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
