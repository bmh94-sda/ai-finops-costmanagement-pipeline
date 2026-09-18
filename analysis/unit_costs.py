# ==============================================================================
# unit_costs.py
# ------------------------------------------------------------------------------
# PURPOSE: Read the final Gold table and build the key unit-cost chart that
# proves the core FinOps concept: total cost rising isn't automatically bad —
# only a UNIT-cost metric (cost per request) can tell you whether it's
# healthy usage growth or a real efficiency problem.
#
# This file also demonstrates an important real-world lesson: a BLENDED
# cost-per-request metric (AI cost + shared infra cost combined) completely
# hid the planted anomaly, because shared infrastructure cost dominates the
# total for this product. Only by isolating ai_cost_per_request specifically
# did the anomaly become visible — mirroring a genuine FinOps investigation
# challenge.
# ==============================================================================

import sqlite3

import matplotlib.pyplot as plt
import pandas as pd

DB_PATH = "data/warehouse.db"

# ---------------------------------------------------------------------------
# STEP 1 — Read the Gold table back out of the database
# ---------------------------------------------------------------------------
print("Reading Gold table...")
conn = sqlite3.connect(DB_PATH)
gold_df = pd.read_sql("SELECT * FROM gold_daily_product_cost", conn)
conn.close()

# SQLite has no true date type, so "date" comes back as plain text —
# convert it back into a real date object so matplotlib can draw a proper
# chronological x-axis.
gold_df["date"] = pd.to_datetime(gold_df["date"])

print(f"gold_daily_product_cost -> {len(gold_df):,} rows loaded")
print(gold_df.head())

# ---------------------------------------------------------------------------
# STEP 2 — Calculate an AI-cost-specific unit metric.
# NOTE: gold_df already has "cost_per_request" (a BLENDED metric including
# allocated cloud cost). That blended version turned out to hide the
# anomaly, since cloud cost dominates the total for this product. This new
# column isolates just the AI/token-driven cost, which reveals the anomaly
# clearly.
# ---------------------------------------------------------------------------
gold_df["ai_cost_per_request"] = gold_df["total_ai_cost"] / gold_df["total_requests"]

# ---------------------------------------------------------------------------
# STEP 3 — Build the chart: AI cost per request over time, for Case Law
# Research Assistant specifically (the product with the planted anomaly).
# ---------------------------------------------------------------------------
print("Building AI-cost-per-request chart for Case Law Research Assistant...")

case_law_df = gold_df[gold_df["product"] == "Case Law Research Assistant"].sort_values("date")

plt.figure(figsize=(12, 5))
plt.plot(case_law_df["date"], case_law_df["ai_cost_per_request"], color="#2E5AAC")
plt.title("Case Law Research Assistant — AI Cost per Request Over Time")
plt.xlabel("Date")
plt.ylabel("AI Cost per Request ($)")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("analysis/ai_cost_per_request_chart.png")
print("Chart saved to analysis/ai_cost_per_request_chart.png")