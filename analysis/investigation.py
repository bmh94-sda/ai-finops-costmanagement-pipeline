# ==============================================================================
# investigation.py
# ------------------------------------------------------------------------------
# PURPOSE: Prove, using only the data (not prior knowledge of what we
# planted), what actually caused the cost-per-request spike in Case Law
# Research Assistant — then quantify a savings recommendation if it were fixed.
#
# This mirrors the real FinOps investigation loop: detect an anomaly ->
# slice the data by different dimensions to isolate the cause -> rule out
# alternative explanations -> quantify a fix -> write a recommendation
# (not a mandate — consistent with an "enablement, not gatekeeping" model).
# ==============================================================================

import sqlite3

import pandas as pd

DB_PATH = "data/warehouse.db"

# ---------------------------------------------------------------------------
# STEP 1 — Read the Gold table and isolate Case Law Research Assistant
# ---------------------------------------------------------------------------
print("Reading Silver-level joined data for investigation...")
conn = sqlite3.connect(DB_PATH)
gold_df = pd.read_sql("SELECT * FROM gold_daily_product_cost", conn)
conn.close()

gold_df["date"] = pd.to_datetime(gold_df["date"])
case_law_df = gold_df[gold_df["product"] == "Case Law Research Assistant"].sort_values("date")

# Average context length (tokens_in) per request, per day — this is the
# metric we'll check against the cost spike to see if they move together.
case_law_df["avg_tokens_in"] = case_law_df["total_tokens_in"] / case_law_df["total_requests"]

# Split the data into "before" and "after" the observed spike date
# (identified visually from the chart in unit_costs.py — day 180 from a
# June 1 start lands around Nov 28).
before = case_law_df[case_law_df["date"] < "2025-11-28"]
after = case_law_df[case_law_df["date"] >= "2025-11-28"]

# ---------------------------------------------------------------------------
# STEP 2 — Test two possible explanations for the cost spike:
#   1. Usage growth (more requests) -- checked via total_requests
#   2. Context length change (longer documents per request) -- checked via avg_tokens_in
# If context length moved a lot but requests barely moved, that points to
# context length as the real driver, not just "the product got more popular."
# ---------------------------------------------------------------------------
print(f"Avg tokens_in per request BEFORE spike: {before['avg_tokens_in'].mean():.0f}")
print(f"Avg tokens_in per request AFTER spike:  {after['avg_tokens_in'].mean():.0f}")
print(f"Avg requests/day BEFORE spike: {before['total_requests'].mean():.0f}")
print(f"Avg requests/day AFTER spike:  {after['total_requests'].mean():.0f}")

# ---------------------------------------------------------------------------
# STEP 3 — Quantify the savings opportunity: if context length were
# restored to its pre-spike level, what would cost per request be instead,
# and how much would that save per year at current volume?
# ---------------------------------------------------------------------------
avg_tokens_before = before["avg_tokens_in"].mean()
avg_tokens_after = after["avg_tokens_in"].mean()
avg_requests_after = after["total_requests"].mean()
avg_ai_cost_per_request_after = (after["total_ai_cost"] / after["total_requests"]).mean()

# What fraction would cost drop by, if tokens returned to their old level?
token_reduction_ratio = avg_tokens_before / avg_tokens_after
estimated_cost_per_request_if_fixed = avg_ai_cost_per_request_after * token_reduction_ratio

# Savings per request x current daily volume x 365 days = estimated annual savings.
daily_savings = (avg_ai_cost_per_request_after - estimated_cost_per_request_if_fixed) * avg_requests_after
annual_savings = daily_savings * 365

print(f"\nCurrent avg AI cost per request: ${avg_ai_cost_per_request_after:.4f}")
print(f"Estimated cost per request if context length were restored: ${estimated_cost_per_request_if_fixed:.4f}")
print(f"Estimated daily savings: ${daily_savings:.2f}")
print(f"Estimated ANNUAL savings if fixed: ${annual_savings:,.2f}")

# A percentage framing is often more compelling in a narrative than a
# modest absolute dollar figure, and is equally accurate.
pct_reduction = (1 - token_reduction_ratio) * 100
print(f"\nThis represents a {pct_reduction:.1f}% reduction in AI cost per request for this product.")