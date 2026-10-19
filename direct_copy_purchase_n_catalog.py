import pandas as pd
from sqlalchemy import create_engine

# Source Database Connection (DigitalOcean - ပေးထားသည့် အချက်အလက်များအတိုင်း)
SOURCE_DB_URL = "mysql+pymysql://kmkyaw:BOs5hA%2BMo6UfmgYweaPJqrmD@db-distribution-accounting-do-user-2718740-0.h.db.ondigitalocean.com:25060/bi_database"

# Target Database Connection (Local marathon-bi)
TARGET_DB_URL = "mysql+pymysql://root:MaratonBI!1234@localhost:3306/m_bi"

source_engine = create_engine(SOURCE_DB_URL)
target_engine = create_engine(TARGET_DB_URL)

tables_to_copy = [
    "bi_master_catalog",
    "bi_daily_purchase_records",
]


def direct_copy_tables():
  for table_name in tables_to_copy:
    print(f"Reading '{table_name}' from Source database...")
    try:
      df = pd.read_sql(f"SELECT * FROM {table_name}", con=source_engine)

      print(
          f"Writing '{table_name}' to Target database (Replacing existing"
          " data)..."
      )
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