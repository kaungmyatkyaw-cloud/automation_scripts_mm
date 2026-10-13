-- ┌─────────────────────────┐      ┌─────────────────────────┐
-- │ das-db.sales_invoices   │      │ das-db.pos_checkouts    │
-- └────────────┬────────────┘      └────────────┬────────────┘
--              │ (INVOICE Data)                 │ (POS Data)
--              └──────────────┬─────────────────┘
--                             ▼
--            ┌──────────────────────────────────┐
--            │   TRUNCATE & INSERT Initial Data │
--            │   into bi_database.fact_saless   │
--            └────────────────┬─────────────────┘
--                             │
--                             ▼
--            ┌──────────────────────────────────┐
--            │ Step 1: Chunk-based Backfill     │
--            │ (Product & Category Mapping)     │
--            └────────────────┬─────────────────┘
--                             │
--                             ▼
--            ┌──────────────────────────────────┐
--            │ Step 2: Salesperson Backfill     │
--            │ (Invoice & POS Header Joins)     │
--            └────────────────┬─────────────────┘
--                             │
--                             ▼
--            ┌──────────────────────────────────┐
--            │ Step 3: Master Product Mapping   │
--            │ (Bridge Mapping & Master Sync)   │
--            └────────────────┬─────────────────┘
--                             │
--                             ▼
--            ┌──────────────────────────────────┐
--            │ Step 4: Dimension Enrichment     │
--            │ (Business & Branch Names)        │
--            └──────────────────────────────────┘

-- ################################################################################
-- ETL PROCESS STATED HERE
-- ################################################################################
USE bi_database;
SET sql_safe_updates = 0;
SET MAX_EXECUTION_TIME = 800000;

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

-- DELIMITER //

-- CREATE PROCEDURE sp_update_fact_sales_in_chunks()
-- BEGIN
--     DECLARE min_id INT DEFAULT 1;
--     DECLARE max_id INT DEFAULT 5000;
--     DECLARE total_max_id INT DEFAULT 0;

--     -- fact_sale_id ရဲ့ Maximum ID ကို ဆွဲထုတ်ပါသည်
--     SELECT IFNULL(MAX(fact_sale_id), 0) INTO total_max_id FROM bi_database.fact_saless;

--     WHILE min_id <= total_max_id DO
--         UPDATE bi_database.fact_saless fs
--         INNER JOIN `das-db`.products p 
--             ON fs.product_id = p.id AND fs.business_id = p.business_id
--         LEFT JOIN `das-db`.product_categories pc 
--             ON p.category_id = pc.id AND p.business_id = pc.business_id
--         SET 
--             fs.product_sku      = p.sku,
--             fs.product_barcode  = p.barcode,
--             fs.product_category = pc.name,
--             fs.product_brand    = p.brand_name
--         WHERE fs.product_id IS NOT NULL
--           AND fs.fact_sale_id BETWEEN min_id AND max_id;

--         -- Batch တစ်ခုပြီးတိုင်း Next Range သို့ သွားပါမည်
--         SET min_id = min_id + 5000;
--         SET max_id = max_id + 5000;
--     END WHILE;
-- END //

-- DELIMITER ;

-- ################################################################################


CALL bi_database.sp_update_fact_sales_in_chunks();

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
  AND (fs.product_sku IS NULL OR fs.product_category IS NULL);


-- ################################################################################
-- Sale Person update

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


-- ################################################################################
-- DROP PROCEDURE IF EXISTS sp_update_master_product_details_in_chunks;
-- DELIMITER //

-- CREATE PROCEDURE sp_update_master_product_details_in_chunks()
-- BEGIN
--     DECLARE min_id INT DEFAULT 1;
--     DECLARE max_id INT DEFAULT 5000;
--     DECLARE total_max_id INT DEFAULT 0;

--     -- fact_sale_id ရဲ့ Maximum ID ကို ဆွဲထုတ်ပါသည်
--     SELECT IFNULL(MAX(fact_sale_id), 0) INTO total_max_id FROM bi_database.fact_saless;

--     WHILE min_id <= total_max_id DO
--         UPDATE bi_database.fact_saless fs
--         INNER JOIN bi_database.dim_master_products dmp 
--             ON fs.master_product_id = dmp.master_product_id
--         SET 
--             fs.master_sku           = dmp.master_sku,
--             fs.master_barcode       = dmp.master_barcode,
--             fs.master_product_name  = dmp.master_product_name,
--             fs.master_brand_name    = dmp.brand_name,
--             fs.master_category      = dmp.category,
--             fs.master_sub_category  = dmp.sub_category
--         WHERE fs.master_product_id IS NOT NULL
--           AND fs.fact_sale_id BETWEEN min_id AND max_id;

--         -- Next Range
--         SET min_id = min_id + 5000;
--         SET max_id = max_id + 5000;
--     END WHILE;
-- END //

-- DELIMITER ;

-- ################################################################################

-- Procedure ကို Run ရန်
CALL bi_database.sp_update_master_product_details_in_chunks();

-- ################################################################################
-- Check  
-- SELECT 
--     COUNT(*) AS total_rows,
--     SUM(CASE WHEN product_sku IS NOT NULL THEN 1 ELSE 0 END) AS has_bu_sku,
--     SUM(CASE WHEN master_sku IS NOT NULL THEN 1 ELSE 0 END) AS has_master_sku,
--     ROUND(SUM(CASE WHEN product_sku IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*)*100,1) AS bu_sku_pct,
--     ROUND(SUM(CASE WHEN master_sku IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*)*100,1) AS master_sku_pct
-- FROM bi_database.fact_saless;

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
--     
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

-- Truncate Table map_product_master;
-- -- -- 1) Insert PRIMARY matches (already known)
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

-- ################################################################################
/*
SELECT 
    COUNT(DISTINCT fs.master_product_id) AS total_master_products_sold,
    COUNT(DISTINCT CASE WHEN sub.bu_cnt >= 2 THEN fs.master_product_id END) AS cross_bu_products,
    COUNT(DISTINCT CASE WHEN sub.bu_cnt = 1 THEN fs.master_product_id END) AS single_bu_products,
    ROUND(
        COUNT(DISTINCT CASE WHEN sub.bu_cnt >= 2 THEN fs.master_product_id END) * 100.0 
        / COUNT(DISTINCT fs.master_product_id), 1
    ) AS cross_bu_pct
FROM bi_database.fact_saless fs
INNER JOIN (
    SELECT master_product_id, COUNT(DISTINCT business_id) AS bu_cnt
    FROM bi_database.fact_saless
    WHERE master_product_id IS NOT NULL
    GROUP BY master_product_id
) sub ON fs.master_product_id = sub.master_product_id
WHERE fs.master_product_id IS NOT NULL;
*/

-- ################################################################################
-- Which BU has the most unmatched rows?
-- SELECT 
--     b.name AS bu_name,
--     COUNT(*) AS unmatched_rows,
--     ROUND(SUM(fs.net_amount), 2) AS unmatched_revenue
-- FROM bi_database.fact_saless fs
-- LEFT JOIN `das-db`.businesses b ON fs.business_id = b.id
-- WHERE fs.master_product_id IS NULL
-- GROUP BY b.name
-- ORDER BY unmatched_revenue DESC;

-- ################################################################################
-- Rebuild aggregate using only active BUs
Truncate TABLE bi_database.agg_product_sales;
-- ################################################################################
-- 
-- INSERT INTO bi_database.agg_product_sales (
--     master_product_id, master_sku, master_barcode, master_product_name,
--     brand_name, category, sub_category,
--     total_transactions, sold_across_bu_count,
--     total_qty_sold, total_revenue, total_cogs, total_gross_profit,
--     overall_margin_pct, invoice_revenue, pos_revenue,
--     first_sale_date, last_sale_date, last_refreshed_at
-- )
-- SELECT 
--     fs.master_product_id,
--     MAX(fs.master_sku) AS master_sku,
--     MAX(fs.master_barcode) AS master_barcode,
--     MAX(fs.master_product_name) AS master_product_name,
--     MAX(fs.master_brand_name) AS brand_name,
--     MAX(fs.master_category) AS category,
--     MAX(fs.master_sub_category) AS sub_category,
--     COUNT(DISTINCT fs.source_header_id) AS total_transactions,
--     COUNT(DISTINCT fs.business_id) AS sold_across_bu_count,
--     SUM(fs.quantity) AS total_qty_sold,
--     SUM(fs.net_amount) AS total_revenue,
--     SUM(fs.cogs_amount) AS total_cogs,
--     SUM(fs.gross_profit) AS total_gross_profit,
--     CASE 
--         WHEN SUM(fs.net_amount) = 0 THEN 0
--         ELSE ROUND(SUM(fs.gross_profit) / SUM(fs.net_amount) * 100, 2)
--     END AS overall_margin_pct,
--     SUM(CASE WHEN fs.source_type = 'INVOICE' THEN fs.net_amount ELSE 0 END) AS invoice_revenue,
--     SUM(CASE WHEN fs.source_type = 'POS' THEN fs.net_amount ELSE 0 END)     AS pos_revenue,
--     MIN(fs.sale_date) AS first_sale_date,
--     MAX(fs.sale_date) AS last_sale_date,
--     CURRENT_TIMESTAMP() AS last_refreshed_at
-- FROM bi_database.fact_saless fs
-- INNER JOIN bi_database.active_BUs abu 
--     ON fs.business_id = abu.business_id COLLATE utf8mb4_0900_ai_ci
-- WHERE fs.master_product_id IS NOT NULL
--   AND abu.Identifier = 1
-- GROUP BY fs.master_product_id;

-- -- ################################################################################
-- -- Should return 0 duplicates
-- SELECT master_product_id, COUNT(*) AS cnt
-- FROM bi_database.agg_product_sales
-- GROUP BY master_product_id
-- HAVING COUNT(*) > 1;
 
-- ################################################################################
-- Total products in aggregate
-- SELECT COUNT(*) AS total_products, 
--        ROUND(SUM(total_revenue), 2) AS grand_revenue
-- FROM bi_database.agg_product_sales

UPDATE fact_saless
SET margin_pct = CASE 
    WHEN net_amount IS NOT NULL AND net_amount > 0 
        THEN ROUND((gross_profit / net_amount) * 100, 2)
    ELSE 0.00
END
WHERE margin_pct IS NULL OR margin_pct = 0;