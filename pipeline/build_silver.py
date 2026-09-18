# ==============================================================================
# build_silver.py
# ------------------------------------------------------------------------------
# PURPOSE: Read the 3 raw Bronze tables from warehouse.db, join and clean them
# into a trustworthy "Silver" dataset, allocate shared cloud costs fairly
# across products, then aggregate everything into a final "Gold" table ready
# for analysis and dashboarding.
#
# This single file covers both the Silver layer (join + cleaning + cost
# allocation) and the Gold layer (final aggregated summary table) since the
# Gold step directly depends on variables built earlier in this same script.
# ==============================================================================

import sqlite3

import pandas as pd

DB_PATH = "data/warehouse.db"

# ---------------------------------------------------------------------------
# STEP 1 — Read the raw Bronze tables back out of the database
# ---------------------------------------------------------------------------
print("Connecting to database...")
conn = sqlite3.connect(DB_PATH)

provider_df = pd.read_sql("SELECT * FROM bronze_provider_usage_log", conn)
internal_df = pd.read_sql("SELECT * FROM bronze_internal_feature_log", conn)
cloud_df = pd.read_sql("SELECT * FROM bronze_cloud_billing_log", conn)

print(f"bronze_provider_usage_log   -> {len(provider_df):,} rows loaded")
print(f"bronze_internal_feature_log -> {len(internal_df):,} rows loaded")
print(f"bronze_cloud_billing_log    -> {len(cloud_df):,} rows loaded")

# ---------------------------------------------------------------------------
# STEP 2 — SILVER: Join provider log + internal log on request_id
# This is the core "attribution" join: matching what the AI provider billed
# with which product/team caused it, using the shared request_id as the key
# (same concept as VLOOKUP matching two spreadsheets on a shared column).
# ---------------------------------------------------------------------------
print("Joining provider and internal logs on request_id...")

joined_df = pd.merge(
    provider_df,
    internal_df,
    on="request_id",
    how="inner",   # only keep rows where request_id exists in BOTH tables
)

print(f"Joined table -> {len(joined_df):,} rows")
print(f"Columns: {list(joined_df.columns)}")

# Both source tables had a "timestamp" column, so pandas auto-renamed them
# to timestamp_x / timestamp_y to avoid a clash. Since both represent the
# same moment, we keep one and drop the duplicate.
joined_df = joined_df.rename(columns={"timestamp_x": "timestamp"})
joined_df = joined_df.drop(columns=["timestamp_y"])

print(f"Cleaned columns: {list(joined_df.columns)}")
print(joined_df.head(10))


# ---------------------------------------------------------------------------
# STEP 3 — Data quality checks
# Real pipelines never blindly trust data, even data they generated
# themselves. These checks catch obviously broken rows before they flow
# downstream into any analysis or dashboard.
# ---------------------------------------------------------------------------
print("Running data quality checks...")
missing_request_id = joined_df["request_id"].isna().sum()
negative_tokens = (joined_df["tokens_in"] < 0).sum() + (joined_df["tokens_out"] < 0).sum()
negative_cost = (joined_df["cost_usd"] < 0).sum()

print(f"Rows with missing request_id: {missing_request_id}")
print(f"Rows with negative token counts: {negative_tokens}")
print(f"Rows with negative cost: {negative_cost}")

if missing_request_id > 0 or negative_tokens > 0 or negative_cost > 0:
    print("WARNING: data quality issues found — review before proceeding.")
else:
    print("Data quality checks passed. No issues found.")

# ---------------------------------------------------------------------------
# STEP 4 — SHARED COST ALLOCATION (part 1): calculate each product's daily
# "share" of total activity.
#
# WHY: cloud_billing_log has no request_id — it's a lump-sum cost per
# service per day, not tied to any single product. To attribute it fairly,
# we first need to know what % of each day's total usage belonged to each
# product, then use that % to split the shared cost proportionally.
# ---------------------------------------------------------------------------
print("Calculating daily request volume per product (for cost allocation)...")
joined_df["date"] = pd.to_datetime(joined_df["timestamp"]).dt.date

# Count requests per (date, product) combination.
daily_product_counts = joined_df.groupby(["date", "product"]).size().reset_index(name="daily_requests")
# Count TOTAL requests per date, across all products combined.
daily_totals = joined_df.groupby("date").size().reset_index(name="total_requests_that_day")

# Attach each day's grand total onto every product-day row, then calculate
# what fraction of that day's activity belongs to each product.
daily_product_counts = daily_product_counts.merge(daily_totals, on="date")
daily_product_counts["request_share"] = (
    daily_product_counts["daily_requests"] / daily_product_counts["total_requests_that_day"]
)
print(daily_product_counts.head(10))

# ---------------------------------------------------------------------------
# STEP 5 — SHARED COST ALLOCATION (part 2): apply the % share to actually
# split each day's real cloud bill across the 3 products.
# ---------------------------------------------------------------------------
print("Allocating shared cloud costs to products...")
# cloud_df has 4 rows per day (one per service) — sum them into one
# total cloud cost per day, since we're allocating the whole day's bill.
daily_cloud_totals = cloud_df.groupby("date")["daily_cost_usd"].sum().reset_index(name="total_cloud_cost")
daily_cloud_totals["date"] = pd.to_datetime(daily_cloud_totals["date"]).dt.date

allocation_df = daily_product_counts.merge(daily_cloud_totals, on="date")
# Each product's slice of the shared bill = its % share of that day's usage.
allocation_df["allocated_cloud_cost"] = (
    allocation_df["request_share"] * allocation_df["total_cloud_cost"]
)

print(allocation_df.head(9))

# ---------------------------------------------------------------------------
# STEP 6 — GOLD (part 1): aggregate the detailed, request-level joined data
# down to one row per (date, product) — matching the same granularity as
# our allocation table, ready to be merged together.
# ---------------------------------------------------------------------------
print("Aggregating AI usage costs to daily/product level...")

daily_ai_costs = joined_df.groupby(["date", "product", "team"]).agg(
    total_requests=("request_id", "count"),
    total_tokens_in=("tokens_in", "sum"),
    total_tokens_out=("tokens_out", "sum"),
    total_ai_cost=("cost_usd", "sum"),
).reset_index()

print(daily_ai_costs.head(9))

# ---------------------------------------------------------------------------
# STEP 6b — Aggregate by MODEL as well, for a "cost by model" chart in
# Tableau. This is separate from the Gold table since Gold is organized by
# product/day, not by model.
# ---------------------------------------------------------------------------
print("Aggregating AI costs by model...")

model_costs = joined_df.groupby(["product", "model"]).agg(
    total_requests=("request_id", "count"),
    total_ai_cost=("cost_usd", "sum"),
).reset_index()

model_costs.to_csv("data/model_costs.csv", index=False)
print(f"model_costs.csv -> {len(model_costs):,} rows exported")
print(model_costs)

# ---------------------------------------------------------------------------
# STEP 7 — GOLD (part 2): merge AI costs + allocated cloud costs into ONE
# final table, and calculate the headline unit-cost metric.
# ---------------------------------------------------------------------------
print("Building final Gold table...")

gold_df = daily_ai_costs.merge(
    allocation_df[["date", "product", "allocated_cloud_cost"]],
    on=["date", "product"],
)

gold_df["total_cost"] = gold_df["total_ai_cost"] + gold_df["allocated_cloud_cost"]
# Our first real unit-cost metric: total cost / number of requests.
# NOTE: this BLENDED metric can hide problems if one cost driver (e.g.
# shared infra) dominates another (e.g. AI cost) — see unit_costs.py /
# investigation.py, where we had to isolate ai_cost_per_request separately
# to actually see the planted anomaly clearly.
gold_df["cost_per_request"] = gold_df["total_cost"] / gold_df["total_requests"]

print(gold_df.head(9))

# ---------------------------------------------------------------------------
# STEP 8 — Save the Gold table to the database, ready for analysis/dashboarding.
# Reuses the SAME `conn` opened at the very top of this file — opening a
# second connection here caused a "database is locked" error.
# ---------------------------------------------------------------------------
print("Saving Gold table to database...")

gold_df.to_sql("gold_daily_product_cost", conn, if_exists="replace", index=False)
conn.close()

print(f"gold_daily_product_cost -> {len(gold_df):,} rows saved.")
print("Silver and Gold layers complete.")