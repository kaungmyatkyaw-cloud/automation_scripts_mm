CREATE OR REPLACE VIEW bi_database.vw_weekly_bu_sales_summary AS
WITH base_sales AS (
    SELECT 
        fs.sale_datetime,
        fs.net_amount,
        YEARWEEK(fs.sale_datetime, 1) AS yw,
        DATE_FORMAT(fs.sale_datetime, '%b') AS month_name,
        MONTH(fs.sale_datetime) AS month_num,
        CASE 
            WHEN fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND fs.branch_id = 34 THEN 'M-Kitchen'
            WHEN (fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(fs.branch_id AS CHAR)) != '34' OR fs.branch_id IS NULL))
                 OR (fs.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642') THEN 'M-Trading'
            WHEN fs.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08' THEN 'ShweZay (YGN)'
            WHEN fs.business_id = '2d393763-d5c7-42be-b345-84b7be787f10' THEN 'ShweZay (NPT)'
            WHEN fs.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916' THEN 'ShweZay (KPG)'
            ELSE NULL
        END AS business_unit_branch
    FROM bi_database.fact_saless fs
    -- ၂၀၂၆ အတွက် Performance အကောင်းဆုံး Filter စစ်ထုတ်နည်း (Index Scan ဝင်စေရန်)
    WHERE fs.sale_datetime >= '2026-01-01 00:00:00' 
      AND fs.sale_datetime < '2027-01-01 00:00:00'
)
SELECT 
    CONCAT('W-', LPAD(MOD(yw, 100), 2, '0')) AS week_name,
    yw AS year_week_code,
    month_name,
    month_num,
    MIN(DATE(sale_datetime)) AS week_start_date,
    MAX(DATE(sale_datetime)) AS week_end_date,
    business_unit_branch,
    SUM(net_amount) AS total_sales_amount
FROM base_sales
WHERE business_unit_branch IS NOT NULL
GROUP BY 
    yw,
    month_name,
    month_num,
    business_unit_branch
ORDER BY yw, month_num;

select * from vw_weekly_bu_sales_summary
order by month_num desc;




