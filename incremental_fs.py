import os
import pandas as pd
import numpy as np
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
    
    # DigitalOcean ကဲ့သို့ Cloud DB များအတွက် SSL ဖြင့် ချိတ်ဆက်ရန်
    if db_key == "SRC_DB":
        return create_engine(
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}",
            connect_args={"ssl": {"reject_server_certificate": True}}
        )
    else:
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

        # 2. Source မှ ဒေတာအသစ်များကို ဖတ်ယူရန်
        query = f"SELECT * FROM fact_saless WHERE sale_date >= '{last_date}'"
        df = pd.read_sql(query, src_engine)
        print(f"Found {len(df)} rows to sync from Source based on date.")

        # 3. fact_sale_id ကို numeric သို့ပြောင်းပြီး စာသား/header row များကို သန့်စင်ဖယ်ရှားခြင်း
        if not df.empty and 'fact_sale_id' in df.columns:
            df['fact_sale_id'] = pd.to_numeric(df['fact_sale_id'], errors='coerce')
            df = df.dropna(subset=['fact_sale_id'])

        # Raw connection ဖန်တီးခြင်း (Upsert အတွက်)
        raw_conn = pymysql.connect(
            host=os.getenv("TARGET_DB_HOST") or "localhost",
            port=int(os.getenv("TARGET_DB_PORT") or 3306),
            user=os.getenv("TARGET_DB_USER") or "",
            password=os.getenv("TARGET_DB_PASSWORD") or "",
            database=os.getenv("TARGET_DB_NAME") or "",
            cursorclass=pymysql.cursors.DictCursor
        )

        try:
            # Date-based incremental rows များကို Insert / Upsert လုပ်ခြင်း
            if not df.empty:
                generated_cols = ['sale_date', 'gross_profit', 'margin_pct']
                for col in generated_cols:
                    if col in df.columns:
                        df = df.drop(columns=[col])

                df = df.replace({np.nan: None, pd.NA: None})
                df = df.where(pd.notnull(df), None)

                records = df.to_dict(orient='records')
                if records:
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

                    with raw_conn.cursor() as cursor:
                        chunk_size = 1000
                        for i in range(0, len(records), chunk_size):
                            chunk = records[i:i + chunk_size]
                            cursor.executemany(sql, chunk)
                        raw_conn.commit()
                    print(f"Synced {len(records)} date-incremental rows successfully.")

            # 4. Reconciliation & Missing IDs Check (Server နှစ်ခုကြား ID များကို နှိုင်းယှဉ်စစ်ဆေးခြင်း)
            print("Performing reconciliation check between Source and Target IDs...")
            src_ids_df = pd.read_sql("SELECT fact_sale_id FROM fact_saless", src_engine)
            tgt_ids_df = pd.read_sql("SELECT fact_sale_id FROM fact_saless", tgt_engine)

            src_ids = set(src_ids_df['fact_sale_id'])
            tgt_ids = set(tgt_ids_df['fact_sale_id'])

            missing_ids = list(src_ids - tgt_ids)
            print(f"Reconciliation Status -> Source Total IDs: {len(src_ids)} | Target Total IDs: {len(tgt_ids)}")
            print(f"Missing IDs found in Target: {len(missing_ids)}")

            # အကယ်၍ Missing IDs များ ရှိနေပါက ၎င်းတို့ကိုပါ သီးသန့်ဆွဲထုတ်၍ Target သို့ ထည့်သွင်းခြင်း
            if missing_ids:
                print("Fetching and syncing missing IDs...")
                generated_cols = ['sale_date', 'gross_profit', 'margin_pct']
                batch_size = 1000
                for i in range(0, len(missing_ids), batch_size):
                    batch_ids = missing_ids[i:i + batch_size]
                    id_list_str = ", ".join(map(str, batch_ids))
                    
                    missing_query = f"SELECT * FROM fact_saless WHERE fact_sale_id IN ({id_list_str})"
                    missing_df = pd.read_sql(missing_query, src_engine)

                    if not missing_df.empty:
                        for col in generated_cols:
                            if col in missing_df.columns:
                                missing_df = missing_df.drop(columns=[col])

                        missing_df = missing_df.replace({np.nan: None, pd.NA: None})
                        missing_df = missing_df.where(pd.notnull(missing_df), None)

                        miss_records = missing_df.to_dict(orient='records')
                        if miss_records:
                            m_columns = list(miss_records[0].keys())
                            m_col_names = ", ".join([f"`{c}`" for c in m_columns])
                            m_placeholders = ", ".join([f"%({c})s" for c in m_columns])
                            m_update_cols = [f"`{c}` = VALUES(`{c}`)" for c in m_columns if c != 'fact_sale_id']
                            m_update_str = ", ".join(m_update_cols)

                            m_sql = f"""
                                INSERT INTO fact_saless ({m_col_names}) 
                                VALUES ({m_placeholders})
                                ON DUPLICATE KEY UPDATE {m_update_str};
                            """
                            with raw_conn.cursor() as cursor:
                                cursor.executemany(m_sql, miss_records)
                                raw_conn.commit()
                print("All missing IDs successfully synchronized!")
            else:
                print("Target is 100% in sync with Source. No missing records.")

            print("Incremental sync and reconciliation completed successfully!")

        finally:
            raw_conn.close()

    except Exception as e:
        print(f"Incremental sync failed: {e}")

if __name__ == "__main__":
    run_incremental_sync()