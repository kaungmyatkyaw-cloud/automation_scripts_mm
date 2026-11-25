-- ################################################################################
-- ETL PROCESS STATED HERE
-- ################################################################################

USE bi_database;
SET sql_safe_updates = 0;
TRUNCATE TABLE bi_database.fact_saless;

-- Part 1: INSERT Invoice Sales
INSERT INTO bi_database.fact_saless (
    source_type, source_header_id, source_detail_id,
    transaction_number, header_status,
    business_id, branch_id, warehouse_id, customer_id,
    currency_id, exchange_rate, sale_datetime,
    product_id, product_type, product_name,
    product_sku, product_barcode, product_category, product_brand,
    batch_number,
    master_product_id, master_sku, master_barcode,
    master_product_name, master_brand_name, master_category, master_sub_category,
    quantity, unit_rate, discount_amount, tax_amount,
    net_amount, cogs_amount
)
SELECT 
    'INVOICE'                           AS source_type,
    si.id                               AS source_header_id,
    sid.id                              AS source_detail_id,
    si.invoice_number                   AS transaction_number,
    si.current_status                   AS header_status,
    si.business_id,
    si.branch_id,
    si.warehouse_id,
    si.customer_id,
    si.currency_id,
    si.exchange_rate,
    si.invoice_date                     AS sale_datetime,
    sid.product_id,
    sid.product_type,
    sid.name                            AS product_name,
    p.sku                               AS product_sku,
    p.barcode                           AS product_barcode,
    pc.name                             AS product_category,
    p.brand_name                        AS product_brand,
    sid.batch_number,
    mpm.master_product_id,
    dmp.master_sku,
    dmp.master_barcode,
    dmp.master_product_name,
    dmp.brand_name                      AS master_brand_name,
    dmp.category                        AS master_category,
    dmp.sub_category                    AS master_sub_category,
    sid.detail_qty                      AS quantity,
    sid.detail_unit_rate                AS unit_rate,
    sid.detail_discount_amount          AS discount_amount,
    sid.detail_tax_amount               AS tax_amount,
    sid.detail_total_amount             AS net_amount,
    sid.cogs                            AS cogs_amount
FROM `das-db`.sales_invoices si
INNER JOIN `das-db`.sales_invoice_details sid 
    ON sid.sales_invoice_id = si.id
LEFT JOIN bi_database.map_product_master mpm
    ON mpm.product_id = sid.product_id 
    AND mpm.business_id = si.business_id
LEFT JOIN `das-db`.products p
    ON p.id = sid.product_id
    AND p.business_id = si.business_id
LEFT JOIN `das-db`.product_categories pc
    ON pc.id = p.category_id
    AND pc.business_id = p.business_id
LEFT JOIN bi_database.dim_master_products dmp
    ON dmp.master_product_id = mpm.master_product_id
WHERE si.current_status IN ('Confirmed', 'Partial Paid', 'Paid');

-- ################################################################################
-- Part 2: INSERT POS Sales
INSERT INTO bi_database.fact_saless (
    source_type, source_header_id, source_detail_id,
    transaction_number, header_status,
    business_id, branch_id, warehouse_id, customer_id,
    currency_id, exchange_rate, sale_datetime,
    product_id, product_type, product_name,
    product_sku, product_barcode, product_category, product_brand,
    batch_number,
    master_product_id, master_sku, master_barcode,
    master_product_name, master_brand_name, master_category, master_sub_category,
    quantity, unit_rate, discount_amount, tax_amount,
    net_amount, cogs_amount
)
SELECT 
    'POS'                               AS source_type,
    pc2.id                              AS source_header_id,
    pcd.id                              AS source_detail_id,
    pc2.checkout_number                 AS transaction_number,
    pc2.current_status                  AS header_status,
    pc2.business_id,
    pc2.branch_id,
    pc2.warehouse_id,
    pc2.customer_id,
    pc2.currency_id,
    pc2.exchange_rate,
    pc2.checkout_date                   AS sale_datetime,
    pcd.product_id,
    pcd.product_type,
    pcd.name                            AS product_name,
    p.sku                               AS product_sku,
    p.barcode                           AS product_barcode,
    pc.name                             AS product_category,
    p.brand_name                        AS product_brand,
    pcd.batch_number,
    mpm.master_product_id,
    dmp.master_sku,
    dmp.master_barcode,
    dmp.master_product_name,
    dmp.brand_name                      AS master_brand_name,
    dmp.category                        AS master_category,
    dmp.sub_category                    AS master_sub_category,
    pcd.detail_qty                      AS quantity,
    pcd.detail_unit_rate                AS unit_rate,
    pcd.detail_discount_amount          AS discount_amount,
    pcd.detail_tax_amount               AS tax_amount,
    pcd.detail_total_amount             AS net_amount,
    pcd.cogs                            AS cogs_amount
FROM `das-db`.pos_checkout_invoice_payments pc2
INNER JOIN `das-db`.pos_checkout_details pcd 
    ON pcd.pos_checkout_invoice_payment_id = pc2.id
LEFT JOIN bi_database.map_product_master mpm
    ON mpm.product_id = pcd.product_id 
    AND mpm.business_id = pc2.business_id
LEFT JOIN `das-db`.products p
    ON p.id = pcd.product_id
    AND p.business_id = pc2.business_id
LEFT JOIN `das-db`.product_categories pc
    ON pc.id = p.category_id
    AND pc.business_id = p.business_id
LEFT JOIN bi_database.dim_master_products dmp
    ON dmp.master_product_id = mpm.master_product_id
WHERE pc2.current_status = 'Paid';

-- ################################################################################
-- ################################################################################
/*
-- Data Load ကြီးတဲ့ အတွက် cpu consume သက်သာ အောင် အပိုင်းလိုက် update လုပ်မှာဖြစ်ပါတယ် 
-- Chunk 1 (rows 1–30,000)
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
  AND fs.fact_sale_id BETWEEN 1 AND 30000;
  
-- ################################################################################

-- Chunk 2 (rows 30,001–400,00)
UPDATE bi_database.fact_saless fs
INNER JOIN products p 
    ON fs.product_id = p.id AND fs.business_id = p.business_id
LEFT JOIN `das-db`.product_categories pc 
    ON p.category_id = pc.id AND p.business_id = pc.business_id
SET 
    fs.product_sku      = p.sku,
    fs.product_barcode  = p.barcode,
    fs.product_category = pc.name,
    fs.product_brand    = p.brand_name
WHERE fs.product_id IS NOT NULL
  AND fs.fact_sale_id BETWEEN 30001 AND 60000;

-- ################################################################################

-- Chunk 3 (rows 60,001–90,000)
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
  AND fs.fact_sale_id BETWEEN 60001 AND 90000;

-- ################################################################################

-- Chunk 4 (rows 90,001–120,000)
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
  AND fs.fact_sale_id BETWEEN 90001 AND 120000;

-- ################################################################################

-- Chunk 5 (rows 120001-150000)
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
  AND fs.fact_sale_id BETWEEN 120001 AND 150000;

-- ################################################################################

-- Chunk 6 (rows 150001-180000)
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
  AND fs.fact_sale_id BETWEEN 150001 AND 180000;

-- ################################################################################

-- Chunk 7 (rows 180001-210000)
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
  AND fs.fact_sale_id BETWEEN 180001 AND 210000;

-- ####################################################

-- Chunk 8 (rows > 210000)
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
  AND fs.fact_sale_id > 210000;

-- ################################################################################
*/
UPDATE bi_database.fact_saless fs
INNER JOIN `das-db`.sales_invoices si 
    ON fs.source_header_id = si.id
    AND fs.source_type = 'INVOICE'
SET fs.sales_person_id = si.sales_person_id
WHERE fs.sales_person_id IS NULL;

-- Backfill from pos_checkout_invoice_payments
UPDATE bi_database.fact_saless fs
INNER JOIN `das-db`.pos_checkout_invoice_payments pos 
    ON fs.source_header_id = pos.id
    AND fs.source_type = 'POS'
SET fs.sales_person_id = pos.sales_person_id
WHERE fs.sales_person_id IS NULL;


-- UPDATE Master Product Details (in 5 chunks)
-- ################################################################################

-- Chunk 1
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.dim_master_products dmp 
    ON fs.master_product_id = dmp.master_product_id
SET 
    fs.master_sku           = dmp.master_sku,
    fs.master_barcode       = dmp.master_barcode,
    fs.master_product_name  = dmp.master_product_name,
    fs.master_brand_name    = dmp.brand_name,
    fs.master_category      = dmp.category,
    fs.master_sub_category  = dmp.sub_category
WHERE fs.master_product_id IS NOT NULL
  AND fs.fact_sale_id BETWEEN 1 AND 50000;

-- ################################################################################

-- Chunk 2
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.dim_master_products dmp 
    ON fs.master_product_id = dmp.master_product_id
SET 
    fs.master_sku           = dmp.master_sku,
    fs.master_barcode       = dmp.master_barcode,
    fs.master_product_name  = dmp.master_product_name,
    fs.master_brand_name    = dmp.brand_name,
    fs.master_category      = dmp.category,
    fs.master_sub_category  = dmp.sub_category
WHERE fs.master_product_id IS NOT NULL
  AND fs.fact_sale_id BETWEEN 50001 AND 100000;

-- ################################################################################

-- Chunk 3
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.dim_master_products dmp 
    ON fs.master_product_id = dmp.master_product_id
SET 
    fs.master_sku           = dmp.master_sku,
    fs.master_barcode       = dmp.master_barcode,
    fs.master_product_name  = dmp.master_product_name,
    fs.master_brand_name    = dmp.brand_name,
    fs.master_category      = dmp.category,
    fs.master_sub_category  = dmp.sub_category
WHERE fs.master_product_id IS NOT NULL
  AND fs.fact_sale_id BETWEEN 100001 AND 150000;
  
################################################################################

-- Chunk 4
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.dim_master_products dmp 
    ON fs.master_product_id = dmp.master_product_id
SET 
    fs.master_sku           = dmp.master_sku,
    fs.master_barcode       = dmp.master_barcode,
    fs.master_product_name  = dmp.master_product_name,
    fs.master_brand_name    = dmp.brand_name,
    fs.master_category      = dmp.category,
    fs.master_sub_category  = dmp.sub_category
WHERE fs.master_product_id IS NOT NULL
  AND fs.fact_sale_id BETWEEN 150001 AND 200000;

################################################################################

-- Chunk 5  
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.dim_master_products dmp 
    ON fs.master_product_id = dmp.master_product_id
SET 
    fs.master_sku           = dmp.master_sku,
    fs.master_barcode       = dmp.master_barcode,
    fs.master_product_name  = dmp.master_product_name,
    fs.master_brand_name    = dmp.brand_name,
    fs.master_category      = dmp.category,
    fs.master_sub_category  = dmp.sub_category
WHERE fs.master_product_id IS NOT NULL
  AND fs.fact_sale_id > 200000;

-- ################################################################################

-- Check  
-- SELECT 
--     COUNT(*) AS total_rows,
--     SUM(CASE WHEN product_sku IS NOT NULL THEN 1 ELSE 0 END) AS has_bu_sku,
--     SUM(CASE WHEN master_sku IS NOT NULL THEN 1 ELSE 0 END) AS has_master_sku,
--     ROUND(SUM(CASE WHEN product_sku IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*)*100,1) AS bu_sku_pct,
--     ROUND(SUM(CASE WHEN master_sku IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*)*100,1) AS master_sku_pct
-- FROM bi_database.fact_saless;

-- -- #######################################

-- DROP TABLE IF EXISTS bi_database.agg_product_sales;

-- -- ################################################################################

-- CREATE TABLE bi_database.agg_product_sales (
--     master_product_id   BIGINT NOT NULL PRIMARY KEY,
--     master_sku          VARCHAR(100),
--     master_barcode      VARCHAR(100),
--     master_product_name VARCHAR(255),
--     brand_name          VARCHAR(100),
--     category            VARCHAR(150),
--     sub_category        VARCHAR(150),
--     total_transactions  BIGINT DEFAULT 0,
--     sold_across_bu_count BIGINT DEFAULT 0,
--     total_qty_sold      DECIMAL(20,4) DEFAULT 0.0000,
--     total_revenue       DECIMAL(20,4) DEFAULT 0.0000,
--     total_cogs          DECIMAL(20,4) DEFAULT 0.0000,
--     total_gross_profit  DECIMAL(20,4) DEFAULT 0.0000,
--     overall_margin_pct  DECIMAL(10,2) DEFAULT 0.00,
--     invoice_revenue     DECIMAL(20,4) DEFAULT 0.0000,
--     pos_revenue         DECIMAL(20,4) DEFAULT 0.0000,
--     first_sale_date     DATE,
--     last_sale_date      DATE,
--     last_refreshed_at   DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    
--     INDEX idx_agg_cat   (category),
--     INDEX idx_agg_brand (brand_name),
--     INDEX idx_agg_rev   (total_revenue DESC)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- -- ################################################################################

-- DROP TABLE IF EXISTS bi_database.map_product_master ;

-- -- ################################################################################
-- -- Build the bridge table
-- CREATE TABLE bi_database.map_product_master (
--     product_id      BIGINT NOT NULL,
--     business_id     VARCHAR(191) NOT NULL,
--     master_product_id BIGINT NOT NULL,
--     match_method    ENUM('PRIMARY','BARCODE','SKU','MANUAL') NOT NULL,
--     PRIMARY KEY (product_id, business_id),
--     INDEX idx_map_master (master_product_id)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- -- 1) Insert PRIMARY matches (already known)
-- INSERT INTO bi_database.map_product_master (product_id, business_id, master_product_id, match_method)
-- SELECT 
--     dmp.primary_source_id,
--     dmp.primary_business_id,
--     dmp.master_product_id,
--     'PRIMARY'
-- FROM bi_database.dim_master_products dmp;

-- -- 2) Insert BARCODE matches (products with same barcode as a master product)
-- INSERT IGNORE INTO bi_database.map_product_master (product_id, business_id, master_product_id, match_method)
-- SELECT 
--     p.id,
--     p.business_id,
--     dmp.master_product_id,
--     'BARCODE'
-- FROM `das-db`.products p
-- INNER JOIN bi_database.dim_master_products dmp 
--     ON p.barcode = dmp.master_barcode
--     AND p.business_id != dmp.primary_business_id  -- exclude already-matched primary
-- WHERE p.barcode IS NOT NULL 
--     AND p.barcode != ''
--     AND p.is_active = 1;

-- ################################################################################

-- SELECT 
--     match_method,
--     COUNT(*) AS mapped_products,
--     COUNT(DISTINCT business_id) AS bus_covered,
--     COUNT(DISTINCT master_product_id) AS masters_linked
-- FROM bi_database.map_product_master
-- GROUP BY match_method;

-- SELECT 
--     mpm.master_product_id,
--     dmp.master_product_name,
--     dmp.master_sku,
--     COUNT(DISTINCT mpm.business_id) AS bu_count,
--     GROUP_CONCAT(DISTINCT b.name ORDER BY b.name SEPARATOR ' | ') AS sold_in_bus
-- FROM bi_database.map_product_master mpm
-- INNER JOIN bi_database.dim_master_products dmp 
--     ON mpm.master_product_id = dmp.master_product_id
-- LEFT JOIN `das-db`.businesses b ON mpm.business_id = b.id
-- GROUP BY mpm.master_product_id, dmp.master_product_name, dmp.master_sku
-- HAVING COUNT(DISTINCT mpm.business_id) >= 2
-- ORDER BY bu_count DESC
-- LIMIT 50;

-- SELECT 
--     source_type,
--     COUNT(*) AS total_rows,
--     SUM(CASE WHEN master_product_id IS NULL THEN 1 ELSE 0 END) AS still_unmatched,
--     ROUND(SUM(CASE WHEN master_product_id IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) AS unmatched_pct
-- FROM bi_database.fact_saless
-- GROUP BY source_type;

-- Update previously unmatched rows using the new bridge

-- chunk 1
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id between 1 and 30000;

-- chunk 2
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id between 30001 and 60000;

-- chunk 3
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id between 60001 and 90000;

-- chunk 4
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id between 90001 and 120000;

-- chunk 5
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id between 120001 and 150000;

-- chunk 6
UPDATE bi_database.fact_saless fs
INNER JOIN bi_database.map_product_master mpm
    ON fs.product_id = mpm.product_id
    AND fs.business_id = mpm.business_id
SET fs.master_product_id = mpm.master_product_id
WHERE fs.master_product_id IS null
and fs.fact_sale_id > 150001;

-- ################################################################################

UPDATE fact_saless fs
JOIN `das-db`.branches b
  ON b.id = fs.branch_id
 AND b.business_id = fs.business_id
SET fs.branch_name = b.name;

UPDATE fact_saless fs
JOIN `das-db`.businesses b
  ON b.id = fs.business_id 
SET fs.business_name = b.name;

UPDATE fact_saless
SET margin_pct = CASE 
    WHEN net_amount IS NOT NULL AND net_amount > 0 
        THEN ROUND((gross_profit / net_amount) * 100, 2)
    ELSE 0.00
END
WHERE margin_pct IS NULL OR margin_pct = 0;

select max(sale_date) from fact_saless fs ;

TRUNCATE TABLE customers;
INSERT INTO bi_database.customers
SELECT * FROM `das-db`.customers;

TRUNCATE TABLE customer_groups;
INSERT INTO bi_database.customer_groups
SELECT * FROM `das-db`.customer_groups;
-- ################################################################################
## ETL SCRIPT COMPLETED HERE
-- ################################################################################