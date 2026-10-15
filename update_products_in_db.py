import os
import sys
import time
import pymysql
from dotenv import load_dotenv

# .env file ကို ဖတ်ယူခြင်း
load_dotenv()

# Environment Variables များ ရယူခြင်း
def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} environment variable is not set")
    return value

DB_HOST = require_env("BI_DB_HOST")
DB_PORT = int(os.getenv("BI_DB_PORT", "25060"))
DB_USER = require_env("BI_DB_USER")
DB_PASS = require_env("BI_DB_PASS")
DB_NAME = require_env("BI_DB_NAME")

# Database Connection တည်ဆောက်ခြင်း
def get_db_connection():
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            ssl={'ssl_mode': 'REQUIRED'},  # DigitalOcean Managed MySQL
            connect_timeout=30,
            autocommit=True
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"[Error] Database ချိတ်ဆက်မှု မအောင်မြင်ပါ: {e}")
        sys.exit(1)


def batch_update_sales_products():
    chunk_size = 5000
    max_id = 500000
    
    print(f"Starting batch update from ID 1 to {max_id} (Chunk Size: {chunk_size})...")
    
    connection = get_db_connection()
    
    try:
        with connection.cursor() as cursor:
            for start_id in range(1, max_id + 1, chunk_size):
                end_id = min(start_id + chunk_size - 1, max_id)
                
                # SQL Query
                update_query = f"""
                    UPDATE bi_database.fact_saless fs
                    INNER JOIN `das-db`.products p 
                        ON fs.product_id = p.id AND fs.business_id = p.business_id
                    LEFT JOIN `das-db`.product_categories pc 
                        ON p.category_id = pc.id AND p.business_id = pc.business_id
                    SET 
                        fs.product_sku      = p.sku,
                        fs.product_barcode  = p.barcode,
                        fs.product_category = pc.name,
                        fs.product_brand    = p.brand_name
                    WHERE fs.product_id IS NOT NULL
                      AND fs.fact_sale_id BETWEEN {start_id} AND {end_id};
                """
                
                start_time = time.time()
                
                # Query ကို Run ခြင်း
                affected_rows = cursor.execute(update_query)
                
                elapsed_time = time.time() - start_time
                
                print(f"[Success] Chunk ({start_id} to {end_id}) processed in {elapsed_time:.2f}s | Rows Updated: {affected_rows}")
                
                # DigitalOcean DB Server CPU Load သက်သာစေရန် 0.1 စက္ကန့် နားပေးခြင်း
                time.sleep(0.1)
                
        print("\nAll batch updates completed successfully!")
        
    except Exception as err:
        print(f"\n[Error] Batch process အတွင်း အမှားအယွင်း ဖြစ်ပေါ်ခဲ့သည်: {err}")
    finally:
        connection.close()
        print("Database connection closed.")


if __name__ == "__main__":
    batch_update_sales_products()