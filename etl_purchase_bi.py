import os
import sys
import logging
import pymysql
from dotenv import load_dotenv

# Logging ကို စနစ်တကျ ပြင်ဆင်ခြင်း
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# .env ဖိုင်ကို ဖတ်ယူခြင်း
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
            autocommit=False  # Transaction control အတွက် False ထားပါသည်
        )
        return connection
    except pymysql.MySQLError as e:
        logging.error(f"Database ချိတ်ဆက်မှု မအောင်မြင်ပါ: {e}")
        sys.exit(1)

def refresh_purchase_records():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # ရှင်းလင်းပြီး စနစ်တကျ ပုံစံထုတ်ထားသော SQL Query
    sql_query = """
    INSERT INTO bi_daily_purchase_records (
        business_id, business_name, branch_id, branch_name, warehouse_id, warehouse_name,
        supplier_group_id, supplier_group_name, supplier_id, supplier_name, supplier_phone, supplier_mobile, supplier_email,
        bill_id, bill_number, reference_number, purchase_order_id, purchase_order_number,
        purchase_date, payment_due_date, payment_terms, bill_status,
        currency_symbol, currency_name, exchange_rate,
        bill_detail_id, product_sku, product_name, item_batch_number, item_expiry_date,
        purchased_qty, unit_price, item_discount_amount, item_tax_amount, item_line_total,
        bill_subtotal, bill_total_discount, bill_total_tax, grand_total_amount,
        total_paid_amount, credit_note_used_amount, advance_deposit_used_amount, outstanding_balance,
        bill_created_at, bill_updated_at
    )
    SELECT
        b.id AS business_id,
        b.name AS business_name,
        br.id AS branch_id,
        br.name AS branch_name,
        w.id AS warehouse_id,
        w.name AS warehouse_name,
        sg.id AS supplier_group_id,
        COALESCE(sg.name, 'Ungrouped') AS supplier_group_name,
        s.id AS supplier_id,
        s.name AS supplier_name,
        s.phone AS supplier_phone,
        s.mobile AS supplier_mobile,
        s.email AS supplier_email,
        bill.id AS bill_id,
        bill.bill_number AS bill_number,
        bill.reference_number AS reference_number,
        bill.purchase_order_id AS purchase_order_id,
        bill.purchase_order_number AS purchase_order_number,
        bill.bill_date AS purchase_date,
        bill.bill_due_date AS payment_due_date,
        bill.bill_payment_terms AS payment_terms,
        bill.current_status AS bill_status,
        curr.symbol AS currency_symbol,
        curr.name AS currency_name,
        bill.exchange_rate AS exchange_rate,
        bd.id AS bill_detail_id,
        COALESCE(p.sku, 'N/A') AS product_sku,
        COALESCE(p.name, bd.name) AS product_name,
        bd.batch_number AS item_batch_number,
        bd.expiry_date AS item_expiry_date,
        bd.detail_qty AS purchased_qty,
        bd.detail_unit_rate AS unit_price,
        bd.detail_discount_amount AS item_discount_amount,
        bd.detail_tax_amount AS item_tax_amount,
        bd.detail_total_amount AS item_line_total,
        bill.bill_subtotal AS bill_subtotal,
        bill.bill_total_discount_amount AS bill_total_discount,
        bill.bill_total_tax_amount AS bill_total_tax,
        bill.bill_total_amount AS grand_total_amount,
        bill.bill_total_paid_amount AS total_paid_amount,
        bill.bill_total_credit_used_amount AS credit_note_used_amount,
        bill.bill_total_advance_used_amount AS advance_deposit_used_amount,
        bill.remaining_balance AS outstanding_balance,
        bill.created_at AS bill_created_at,
        bill.updated_at AS bill_updated_at
    FROM bills AS bill
    INNER JOIN businesses AS b ON bill.business_id = b.id
    INNER JOIN branches AS br ON bill.branch_id = br.id
    INNER JOIN warehouses AS w ON bill.warehouse_id = w.id
    INNER JOIN suppliers AS s ON bill.supplier_id = s.id
    LEFT JOIN supplier_groups sg ON s.group_id = sg.id
    INNER JOIN currencies AS curr ON bill.currency_id = curr.id
    LEFT JOIN bill_details AS bd ON bd.bill_id = bill.id
    LEFT JOIN products AS p ON bd.product_id = p.id
    ORDER BY bill.bill_date DESC, bill.id DESC, bd.id ASC;
    """

    try:
        logging.info("ETL Sync လုပ်ငန်းစဉ် စတင်နေပါပြီ...")
        
        # 1. Truncate Table (Existing records များကို ဖယ်ရှားခြင်း)
        cursor.execute("TRUNCATE TABLE bi_daily_purchase_records;")
        logging.info("Table `bi_daily_purchase_records` successfully truncated.")
        
        # 2. Insert New Data from Source Query
        cursor.execute(sql_query)
        row_count = cursor.rowcount
        
        # 3. Commit Transaction
        connection.commit()
        logging.info(f"ETL Sync အောင်မြင်ပါသည်! စုစုပေါင်း Records အရေအတွက် ({row_count}) ခု ထည့်သွင်းပြီးပါပြီ။")

    except Exception as e:
        connection.rollback()
        logging.error(f"[Error] ETL Sync မအောင်မြင်ပါ (Rolled back): {e}")
        sys.exit(1)
        
    finally:
        cursor.close()
        connection.close()
        logging.info("Database connection closed.")

if __name__ == "__main__":
    refresh_purchase_records()