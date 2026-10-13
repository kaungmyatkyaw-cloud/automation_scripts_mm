/*
 * MySQL Server info:
 * db_host=db-distribution-accounting-do-user-2718740-0.h.db.ondigitalocean.com
 * db_port=25060
 * db_user=kmkyaw
 * db_pw=
 * db_name=bi_database
 */
-- show databases;
-- use bi_database;
-- show tables;
-- ################################################################################

-- These schemas are already created in database
-- CREATE TABLE bi_database.customer_groups LIKE `das-db`.customer_groups;
-- INSERT INTO bi_database.customer_groups
-- SELECT * FROM `das-db`.customer_groups;

-- CREATE TABLE bi_database.customers LIKE `das-db`.customers;
-- INSERT INTO bi_database.customers
-- SELECT * FROM `das-db`.customers;
-- 
-- CREATE TABLE bi_database.sales_people LIKE `das-db`.sales_people;
-- INSERT INTO bi_database.sales_people
-- SELECT * FROM `das-db`.sales_people;

-- select * from sales_people sp ;

-- ==========================================
-- Table: active_BUs
-- Purpose: Master Data Management (MDM) - Active Business Unit & Branch Registry
-- Epic 3: Master Data Management & Data Warehouse Build
-- ==========================================
/*
DROP TABLE IF EXISTS `active_BUs`;

CREATE TABLE `active_BUs` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `business_id` VARCHAR(191) NOT NULL COMMENT 'UUID of the Business Unit',
    `business_name` VARCHAR(100) NOT NULL COMMENT 'Display name of the Business Unit',
    `business_code` VARCHAR(50) NOT NULL COMMENT 'Short code for the BU',
    `branch_id` BIGINT NOT NULL COMMENT 'Branch ID from das-db.branches',
    `branch_name` VARCHAR(100) NOT NULL COMMENT 'Branch name',
    `state` VARCHAR(100) DEFAULT NULL COMMENT 'State/Region',
    `township` VARCHAR(100) DEFAULT NULL COMMENT 'Township',
    `branch_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 = Active, 0 = Inactive',
    `branch_type` VARCHAR(50) DEFAULT NULL COMMENT 'Primary, Secondary, etc.',
    `Identifier` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'BI inclusion flag',
    `BI_Called` VARCHAR(255) NOT NULL COMMENT 'Display name used in BI dashboards',
    `created_at` DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    `updated_at` DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_active_bus_biz_branch` (`business_id`, `branch_id`),
    INDEX `idx_active_bus_business_id` (`business_id`),
    INDEX `idx_active_bus_branch_id` (`branch_id`),
    INDEX `idx_active_bus_business_code` (`business_code`),
    INDEX `idx_active_bus_branch_active` (`branch_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Active Business Units & Branches for BI Reporting';

-- ################################################################################

INSERT INTO `active_BUs` 
    (`business_id`, `business_name`, `business_code`, `branch_id`, `branch_name`, 
     `state`, `township`, `branch_active`, `branch_type`, `Identifier`, `BI_Called`)
VALUES
-- M-Kitchen
('84093770-29ad-4e8e-9da1-babe583c0d69', 'M-Kitchen', 'mkitchen', 34, 'Distribution (YGN)', 'Yangon', NULL, 1, '✅ Primary', TRUE, 'M-Kitchen - Distribution (Ygn) (Primary HQ)'),

-- Marathon Express
('fde62d0f-a449-4511-a011-58accd492a85', 'MarathonExpress', 'mexpress', 52, 'Primary Branch', 'Yangon', NULL, 1, '✅ Primary', TRUE, 'Marathonexpress - Primary Branch (Primary HQ)'),

-- Shwe Zay KPG
('1eb52cc2-7a34-43d8-b646-67cc60402916', 'Shwe Zay KPG', 'shwezay_kpg', 62, 'KPG Operation', 'Kyaukpadaung', NULL, 1, '✅ Primary', TRUE, 'Shwe Zay Kpg - Kpg Operation (Primary HQ)'),
('1eb52cc2-7a34-43d8-b646-67cc60402916', 'Shwe Zay KPG', 'shwezay_kpg', 65, 'KPG Finance', 'Kyaukpadaung', NULL, 1, NULL, TRUE, 'Shwe Zay Kpg - Kpg Finance (Primary HQ)'),
('1eb52cc2-7a34-43d8-b646-67cc60402916', 'Shwe Zay KPG', 'shwezay_kpg', 63, 'KPG Management and Admin', 'Kyaukpadaung', NULL, 1, NULL, TRUE, 'Shwe Zay Kpg - Kpg Management And Admin (Primary HQ)'),
('1eb52cc2-7a34-43d8-b646-67cc60402916', 'Shwe Zay KPG', 'shwezay_kpg', 64, 'KPG Sale and Marketing', 'Kyaukpadaung', NULL, 1, NULL, TRUE, 'Shwe Zay Kpg - Kpg Sale And Marketing (Primary HQ)'),

-- Shwe Zay YGN
('ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', 'Shwe Zay YGN', 'shwezay_ygn', 79, 'YGN Operation', 'Yangon', NULL, 1, '✅ Primary', TRUE, 'Shwe Zay Ygn - Ygn Operation (Primary HQ)'),
('ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', 'Shwe Zay YGN', 'shwezay_ygn', 106, 'YGN Finance', 'Yangon', NULL, 1, NULL, TRUE, 'Shwe Zay Ygn - Ygn Finance (Primary HQ)'),
('ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', 'Shwe Zay YGN', 'shwezay_ygn', 92, 'YGN HQ', 'Yangon', NULL, 1, NULL, TRUE, 'Shwe Zay Ygn - Ygn Hq (Primary HQ)'),
('ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', 'Shwe Zay YGN', 'shwezay_ygn', 83, 'YGN Management and Admin', 'Yangon', NULL, 1, NULL, TRUE, 'Shwe Zay Ygn - Ygn Management And Admin (Primary HQ)'),
('ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', 'Shwe Zay YGN', 'shwezay_ygn', 91, 'YGN Sale & Marketing', 'Yangon', NULL, 1, NULL, TRUE, 'Shwe Zay Ygn - Ygn Sale & Marketing (Primary HQ)'),

-- ShweZay (Nay Pyi Taw)
('2d393763-d5c7-42be-b345-84b7be787f10', 'ShweZay (Nay Pyi Taw)', 'ShweZay_Npt', 43, 'NPT - Operation', 'Nay Pyi Taw', NULL, 1, '✅ Primary', TRUE, 'Shwezay (Nay Pyi Taw) - Npt - Operation (Primary HQ)'),
('2d393763-d5c7-42be-b345-84b7be787f10', 'ShweZay (Nay Pyi Taw)', 'ShweZay_Npt', 49, 'NPT - Finance', 'Nay Pyi Taw', NULL, 1, NULL, TRUE, 'Shwezay (Nay Pyi Taw) - Npt - Finance (Primary HQ)'),
('2d393763-d5c7-42be-b345-84b7be787f10', 'ShweZay (Nay Pyi Taw)', 'ShweZay_Npt', 50, 'NPT - Management & Admin', 'Nay Pyi Taw', NULL, 1, NULL, TRUE, 'Shwezay (Nay Pyi Taw) - Npt - Management & Admin (Primary HQ)'),
('2d393763-d5c7-42be-b345-84b7be787f10', 'ShweZay (Nay Pyi Taw)', 'ShweZay_Npt', 55, 'NPT - Sale & Marketing', 'Nay Pyi Taw', NULL, 1, NULL, TRUE, 'Shwezay (Nay Pyi Taw) - Npt - Sale & Marketing (Primary HQ)');
*/
-- select * from active_BUs ab ;
-- ################################################################################
/*
DROP TABLE IF exists bi_database.dim_master_products_categorized;
CREATE TABLE bi_database.dim_master_products_categorized (
    master_product_id BIGINT NOT NULL,
    primary_source_id BIGINT NOT NULL,
    primary_business_id VARCHAR(191) NOT NULL,
    master_match_key VARCHAR(255) NOT NULL,
    master_barcode VARCHAR(100) NULL,
    master_sku VARCHAR(100) NULL,
    master_product_name VARCHAR(255) NOT NULL,
    master_description TEXT NULL,
    brand_name VARCHAR(100) NULL,
    category_id BIGINT NULL,
    unit_id BIGINT NULL,
    sales_price DECIMAL(20,4) NULL DEFAULT 0.0000,
    purchase_price DECIMAL(20,4) NULL DEFAULT 0.0000,
    last_updated_at DATETIME(3) NULL,
    
    -- CSV အတိုင်း Column နာမည်များ တိုက်ရိုက် ပြင်ဆင်ထား
    category VARCHAR(150) NULL,
    level_2_category VARCHAR(150) NULL,
    level_3_category VARCHAR(150) NULL,
    
    PRIMARY KEY (master_product_id),
    INDEX idx_primary_business (primary_business_id),
    INDEX idx_master_match_key (master_match_key),
    INDEX idx_master_barcode (master_barcode),
    INDEX idx_category (category),
    INDEX idx_level_2 (level_2_category),
    INDEX idx_level_3 (level_3_category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ################################################################################
-- ALTER TABLE bi_database.dim_master_products_categorized
--     RENAME COLUMN category TO original_category,
--     RENAME COLUMN level_2_category TO sub_category,
--     RENAME COLUMN level_3_category TO category;

-- ALTER TABLE bi_database.fact_saless
-- ADD COLUMN sales_person_id BIGINT DEFAULT NULL AFTER customer_id;

-- ################################################################################

DROP TABLE IF EXISTS bi_database.fact_saless;

-- ################################################################################
 
CREATE TABLE bi_database.fact_saless (
    fact_sale_id        BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- ── Source Identification ──
    source_type         ENUM('INVOICE','POS') NOT NULL,
    source_header_id    BIGINT NOT NULL COMMENT 'sales_invoices.id or pos_checkout_invoice_payments.id',
    source_detail_id    BIGINT NOT NULL COMMENT 'sales_invoice_details.id or pos_checkout_details.id',
    transaction_number  VARCHAR(255) COMMENT 'invoice_number or checkout_number',
    header_status       VARCHAR(20),

    -- ── Business Context ──
    business_id         VARCHAR(191) NOT NULL,
    branch_id           BIGINT,
    warehouse_id        BIGINT,
    customer_id         BIGINT,
    currency_id         BIGINT,
    exchange_rate       DECIMAL(20,4) DEFAULT 1.0000,

    -- ── Date ──
    sale_datetime       DATETIME(3) NOT NULL,
    sale_date           DATE AS (DATE(sale_datetime)) STORED,

    -- ── Product (BU-Level) ──
    product_id          BIGINT,
    product_type        CHAR(1) DEFAULT 'S',
    product_name        VARCHAR(255),
    product_sku         VARCHAR(100),
    product_barcode     VARCHAR(100),
    product_category    VARCHAR(150),
    product_brand       VARCHAR(100),
    batch_number        VARCHAR(100),

    -- ── Master Product Link & Descriptives ──
    master_product_id   BIGINT COMMENT 'FK → dim_master_products.master_product_id',
    master_sku          VARCHAR(100),
    master_barcode      VARCHAR(100),
    master_product_name VARCHAR(255),
    master_brand_name   VARCHAR(100),
    master_category     VARCHAR(150),
    master_sub_category VARCHAR(150),

    -- ── Measures ──
    quantity            DECIMAL(20,4) DEFAULT 0.0000,
    unit_rate           DECIMAL(20,4) DEFAULT 0.0000,
    discount_amount     DECIMAL(20,4) DEFAULT 0.0000,
    tax_amount          DECIMAL(20,4) DEFAULT 0.0000,
    net_amount          DECIMAL(20,4) DEFAULT 0.0000 COMMENT 'detail_total_amount',
    cogs_amount         DECIMAL(20,4) DEFAULT 0.0000,
    gross_profit        DECIMAL(20,4) AS (net_amount - cogs_amount) STORED,
    margin_pct          DECIMAL(20,4) AS (
                            CASE WHEN net_amount <> 0 
                                 THEN (net_amount - cogs_amount) / net_amount * 100 
                                 ELSE 0 END
                        ) STORED,

    -- ── Audit ──
    etl_loaded_at       DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),

    -- ── Indexes ──
    INDEX idx_fs_biz_date       (business_id, sale_date),
    INDEX idx_fs_date           (sale_date),
    INDEX idx_fs_product        (product_id),
    INDEX idx_fs_master         (master_product_id),
    INDEX idx_fs_source         (source_type, source_header_id, source_detail_id),
    INDEX idx_fs_branch         (branch_id),
    INDEX idx_fs_customer       (customer_id),
    INDEX idx_fs_batch          (batch_number),
    INDEX idx_fs_product_sku    (product_sku),
    INDEX idx_fs_master_sku     (master_sku),
    INDEX idx_fs_master_cat     (master_category),
    INDEX idx_fs_master_brand   (master_brand_name)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE bi_database.fact_saless
    MODIFY COLUMN margin_pct DECIMAL(30,4) AS (
        CASE WHEN net_amount <> 0 
             THEN (net_amount - cogs_amount) / net_amount * 100 
             ELSE 0 END
    ) STORED;

ALTER TABLE fact_saless 
ADD COLUMN branch_name VARCHAR(100) NULL AFTER branch_id;

ALTER TABLE fact_saless 
ADD COLUMN business_name VARCHAR(100) NULL AFTER business_id;

-- fact table
ALTER TABLE bi_database.fact_saless
ADD INDEX idx_fact_saless_product_business (product_id, business_id);

-- products table should ideally support id + business_id lookup
-- product_categories should support id + business_id lookup
*/



-- ################################################################################
-- ETL PROCESS STATED HERE
-- ################################################################################

USE bi_database;
SET sql_safe_updates = 0;

TRUNCATE TABLE bi_database.fact_saless;

select * from bi_database.fact_saless;
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

-- select max(fs.sale_date) from fact_saless fs ;

-- ################################################################################
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

-- ################################################################################

## ETL SCRIPT COMPLETED HERE

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
-- ################################################################################
-- Rebuild aggregate using only active BUs
-- TRUNCATE TABLE bi_database.agg_product_sales;

-- -- ################################################################################

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

-- select * from agg_product_sales aps ;

-- select * from active_BUs ab ;
-- -- ################################################################################
-- -- Should return 0 duplicates
-- SELECT master_product_id, COUNT(*) AS cnt
-- FROM bi_database.agg_product_sales
-- GROUP BY master_product_id
-- HAVING COUNT(*) > 1;

-- -- ################################################################################
-- -- Total products in aggregate
-- SELECT COUNT(*) AS total_products, 
--        ROUND(SUM(total_revenue), 2) AS grand_revenue
-- FROM bi_database.agg_product_sales;

-- select * from fact_saless fs ;