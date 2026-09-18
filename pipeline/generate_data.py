# ==============================================================================
# generate_data.py
# ------------------------------------------------------------------------------
# PURPOSE: Generate 3 synthetic (fake but realistic) CSV files simulating
# what a legal-AI company's raw cost/usage data would look like:
#   1. provider_usage_log.csv   -> what the AI provider (Anthropic/OpenAI/etc.) bills
#   2. internal_feature_log.csv -> what our own app logged internally
#   3. cloud_billing_log.csv    -> itemized daily cloud infrastructure costs
#
# ALL DATA IS SYNTHETIC. No real company data is used or referenced.
# This is the "Bronze" raw material every later pipeline step builds on.
# ==============================================================================

import random
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Fixing the random "seed" makes our randomness REPRODUCIBLE — running this
# script again always produces the exact same fake data, instead of different
# random data every time. Needed because random and numpy have separate,
# independent randomness systems, so both must be seeded separately.
random.seed(42)
np.random.seed(42)


# Sets up logging so the script prints timestamped progress messages while running
# (mainly useful for watching a long-running loop like this one work in real time).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIG
# All the "facts about our simulated world" — decided once, used everywhere
# below. Change values here, not inside the loop logic.
# ---------------------------------------------------------------------------
START_DATE = datetime(2025, 6, 1)     # start date of simulated data
NUM_DAYS = 365                         # a full year of data
ANOMALY_START_DAY = 180                # deliberately-planted cost anomaly starts here
                                        # (used later to simulate a real-world
                                        # context-length regression to investigate)

# Our 3 fake legal-AI products, each with its own usage profile.
# "team" = which internal team OWNS/builds this product (not who uses it).
# "model_mix" = which AI models this product uses, and in what proportion
#               (each product's weights must add up to 1.0 / 100%).
# "tokens_in_range"/"tokens_out_range" = realistic min/max text length per request.
# "agentic" = True means each user action triggers MULTIPLE chained AI calls
#             (e.g. search -> analyze -> draft), not just one.
PRODUCTS = {
    "Contract Summarizer": {
        "team": "Contracts Platform",
        "base_requests_per_day": 350,
        "model_mix": {"claude-opus-5": 0.55, "claude-sonnet-5": 0.30, "gemini-3.1-pro": 0.15},
        "tokens_in_range": (8000, 16000),   # long documents -> high tokens_in
        "tokens_out_range": (400, 900),
        "agentic": False,
    },
    "Case Law Research Assistant": {
        "team": "Research Products",
        "base_requests_per_day": 750,
        "model_mix": {"gemini-3.1-pro": 0.4, "deepseek-v4-flash": 0.4, "claude-sonnet-5": 0.2},
        "tokens_in_range": (1500, 4000),    # short questions -> low tokens_in
        "tokens_out_range": (300, 700),
        "agentic": False,
    },
    "Document Drafting Agent": {
        "team": "Drafting & Review",
        "base_requests_per_day": 220,
        "model_mix": {"claude-opus-5": 0.7, "claude-sonnet-5": 0.15, "gpt-5.6-luna": 0.15},
        "tokens_in_range": (2000, 5000),
        "tokens_out_range": (600, 1500),
        "agentic": True,   # this product simulates chained/multi-step AI calls
    },
}

# The 4 real AWS cost categories we're simulating, and each one's baseline
# daily dollar cost. This is SHARED infrastructure cost — NOT tied to any
# single request, which is intentional (mirrors the real-world "shared cost
# allocation" problem: cloud bills don't know how to split themselves fairly
# across products, an analyst has to calculate that).
CLOUD_SERVICES: dict[str, float] = {
    "compute": 220.0,
    "storage": 55.0,
    "data_transfer": 30.0,
    "database": 75.0,
}

# Real, current model pricing (as of Sept 2026), converted from published
# $-per-1-million-token rates down to $-per-1,000-tokens (easier for per-request math).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5":     {"in": 0.0050, "out": 0.0250},
    "claude-sonnet-5":   {"in": 0.0020, "out": 0.0100},
    "gemini-3.1-pro":    {"in": 0.0020, "out": 0.0120},
    "deepseek-v4-flash": {"in": 0.00044, "out": 0.00132},
    "gpt-5.6-luna":      {"in": 0.0002, "out": 0.0012},
}

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# Small, reusable, single-purpose tools — written once here, called
# repeatedly inside the big loop below. Keeping these separate makes the
# main loop easier to read and avoids repeating the same logic many times.
# ---------------------------------------------------------------------------
def sample_token_count(low: int, high: int) -> int:
    """
    Generate a realistic random token count between `low` and `high`.

    Uses a triangular distribution, which weights results toward the
    midpoint rather than spreading them evenly — mirroring how document
    lengths cluster around a typical size in the real world, with only
    occasional very short or very long documents.

    Args:
        low: minimum plausible token count.
        high: maximum plausible token count.

    Returns:
        A single realistic token count as an integer.
    """
    midpoint = (low + high) / 2
    return int(np.random.triangular(low, midpoint, high))


def pick_weighted_model(model_mix: dict[str, float]) -> str:
    """
    Randomly select one model name, respecting the given probability weights.
    (e.g. a model with weight 0.55 gets picked ~55% of the time, not evenly.)

    Args:
        model_mix: a dict mapping model name -> probability (weights should sum to 1.0),
                    e.g. {"claude-opus-5": 0.55, "claude-sonnet-5": 0.30, "gemini-3.1-pro": 0.15}

    Returns:
        One model name, chosen randomly according to the given weights.
    """
    models = list(model_mix.keys())
    weights = list(model_mix.values())
    # random.choices() always returns a LIST even when k=1, so [0] unwraps
    # the single value out of that list.
    return random.choices(models, weights=weights, k=1)[0]


def make_request_id(counter: int) -> str:
    """
    Create a unique, zero-padded request ID string from a running counter.
    This is the SHARED JOIN KEY that later lets us match rows between
    provider_usage_log.csv and internal_feature_log.csv (same concept as
    VLOOKUP matching two Excel sheets on a shared ID column).

    Args:
        counter: a unique integer, typically an ever-increasing counter
                  tracked across the whole data generation process.

    Returns:
        A formatted request ID string, e.g. "req_00000001".
    """
    return f"req_{counter:08d}"


# ---------------------------------------------------------------------------
# MAIN GENERATION LOOP
# The real engine: loops through every day -> every product -> every
# individual request, using the config and helper functions above to build
# each row, then collects everything into 3 lists (our "buckets") ready to
# be saved as CSVs at the very end.
# ---------------------------------------------------------------------------

# Empty "buckets" that will collect one dictionary (= one row) per request.
provider_rows: list[dict] = []
internal_rows: list[dict] = []
cloud_rows: list[dict] = []

# Lives OUTSIDE the loop on purpose, so it counts continuously across the
# entire year instead of resetting to 1 every day (which would create
# duplicate IDs and break the join later).
request_counter = 1

# Outer loop: one iteration per simulated day (365 total).
for day_index in range(NUM_DAYS):
    current_date = START_DATE + timedelta(days=day_index)
    logger.info(f"Generating day {day_index + 1}/{NUM_DAYS} — {current_date.date()}")

    # Tracks total requests across ALL products today — used below to scale
    # the shared cloud cost (more usage that day -> higher cloud cost).
    total_requests_today = 0

    # Middle loop: one iteration per product (3 total), each day.
    for product_name, cfg in PRODUCTS.items():
        # Simulates organic usage growth over the year: request volume
        # slowly climbs (up to +50% by the final day) rather than staying flat.
        growth_factor = 1 + (day_index / NUM_DAYS) * 0.5
        # Adds a small +/-10% random daily wobble on top of the growth trend,
        # so volume isn't a perfectly smooth curve (real usage is noisy).
        daily_requests = int(cfg["base_requests_per_day"] * growth_factor * np.random.uniform(0.9, 1.1))

        # Inner loop: one iteration per individual request, for this
        # product, on this day (this is where each real data row gets built).
        for _ in range(daily_requests):
            model = pick_weighted_model(cfg["model_mix"])

            tokens_in_low, tokens_in_high = cfg["tokens_in_range"]

            # --- DELIBERATELY INJECTED ANOMALY ---
            # Starting at ANOMALY_START_DAY, Case Law Research Assistant's
            # token range is multiplied by 2.1x, simulating a real-world
            # regression (e.g. the system stopped filtering documents down
            # to relevant excerpts, and started sending much more raw text
            # per request). This is the "problem" the later analysis
            # (investigation.py) is designed to find and explain.
            if product_name == "Case Law Research Assistant" and day_index >= ANOMALY_START_DAY:
                tokens_in_low *= 2.1
                tokens_in_high *= 2.1

            tokens_in = sample_token_count(tokens_in_low, tokens_in_high)
            tokens_out = sample_token_count(*cfg["tokens_out_range"])

            request_id = make_request_id(request_counter)
            request_counter += 1
            total_requests_today += 1

            # Cost math: (tokens / 1000) * price-per-1000-tokens, for both
            # input and output tokens, summed together.
            price = MODEL_PRICING[model]
            cost_usd = round(
                (tokens_in / 1000) * price["in"] + (tokens_out / 1000) * price["out"], 6
            )

            # Gives each request a realistic timestamp during business hours
            # (7am-8pm) rather than literally midnight every time.
            request_timestamp = current_date + timedelta(
                hours=int(np.random.uniform(7, 20)), minutes=int(np.random.uniform(0, 59))
            )

            # Row for provider_usage_log.csv — what the AI PROVIDER would bill.
            # Notice it does NOT include product/team — the provider has no
            # knowledge of which internal feature made the call.
            provider_rows.append({
                "request_id": request_id,
                "timestamp": request_timestamp,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
            })

            # Row for internal_feature_log.csv — what OUR OWN SYSTEM logged.
            # Shares the SAME request_id as the row above — this is the link
            # that lets us JOIN these two files together later in the pipeline.
            internal_rows.append({
                "request_id": request_id,
                "timestamp": request_timestamp,
                "product": product_name,
                "team": cfg["team"],
            })

    # Cloud billing runs ONCE PER DAY (outside the product/request loops),
    # since AWS bills per day/service, not per individual request.
    for service, base_cost in CLOUD_SERVICES.items():
        # Scales cost roughly with how busy the day was overall.
        volume_scale = total_requests_today / 1000.0

        if service == "compute":
            # Compute cost has a floor (max(volume_scale, 0.7)) — simulating
            # real-world over-provisioning: servers running even on quiet
            # days, not scaling all the way down with low traffic. This is
            # a deliberate "rightsizing" finding, a real cloud-cost-
            # management concept, built into the simulated data on purpose.
            daily_cost = base_cost * max(volume_scale, 0.7) * np.random.uniform(0.95, 1.05)
        else:
            daily_cost = base_cost * volume_scale * np.random.uniform(0.9, 1.1)

        # This log has NO request_id — it's a shared, lump-sum daily cost,
        # not tied to any single product. This is intentional: it's what
        # forces the later pipeline to use "shared cost allocation" logic
        # (splitting this fairly by usage %) instead of a simple join.
        cloud_rows.append({
            "date": current_date.date(),
            "service": service,
            "daily_cost_usd": round(daily_cost, 2),
        })

# ---------------------------------------------------------------------------
# SAVE TO CSV
# Converts our 3 "bucket" lists into proper tables (DataFrames), then
# writes each one out to an actual CSV file in the data/ folder.
# ---------------------------------------------------------------------------
provider_df = pd.DataFrame(provider_rows)
internal_df = pd.DataFrame(internal_rows)
cloud_df = pd.DataFrame(cloud_rows)

provider_df.to_csv("data/provider_usage_log.csv", index=False)
internal_df.to_csv("data/internal_feature_log.csv", index=False)
cloud_df.to_csv("data/cloud_billing_log.csv", index=False)

logger.info(f"provider_usage_log.csv   -> {len(provider_df):,} rows")
logger.info(f"internal_feature_log.csv -> {len(internal_df):,} rows")
logger.info(f"cloud_billing_log.csv    -> {len(cloud_df):,} rows")
logger.info("Data generation complete.")