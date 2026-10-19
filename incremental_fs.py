import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pymysql

load_dotenv()

def get_engine(db_key):
    user = os.getenv(f"{db_key}_USER") or ""
    password = os.getenv(f"{db_key}_PASSWORD") or ""
    host = os.getenv(f"{db_key}_HOST") or "localhost"
    port = int(os.getenv(f"{db_key}_PORT") or 3306)
    name = os.getenv(f"{db_key}_NAME") or ""
    return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")

def run_incremental_sync():
    print("Connecting to Source and Target databases...")
    src_engine = get_engine("SRC_DB")
    tgt_engine = get_engine("TARGET_DB")

    try:
        # 1. Target မှာ ရှိပြီးသား အနောက်ဆုံး sale_date ကို ရှာခြင်း
        with tgt_engine.connect() as tgt_conn:
            result = tgt_conn.execute(text("SELECT MAX(sale_date) as max_date FROM fact_saless;")).fetchone()
            last_date = result[0] if result and result[0] else '1970-01-01'
        print(f"Last synced date in Target: {last_date}")

        # 2. Source မှ ဒေတာအသစ်များကို ဖတ်ယူရန် (SQLAlchemy engine ကို သုံးခြင်းဖြင့် pandas warning & type error ရှင်းမည်)
        query = f"SELECT * FROM fact_saless WHERE sale_date >= '{last_date}'"
        df = pd.read_sql(query, src_engine)
        print(f"Found {len(df)} rows to sync from Source.")

        if df.empty:
            print("Target is already up to date. No new data to sync.")
            return

        # 3. fact_sale_id ကို numeric သို့ပြောင်းပြီး စာသား/header row များကို သန့်စင်ဖယ်ရှားခြင်း
        if 'fact_sale_id' in df.columns:
            df['fact_sale_id'] = pd.to_numeric(df['fact_sale_id'], errors='coerce')
            df = df.dropna(subset=['fact_sale_id'])

        if df.empty:
            print("No valid numeric records found after cleaning.")
            return

        print(f"Valid rows to insert after cleaning: {len(df)}")

        # 4. Generated Columns များကို DataFrame ထဲမှ ဖယ်ရှားခြင်း (MySQL က သူ့အလိုလို တွက်ပေးပါမည်)
        generated_cols = ['sale_date', 'gross_profit', 'margin_pct']
        for col in generated_cols:
            if col in df.columns:
                df = df.drop(columns=[col])

        # 5. Target Database သို့ Upsert လုပ်ဆောင်ခြင်း (PyMySQL Raw Connection ဖြင့် executemany သုံးခြင်း)
        print("Syncing incremental rows to Target database...")
        
        records = df.where(pd.notnull(df), None).to_dict(orient='records')
        if not records:
            print("No valid records to insert.")
            return

        columns = list(records[0].keys())
        col_names = ", ".join([f"`{c}`" for c in columns])
        placeholders = ", ".join([f"%({c})s" for c in columns])
        
        update_cols = [f"`{c}` = VALUES(`{c}`)" for c in columns if c != 'fact_sale_id']
        update_str = ", ".join(update_cols)

        sql = f"""
            INSERT INTO fact_saless ({col_names}) 
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_str};
        """

        raw_conn = pymysql.connect(
            host=os.getenv("TARGET_DB_HOST") or "localhost",
            port=int(os.getenv("TARGET_DB_PORT") or 3306),
            user=os.getenv("TARGET_DB_USER") or "",
            password=os.getenv("TARGET_DB_PASSWORD") or "",
            database=os.getenv("TARGET_DB_NAME") or "",
            cursorclass=pymysql.cursors.DictCursor
        )

        try:
            with raw_conn.cursor() as cursor:
                chunk_size = 1000
                for i in range(0, len(records), chunk_size):
                    chunk = records[i:i + chunk_size]
                    cursor.executemany(sql, chunk)
                raw_conn.commit()
            print("Incremental sync completed successfully with Upsert!")
        finally:
            raw_conn.close()

    except Exception as e:
        print(f"Incremental sync failed: {e}")

if __name__ == "__main__":
    run_incremental_sync()