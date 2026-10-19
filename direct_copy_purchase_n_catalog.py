import os
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine

# .env ဖိုင်မှ ချိတ်ဆက်မှု အချက်အလက်များကို ဖတ်ရန်
load_dotenv()

# Source Database Connection (DigitalOcean)
SOURCE_DB_URL = f"mysql+pymysql://{os.getenv('SOURCE_DB_USER')}:{os.getenv('SOURCE_DB_PASSWORD')}@{os.getenv('SOURCE_DB_HOST')}:{os.getenv('SOURCE_DB_PORT')}/{os.getenv('SOURCE_DB_NAME')}"

# Target Database Connection (Local marathon-bi)
TARGET_DB_URL = f"mysql+pymysql://{os.getenv('TARGET_DB_USER')}:{os.getenv('TARGET_DB_PASSWORD')}@{os.getenv('TARGET_DB_HOST')}:{os.getenv('TARGET_DB_PORT')}/{os.getenv('TARGET_DB_NAME')}"

source_engine = create_engine(SOURCE_DB_URL)
target_engine = create_engine(TARGET_DB_URL)

# တိုက်ရိုက်ကူးယူမည့် Table များစာရင်း
tables_to_copy = [
    "bi_master_catalog",
    "bi_daily_purchase_records",
]


def direct_copy_tables():
  for table_name in tables_to_copy:
    print(f"Reading '{table_name}' from Source database...")
    try:
      # Source မှ Data အားလုံးကို Pandas DataFrame ထဲသို့ ဖတ်ခြင်း
      df = pd.read_sql(f"SELECT * FROM {table_name}", con=source_engine)

      print(
          f"Writing '{table_name}' to Target database (Replacing existing"
          " data)..."
      )
      # Target Database သို့ Table တစ်ခုလုံး အစားထိုး (Replace) လုပ်ခြင်း
      df.to_sql(
          table_name,
          con=target_engine,
          if_exists="replace",
          index=False,
          chunksize=10000,
      )

      print(
          f"Successfully copied '{table_name}': {len(df):,} rows transferred.\n"
      )

    except Exception as e:
      print(f"Error copying '{table_name}': {e}\n")


if __name__ == "__main__":
  direct_copy_tables()