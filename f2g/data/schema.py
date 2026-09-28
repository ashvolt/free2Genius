"""Column groups shared by the generator, the feature pipeline and the API.

Pure data, no logic, no I/O — so a test can import it to assert the leakage
invariant without constructing anything.
"""
from __future__ import annotations

# Numeric behavioural features observed in the 90 days before the nudge window.
NUMERIC_FEATURES = [
    "tenure_days",
    "dd_consecutive_months",
    "dd_amount_monthly",
    "advances_90d",
    "advance_amount_avg",
    "advance_repaid_on_time_rate",
    "instant_transfer_fees_90d",
    "overdraft_fees_90d",
    "budget_sessions_30d",
    "budget_categories_tracked",
    "app_opens_30d",
    "days_since_last_open",
    "savings_balance",
    "recurring_subscriptions_count",
    "recurring_subscription_spend",
    "low_balance_days_30d",
    "avg_daily_balance",
    "prior_upsell_views_90d",
    "support_contacts_90d",
]

BINARY_FEATURES = [
    "direct_deposit_active",
    "savings_auto_enabled",
    "push_enabled",
]

CATEGORICAL_FEATURES = [
    "income_band",
    "age_band",
    "platform",
    "acquisition_channel",
]

FEATURES = NUMERIC_FEATURES + BINARY_FEATURES + CATEGORICAL_FEATURES

# Never fed to a model: outcomes, and the simulation's private variables.
# `f2g.ml.features` refuses to build a pipeline containing any of these, and
# `tests/test_no_leakage.py` asserts the sets stay disjoint.
LABEL_COLUMNS = ["treated", "converted", "retained_30d"]
ORACLE_COLUMNS = ["segment", "true_tau", "p0", "value_fit"]

# Event counts the ledger needs to reconcile exactly against the aggregates.
# Underscore-prefixed so they read as internal and never drift into FEATURES.
INTERNAL_COLUMNS = ["_instant_transfer_count_90d", "_overdraft_count_90d"]

INCOME_BANDS = ["lt_25k", "25_50k", "50_75k", "75k_plus"]
AGE_BANDS = ["18_24", "25_34", "35_49", "50_plus"]
PLATFORMS = ["ios", "android"]
ACQUISITION_CHANNELS = ["organic", "paid_social", "referral", "app_store_search"]

# Sentinel for an outcome that has not been observed. Chosen over NaN because
# NaN vanishes silently from a mean() while -1 produces an obviously wrong
# number a test will catch.
UNOBSERVED = -1
