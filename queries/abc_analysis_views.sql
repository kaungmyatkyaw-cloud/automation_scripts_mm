USE bi_database;
SET sql_safe_updates = 0;

CREATE OR REPLACE VIEW bi_database.vw_shwezay_abc_analysis AS
WITH product_sales AS (
    -- Step 1: Product တစ်ခုချင်းစီ၏ Total Revenue & Total Quantity ကို တွက်ထုတ်ခြင်း
    SELECT 
        fs.business_id,
        fs.business_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product') AS product_name,
        SUM(fs.quantity) AS total_quantity,
        SUM(fs.net_amount) AS total_revenue
    FROM bi_database.fact_saless fs
    WHERE fs.business_id IN (
        'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08', -- YGN
        '2d393763-d5c7-42be-b345-84b7be787f10', -- NPT
        '1eb52cc2-7a34-43d8-b646-67cc60402916'  -- KPG
    )
    -- CURRENT_DATE() သို့မဟုတ် '2026-01-01' မှ ယနေ့အထိ Date Range Filter
    AND fs.sale_date >= '2026-01-01'
    AND fs.sale_date <= CURRENT_DATE()
    GROUP BY 
        fs.business_id,
        fs.business_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product')
),
ranked_sales AS (
    -- Step 2: Cumulative Sum & Grand Total တွက်ချက်ခြင်း
    SELECT 
        business_id,
        business_name,
        product_name,
        total_quantity,
        total_revenue,
        SUM(total_revenue) OVER (PARTITION BY business_id ORDER BY total_revenue DESC) AS cumulative_revenue,
        SUM(total_revenue) OVER (PARTITION BY business_id) AS grand_total_revenue
    FROM product_sales
)
-- Step 3: ABC Classification သတ်မှတ်ခြင်း
SELECT 
    business_id,
    business_name,
    product_name,
    total_quantity,
    total_revenue,
    ROUND((total_revenue / grand_total_revenue) * 100, 2) AS revenue_share_pct,
    ROUND((cumulative_revenue / grand_total_revenue) * 100, 2) AS cumulative_share_pct,
    CASE 
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.80 THEN 'Class A (80%)'
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.95 THEN 'Class B (15%)'
        ELSE 'Class C (5%)'
    END AS abc_class
FROM ranked_sales;

-- ==============================================================

CREATE OR REPLACE VIEW bi_database.vw_mtrading_abc_analysis AS
WITH product_sales AS (
    -- Step 1: M-Kitchen ၏ Product တစ်ခုချင်းစီအလိုက် Total Revenue & Total Quantity ကို တွက်ထုတ်ခြင်း
    SELECT 
        fs.business_id,
        fs.business_name,
        fs.branch_id,
        fs.branch_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product') AS product_name,
        SUM(fs.quantity) AS total_quantity,
        SUM(fs.net_amount) AS total_revenue
    FROM bi_database.fact_saless fs
    WHERE fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND fs.branch_id != 34
      OR  fs.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642'
      AND fs.sale_date >= '2026-01-01'
      AND fs.sale_date <= CURRENT_DATE()
    GROUP BY 
        fs.business_id,
        fs.business_name,
        fs.branch_id,
        fs.branch_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product')
),
ranked_sales AS (
    -- Step 2: M-Kitchen အတွက် Cumulative Revenue & Grand Total Revenue တွက်ချက်ခြင်း
    SELECT 
        business_id,
        business_name,
        branch_id,
        branch_name,
        product_name,
        total_quantity,
        total_revenue,
        SUM(total_revenue) OVER (ORDER BY total_revenue DESC) AS cumulative_revenue,
        SUM(total_revenue) OVER () AS grand_total_revenue
    FROM product_sales
)
-- Step 3: ABC Classification (Class A: 80%, Class B: 15%, Class C: 5%) သတ်မှတ်ခြင်း
SELECT 
    business_id,
    business_name,
    branch_id,
    branch_name,
    product_name,
    total_quantity,
    total_revenue,
    ROUND((total_revenue / grand_total_revenue) * 100, 2) AS revenue_share_pct,
    ROUND((cumulative_revenue / grand_total_revenue) * 100, 2) AS cumulative_share_pct,
    CASE 
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.80 THEN 'Class A (80%)'
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.95 THEN 'Class B (15%)'
        ELSE 'Class C (5%)'
    END AS abc_class
FROM ranked_sales;


-- ==========================================================
CREATE OR REPLACE VIEW bi_database.vw_mkitchen_abc_analysis AS
WITH product_sales AS (
    -- Step 1: M-Kitchen ၏ Product တစ်ခုချင်းစီအလိုက် Total Revenue & Total Quantity ကို တွက်ထုတ်ခြင်း
    SELECT 
        fs.business_id,
        fs.business_name,
        fs.branch_id,
        fs.branch_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product') AS product_name,
        SUM(fs.quantity) AS total_quantity,
        SUM(fs.net_amount) AS total_revenue
    FROM bi_database.fact_saless fs
    WHERE fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND fs.branch_id = 34
      AND fs.sale_date >= '2026-01-01'
      AND fs.sale_date <= CURRENT_DATE()
    GROUP BY 
        fs.business_id,
        fs.business_name,
        fs.branch_id,
        fs.branch_name,
        COALESCE(fs.product_name, fs.master_product_name, 'Unassigned Product')
),
ranked_sales AS (
    -- Step 2: M-Kitchen အတွက် Cumulative Revenue & Grand Total Revenue တွက်ချက်ခြင်း
    SELECT 
        business_id,
        business_name,
        branch_id,
        branch_name,
        product_name,
        total_quantity,
        total_revenue,
        SUM(total_revenue) OVER (ORDER BY total_revenue DESC) AS cumulative_revenue,
        SUM(total_revenue) OVER () AS grand_total_revenue
    FROM product_sales
)
-- Step 3: ABC Classification (Class A: 80%, Class B: 15%, Class C: 5%) သတ်မှတ်ခြင်း
SELECT 
    business_id,
    business_name,
    branch_id,
    branch_name,
    product_name,
    total_quantity,
    total_revenue,
    ROUND((total_revenue / grand_total_revenue) * 100, 2) AS revenue_share_pct,
    ROUND((cumulative_revenue / grand_total_revenue) * 100, 2) AS cumulative_share_pct,
    CASE 
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.80 THEN 'Class A (80%)'
        WHEN (cumulative_revenue / grand_total_revenue) <= 0.95 THEN 'Class B (15%)'
        ELSE 'Class C (5%)'
    END AS abc_class
FROM ranked_sales;