import sqlite3

import pandas as pd

DB_PATH = "data/warehouse.db"

print("Reading Gold table...")
conn = sqlite3.connect(DB_PATH)
gold_df = pd.read_sql("SELECT * FROM gold_daily_product_cost", conn)
conn.close()

gold_df.to_csv("data/gold_daily_product_cost.csv", index=False)
print(f"Exported {len(gold_df):,} rows to data/gold_daily_product_cost.csv")