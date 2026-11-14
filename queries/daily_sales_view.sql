CREATE OR REPLACE VIEW bi_database.vw_daily_sales_summary AS
SELECT
    fs.sale_date,
    fs.business_id,
    CASE
        WHEN fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
             AND fs.branch_id = 34 THEN 'M-Kitchen'
        WHEN (
                 fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
                 AND (TRIM(CAST(fs.branch_id AS CHAR)) != '34' OR fs.branch_id IS NULL)
             )
             OR fs.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642' THEN 'M-Trading'
        ELSE fs.business_name
    END AS business_name,
    fs.branch_id,
    fs.branch_name,
    fs.source_type,

    -- Transaction & Volume KPIs
    COUNT(DISTINCT CONCAT(fs.source_type, '-', fs.source_header_id)) AS total_transactions,
    COUNT(*) AS total_line_items,
    COUNT(DISTINCT fs.customer_id) AS unique_customers,
    ROUND(SUM(COALESCE(fs.quantity, 0)), 4) AS total_quantity,

    -- Revenue, Discount, Tax & COGS KPIs
    ROUND(SUM(COALESCE(fs.quantity, 0) * COALESCE(fs.unit_rate, 0)), 2) AS gross_sales_amount,
    ROUND(SUM(COALESCE(fs.discount_amount, 0)), 2) AS total_discount_amount,
    ROUND(SUM(COALESCE(fs.tax_amount, 0)), 2) AS total_tax_amount,
    ROUND(SUM(COALESCE(fs.net_amount, 0)), 2) AS net_sales_amount,
    ROUND(SUM(COALESCE(fs.cogs_amount, 0)), 2) AS total_cogs_amount,

    -- Profitability KPIs
    ROUND(SUM(COALESCE(fs.gross_profit, 0)), 2) AS total_gross_profit,
    ROUND(
        (SUM(COALESCE(fs.gross_profit, 0)) / NULLIF(SUM(COALESCE(fs.net_amount, 0)), 0)) * 100,
        2
    ) AS gross_margin_pct,

    -- Unit Economics KPIs
    ROUND(
        SUM(COALESCE(fs.net_amount, 0)) / NULLIF(COUNT(DISTINCT CONCAT(fs.source_type, '-', fs.source_header_id)), 0),
        2
    ) AS avg_transaction_value,
    ROUND(
        SUM(COALESCE(fs.quantity, 0)) / NULLIF(COUNT(DISTINCT CONCAT(fs.source_type, '-', fs.source_header_id)), 0),
        2
    ) AS avg_units_per_transaction,

    -- Audit / Freshness
    MAX(fs.etl_loaded_at) AS last_etl_loaded_at

FROM bi_database.fact_saless fs
WHERE (fs.header_status IS NULL OR fs.header_status NOT IN ('Void', 'Draft'))
  AND fs.sale_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
  AND fs.sale_date < DATE_ADD(DATE_FORMAT(CURDATE(), '%Y-%m-01'), INTERVAL 1 MONTH)
GROUP BY
    fs.sale_date,
    fs.business_id,
    CASE
        WHEN fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
             AND fs.branch_id = 34 THEN 'M-Kitchen'
        WHEN (
                 fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
                 AND (TRIM(CAST(fs.branch_id AS CHAR)) != '34' OR fs.branch_id IS NULL)
             )
             OR fs.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642' THEN 'M-Trading'
        ELSE fs.business_name
    END,
    fs.branch_id,
    fs.branch_name,
    fs.source_type;