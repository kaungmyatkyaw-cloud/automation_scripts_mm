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

def refresh_master_catalog():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # 1. Master Catalog Refresh SQL Query
    sql_catalog_etl = """
    INSERT INTO `bi_master_catalog` (
        `business_id`, `product_id`, `master_id`, `external_system_id`, `sku`, `purchased_sku`, `barcode`, 
        `product_name`, `description`, `brand_name`, `nature`, `is_active`, `is_sellable`, `is_purchasable`, 
        `category_id`, `category_name`, `parent_category_id`, `parent_category_name`, 
        `product_group_id`, `product_group_name`, `unit_id`, `unit_name`, `unit_abbreviation`, `unit_precision`, 
        `preferred_supplier_id`, `preferred_supplier_name`, `supplier_group_name`, 
        `sales_price`, `is_sales_tax_inclusive`, `sales_tax_id`, `sales_tax_name`, `sales_tax_rate`, 
        `purchase_price`, `purchase_tax_id`, `purchase_tax_name`, `purchase_tax_rate`, 
        `latest_cogs_rate`, `average_cogs_rate`, `latest_purchase_bill_rate`, `inventory_base_unit_value`, 
        `gross_margin_amount`, `gross_margin_percent`, 
        `total_current_qty`, `total_committed_qty`, `total_order_qty`, `total_asset_valuation`, 
        `reorder_point`, `stock_status`, 
        `is_batch_tracking`, `is_expiry_date_tracking`, `shelf_life_days`, `length`, `width`, `height`, `weight`, 
        `inventory_account_id`, `inventory_account_name`, `sales_account_id`, `sales_account_name`, 
        `purchase_account_id`, `purchase_account_name`, `product_created_at`, `product_updated_at`
    ) 
    SELECT 
        p.business_id, 
        p.id AS product_id, 
        p.master_id, 
        p.external_system_id, 
        p.sku, 
        p.purchased_sku, 
        p.barcode, 
        p.name AS product_name, 
        p.description, 
        p.brand_name, 
        p.nature, 
        p.is_active, 
        p.is_sellable, 
        p.is_purchasable, 
        
        -- Category & Parent Category
        c.id AS category_id, 
        c.name AS category_name, 
        parent_c.id AS parent_category_id, 
        parent_c.name AS parent_category_name, 
        
        -- Product Group
        pg.id AS product_group_id, 
        pg.name AS product_group_name, 
        
        -- Measurement Unit
        u.id AS unit_id, 
        u.name AS unit_name, 
        u.abbreviation AS unit_abbreviation, 
        u.precision AS unit_precision, 
        
        -- Supplier & Group
        s.id AS preferred_supplier_id, 
        s.name AS preferred_supplier_name, 
        COALESCE(sg.name, 'Ungrouped') AS supplier_group_name, 
        
        -- Catalog Listing Prices & Taxes
        p.sales_price, 
        p.is_sales_tax_inclusive, 
        stax.id AS sales_tax_id, 
        stax.name AS sales_tax_name, 
        COALESCE(stax.rate, 0.0000) AS sales_tax_rate, 
        p.purchase_price, 
        ptax.id AS purchase_tax_id, 
        ptax.name AS purchase_tax_name, 
        COALESCE(ptax.rate, 0.0000) AS purchase_tax_rate, 
        
        -- COGS & Cost Calculations
        COALESCE(cogs_agg.latest_cogs, 0.0000) AS latest_cogs_rate, 
        COALESCE(cogs_agg.avg_cogs, 0.0000) AS average_cogs_rate, 
        COALESCE(last_bill.latest_bill_rate, 0.0000) AS latest_purchase_bill_rate, 
        COALESCE(last_hist.base_unit_value, 0.0000) AS inventory_base_unit_value, 
        
        -- Gross Margin Calculations with Safeguard Clamping
        (p.sales_price - COALESCE(cogs_agg.latest_cogs, 0.0000)) AS gross_margin_amount, 
        CASE 
            WHEN p.sales_price > 0 THEN 
                LEAST(
                    GREATEST(
                        ROUND(((p.sales_price - COALESCE(cogs_agg.latest_cogs, 0.0000)) / p.sales_price) * 100, 2), 
                        -9999.99
                    ), 
                    9999.99
                )
            ELSE 0.00 
        END AS gross_margin_percent, 
        
        -- Aggregated Stock Quantities
        COALESCE(stock.total_current, 0.0000) AS total_current_qty, 
        COALESCE(stock.total_committed, 0.0000) AS total_committed_qty, 
        COALESCE(stock.total_order, 0.0000) AS total_order_qty, 
        (COALESCE(stock.total_current, 0.0000) * COALESCE(last_hist.base_unit_value, p.purchase_price)) AS total_asset_valuation, 
        p.reorder_point, 
        
        -- Derived Stock Status
        CASE 
            WHEN COALESCE(stock.total_current, 0.0000) <= 0 THEN 'Out of Stock' 
            WHEN COALESCE(stock.total_current, 0.0000) <= p.reorder_point THEN 'Below Reorder Point' 
            ELSE 'Normal' 
        END AS stock_status, 
        
        -- Lot, Batch, Expiry & Dimensions
        p.is_batch_tracking, 
        p.is_expiry_date_tracking, 
        p.shelf_life_days, 
        p.length, 
        p.width, 
        p.height, 
        p.weight, 
        
        -- GL Accounts
        inv_acc.id AS inventory_account_id, 
        inv_acc.name AS inventory_account_name, 
        sale_acc.id AS sales_account_id, 
        sale_acc.name AS sales_account_name, 
        pur_acc.id AS purchase_account_id, 
        pur_acc.name AS purchase_account_name, 
        
        -- Timestamps
        p.created_at, 
        p.updated_at 

    FROM `das-db`.products AS p 
    -- Category & Hierarchy
    LEFT JOIN `das-db`.product_categories AS c ON p.category_id = c.id 
    LEFT JOIN `das-db`.product_categories AS parent_c ON c.parent_category_id = parent_c.id 
    -- Groups & Measurement Units
    LEFT JOIN `das-db`.product_groups AS pg ON p.id = pg.id 
    LEFT JOIN `das-db`.product_units AS u ON p.unit_id = u.id 
    -- Preferred Supplier
    LEFT JOIN `das-db`.suppliers AS s ON p.supplier_id = s.id 
    LEFT JOIN `das-db`.supplier_groups AS sg ON s.group_id = sg.id 
    -- Tax Rules
    LEFT JOIN `das-db`.taxes AS stax ON p.sales_tax_id = stax.id 
    LEFT JOIN `das-db`.taxes AS ptax ON p.purchase_tax_id = ptax.id 
    -- General Ledger Accounts
    LEFT JOIN `das-db`.accounts AS inv_acc ON p.inventory_account_id = inv_acc.id 
    LEFT JOIN `das-db`.accounts AS sale_acc ON p.sales_account_id = sale_acc.id 
    LEFT JOIN `das-db`.accounts AS pur_acc ON p.purchase_account_id = pur_acc.id 
    
    -- 1. Aggregated COGS from Invoiced Sales
    LEFT JOIN ( 
        SELECT product_id, SUBSTRING_INDEX(GROUP_CONCAT(cogs ORDER BY id DESC), ',', 1) + 0.0000 AS latest_cogs, AVG(NULLIF(cogs, 0)) AS avg_cogs 
        FROM `das-db`.sales_invoice_details 
        WHERE product_id IS NOT NULL AND cogs > 0 
        GROUP BY product_id 
    ) AS cogs_agg ON p.id = cogs_agg.product_id 
    
    -- 2. Latest Invoiced Purchase Rate from Bills
    LEFT JOIN ( 
        SELECT product_id, SUBSTRING_INDEX(GROUP_CONCAT(detail_unit_rate ORDER BY id DESC), ',', 1) + 0.0000 AS latest_bill_rate 
        FROM `das-db`.bill_details 
        WHERE product_id IS NOT NULL AND detail_unit_rate > 0 
        GROUP BY product_id 
    ) AS last_bill ON p.id = last_bill.product_id 
    
    -- 3. Latest Inventory Holding Value from Stock Histories
    LEFT JOIN ( 
        SELECT product_id, SUBSTRING_INDEX(GROUP_CONCAT(base_unit_value ORDER BY stock_date DESC, id DESC), ',', 1) + 0.0000 AS base_unit_value 
        FROM `das-db`.stock_histories 
        WHERE product_id IS NOT NULL AND base_unit_value > 0 
        GROUP BY product_id 
    ) AS last_hist ON p.id = last_hist.product_id 
    
    -- 4. Rollup of Total Stock Across All Warehouses
    LEFT JOIN ( 
        SELECT product_id, SUM(current_qty) AS total_current, SUM(committed_qty) AS total_committed, SUM(order_qty) AS total_order 
        FROM `das-db`.stock_summaries 
        WHERE product_id IS NOT NULL 
        GROUP BY product_id 
    ) AS stock ON p.id = stock.product_id;
    """

    # 2. Business Unit Views Creation Queries for Master Catalog
    sql_view_m_kitchen = """
    CREATE OR REPLACE VIEW vw_bi_catalog_m_kitchen AS
    SELECT * FROM bi_master_catalog
    WHERE business_id = '84093770-29ad-4e8e-9da1-babe583c0d69';
    """

    sql_view_m_trading = """
    CREATE OR REPLACE VIEW vw_bi_catalog_m_trading AS
    SELECT * FROM bi_master_catalog
    WHERE (
        (business_id = '84093770-29ad-4e8e-9da1-babe583c0d69')
        OR 
        (business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
    );
    """

    sql_view_shwezay = """
    CREATE OR REPLACE VIEW vw_bi_catalog_shwezay AS
    SELECT * FROM bi_master_catalog
    WHERE business_id IN (
        'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', -- ygn
        '2d393763-d5c7-42be-b345-84b7be787f10', -- npt
        '1eb52cc2-7a34-43d8-b646-67cc60402916'  -- kpg
    );
    """

    try:
        logging.info("Master catalog ETL sync process started...")
        
        # Truncate table
        cursor.execute("TRUNCATE TABLE `bi_master_catalog`;")
        logging.info("Table `bi_master_catalog` successfully truncated.")
        
        # Increase group_concat_max_len to prevent row truncation error (Error 1260)
        cursor.execute("SET SESSION group_concat_max_len = 1000000;")
        
        # Execute insert query
        cursor.execute(sql_catalog_etl)
        row_count = cursor.rowcount
        logging.info(f"Master catalog successfully loaded with {row_count} records.")

        # 3. Create or Replace Views for Business Units
        logging.info("Creating business unit catalog views...")
        cursor.execute(sql_view_m_kitchen)
        cursor.execute(sql_view_m_trading)
        cursor.execute(sql_view_shwezay)
        logging.info("Catalog views successfully created (`vw_bi_catalog_m_kitchen`, `vw_bi_catalog_m_trading`, `vw_bi_catalog_shwezay`).")
        
        # Commit Transaction
        connection.commit()
        logging.info("Master catalog ETL sync process completed successfully.")

    except Exception as e:
        connection.rollback()
        logging.error(f"Master catalog ETL sync failed (Rolled back): {e}")
        sys.exit(1)
        
    finally:
        cursor.close()
        connection.close()
        logging.info("Database connection closed.")

if __name__ == "__main__":
    refresh_master_catalog()