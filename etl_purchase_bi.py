import os
import sys
import logging
import pymysql
from dotenv import load_dotenv

# Configure logging to English only
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Load environment variables from .env file
load_dotenv()

# Function to require environment variables
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

# Establish Database Connection
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
            autocommit=False
        )
        return connection
    except pymysql.MySQLError as e:
        logging.error(f"Database connection failed: {e}")
        sys.exit(1)

def refresh_purchase_records():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # 1. Main Table Insert Query
    sql_insert = """
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
    FROM `das-db`.bills AS bill
    INNER JOIN `das-db`.businesses AS b ON bill.business_id = b.id
    INNER JOIN `das-db`.branches AS br ON bill.branch_id = br.id
    INNER JOIN `das-db`.warehouses AS w ON bill.warehouse_id = w.id
    INNER JOIN `das-db`.suppliers AS s ON bill.supplier_id = s.id
    LEFT JOIN `das-db`.supplier_groups sg ON s.group_id = sg.id
    INNER JOIN `das-db`.currencies AS curr ON bill.currency_id = curr.id
    LEFT JOIN `das-db`.bill_details AS bd ON bd.bill_id = bill.id
    LEFT JOIN `das-db`.products AS p ON bd.product_id = p.id
    ORDER BY bill.bill_date DESC, bill.id DESC, bd.id ASC;
    """

    # 2. Business Unit Views Creation Queries
    sql_view_m_kitchen = """
    CREATE OR REPLACE VIEW vw_bi_purchase_m_kitchen AS
    SELECT * FROM bi_daily_purchase_records
    WHERE business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND branch_id = 34;
    """

    sql_view_m_trading = """
    CREATE OR REPLACE VIEW vw_bi_purchase_m_trading AS
    SELECT * FROM bi_daily_purchase_records
    WHERE (
        (business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(branch_id AS CHAR)) != '34' OR branch_id IS NULL))
        OR 
        (business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
    );
    """

    sql_view_shwezay = """
    CREATE OR REPLACE VIEW vw_bi_purchase_shwezay AS
    SELECT * FROM bi_daily_purchase_records
    WHERE business_id IN (
        'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', -- ygn
        '2d393763-d5c7-42be-b345-84b7be787f10', -- npt
        '1eb52cc2-7a34-43d8-b646-67cc60402916'  -- kpg
    );
    """

    try:
        logging.info("ETL sync process started...")
        
        # 1. Truncate Table
        cursor.execute("TRUNCATE TABLE bi_daily_purchase_records;")
        logging.info("Table `bi_daily_purchase_records` successfully truncated.")
        
        # 2. Insert New Data
        cursor.execute(sql_insert)
        row_count = cursor.rowcount
        logging.info(f"Master table successfully loaded with {row_count} records.")

        # 3. Create or Replace Views for Business Units
        logging.info("Creating business unit views...")
        cursor.execute(sql_view_m_kitchen)
        cursor.execute(sql_view_m_trading)
        cursor.execute(sql_view_shwezay)
        logging.info("Views successfully created (`vw_bi_purchase_m_kitchen`, `vw_bi_purchase_m_trading`, `vw_bi_purchase_shwezay`).")
        
        # Commit Transaction
        connection.commit()
        logging.info("ETL sync process completed successfully.")

    except Exception as e:
        connection.rollback()
        logging.error(f"ETL sync failed (Rolled back): {e}")
        sys.exit(1)
        
    finally:
        cursor.close()
        connection.close()
        logging.info("Database connection closed.")

if __name__ == "__main__":
    refresh_purchase_records()