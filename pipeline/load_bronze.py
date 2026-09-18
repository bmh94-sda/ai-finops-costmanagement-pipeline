# ==============================================================================
# load_bronze.py
# ------------------------------------------------------------------------------
# PURPOSE: Load the 3 raw synthetic CSVs (created by generate_data.py) into a
# local SQLite database, completely UNTOUCHED — no cleaning, no joining here.
#
# This is the "Bronze" layer of a Bronze -> Silver -> Gold pipeline: raw data
# lands exactly as received, acting as a safety net (the original data is
# always recoverable) before any transformation happens in later steps.
# ==============================================================================

import sqlite3

import pandas as pd

DB_PATH = "data/warehouse.db"

# ---------------------------------------------------------------------------
# STEP 1 — Read the raw CSVs exactly as generated (no changes made here)
# ---------------------------------------------------------------------------
print("Reading raw CSV files...")

provider_df = pd.read_csv("data/provider_usage_log.csv")
internal_df = pd.read_csv("data/internal_feature_log.csv")
cloud_df = pd.read_csv("data/cloud_billing_log.csv")

print(f"provider_usage_log.csv   -> {len(provider_df):,} rows read")
print(f"internal_feature_log.csv -> {len(internal_df):,} rows read")
print(f"cloud_billing_log.csv    -> {len(cloud_df):,} rows read")

# ---------------------------------------------------------------------------
# STEP 2 — Write each raw table into the SQLite database, untouched.
# If warehouse.db doesn't exist yet, sqlite3.connect() creates it automatically.
# ---------------------------------------------------------------------------
print(f"Connecting to database at {DB_PATH}...")
conn = sqlite3.connect(DB_PATH)

# "bronze_" prefix makes it immediately obvious which layer this data
# belongs to, once Silver/Gold tables are added to the same database file.
provider_df.to_sql(
    "bronze_provider_usage_log",
    conn,
    if_exists="replace",  # safely overwrite if this script runs again later
    index=False,           # don't save pandas' internal row-number index as a column
)
internal_df.to_sql("bronze_internal_feature_log", conn, if_exists="replace", index=False)
cloud_df.to_sql("bronze_cloud_billing_log", conn, if_exists="replace", index=False)

print("All 3 tables written to Bronze layer.")

conn.close()
print("Database connection closed. Bronze layer complete.")