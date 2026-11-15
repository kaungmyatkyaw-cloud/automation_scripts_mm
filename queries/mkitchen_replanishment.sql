-- mkitchen
CREATE OR REPLACE VIEW bi_database.vw_mkitchen_store_inventory AS
SELECT 
    cm.*,
    -- Estimated Weekly Losses Calculations
    ROUND(cm.avg_weekly_sales * cm.standard_selling_price, 2) AS weekly_revenue_loss,
    CASE 
        WHEN cm.actual_margin_amount IS NOT NULL THEN ROUND(cm.avg_weekly_sales * cm.actual_margin_amount, 2)
        ELSE 0 
    END AS weekly_margin_loss,
    
    -- Masterdata Alert Status
    CASE 
        WHEN cm.is_expiry_date_tracking = true AND (cm.shelf_life_days < 30 OR cm.shelf_life_days IS NULL) THEN 'Confirm shelf life'
        WHEN cm.brand_name IS NULL OR TRIM(cm.brand_name) = '' THEN 'Confirm brand name'
        WHEN cm.is_batch_tracking = false AND cm.category_L1 != 'Containers' THEN 'No batch tracking'
        WHEN cm.is_expiry_date_tracking = false AND cm.category_L3 = 'Perishable' THEN 'No expiry date tracking'
        WHEN COALESCE(exp.red_qty, 0) > 0 THEN 'Expired Stock (Red Alert)'
        WHEN COALESCE(exp.orange_qty, 0) > 0 THEN 'Near Expiry Stock (Orange Alert)'
        ELSE 'OK'
    END AS MasterdataAlert,
    
    -- Stock Status
    CASE 
        WHEN cm.weeks_of_supply = 0 AND cm.recommended_replenishment_qty > 0 THEN '1. Shortage'
        WHEN cm.weeks_of_supply > 0 AND cm.weeks_of_supply <= 1 AND cm.recommended_replenishment_qty > 0 THEN '2. Urgent need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty > 0 THEN '3. Identified need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty = 0 THEN '4. No need'
        ELSE '6. Ageing stock'
    END AS stock_status
FROM (
    SELECT 
        p.sku,
        p.name AS product_name,
        p.brand_name,
        p.is_expiry_date_tracking,
        p.shelf_life_days,
        p.is_batch_tracking,
        p.sales_price AS standard_selling_price,
        
        -- Category Hierarchy
        COALESCE(pc2.name, pc1.name, pc.name) AS category_L1,
        CASE 
            WHEN pc2.name IS NOT NULL THEN pc1.name 
            WHEN pc1.name IS NOT NULL THEN pc.name 
            ELSE NULL 
        END AS category_L2,
        CASE 
            WHEN pc2.name IS NOT NULL THEN pc.name 
            ELSE NULL 
        END AS category_L3,
        
        -- Stock & Sales Metrics
        COALESCE(stk.total_current_stock, 0) AS total_stock,
        COALESCE(sls.avg_weekly_sales, 0) AS avg_weekly_sales,
        
        -- Weeks of Supply (WOS) Remaining
        CASE 
            WHEN COALESCE(sls.avg_weekly_sales, 0) = 0 THEN 999.0 
            ELSE ROUND(COALESCE(stk.total_current_stock, 0) / sls.avg_weekly_sales, 2)
        END AS weeks_of_supply,

        -- Recommended Order Quantity (Targeting 2 weeks of inventory)
        GREATEST(0, ROUND((sls.avg_weekly_sales * 2) - COALESCE(stk.total_current_stock, 0), 0)) AS recommended_replenishment_qty,

        -- Last Purchase & Margin Metrics
        lp.last_purchased_batch,
        DATE(lp.last_purchase_date) AS last_purchase_date,
        lp.last_purchase_cost,

        -- Actual Margin Amount
        CASE 
            WHEN lp.last_purchase_cost IS NULL THEN NULL 
            ELSE (p.sales_price - lp.last_purchase_cost) 
        END AS actual_margin_amount,
        
        -- Actual Margin Percentage (Gross Margin %)
        CASE 
            WHEN p.sales_price IS NULL OR p.sales_price = 0 OR lp.last_purchase_cost IS NULL THEN NULL
            ELSE ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
        END AS actual_margin_percentage

    FROM products p
    
    -- Subquery 1: COMBINED Sales Summary (POS + Invoices) filtered by business_id and branch_id
    LEFT JOIN (
        SELECT 
            combined_sales.product_id,
            SUM(combined_sales.total_sales_qty) AS total_sales_qty,
            SUM(combined_sales.total_sales_qty) / 4.0 AS avg_weekly_sales
        FROM (
            (
                -- 1a. POS Sales
                SELECT 
                    posd.product_id,
                    SUM(posd.detail_qty) AS total_sales_qty
                FROM pos_checkout_details posd
                JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
                WHERE posi.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
                  AND posi.branch_id = 34
                  AND posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
                  AND posi.current_status != 'Void'
                GROUP BY posd.product_id
            )
            UNION ALL
            (
                -- 1b. Standard Invoice Sales
                SELECT 
                    sid.product_id,
                    SUM(sid.detail_qty) AS total_sales_qty
                FROM sales_invoice_details sid
                JOIN sales_invoices si ON si.id = sid.sales_invoice_id
                WHERE si.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
                  AND si.branch_id = 34
                  AND si.invoice_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
                  AND si.current_status NOT IN ('Draft', 'Void')
                GROUP BY sid.product_id
            )
        ) AS combined_sales
        GROUP BY combined_sales.product_id
    ) sls ON sls.product_id = p.id

    -- Subquery 2: Stock Summary filtered by business_id and branch_id
    LEFT JOIN (
        SELECT 
            ss.product_id,
            SUM(ss.current_qty) AS total_current_stock,
            COUNT(DISTINCT ss.batch_number) AS active_batches
        FROM stock_summaries ss
        INNER JOIN warehouses w ON ss.warehouse_id = w.id AND ss.business_id = w.business_id
        WHERE ss.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
          AND w.branch_id = 34
        GROUP BY ss.product_id
    ) stk ON stk.product_id = p.id

    -- Subquery 3: Last Purchased Batch & Cost filtered by business_id and branch_id
    LEFT JOIN (
        SELECT 
            bd.product_id,
            bd.batch_number AS last_purchased_batch,
            bd.detail_unit_rate AS last_purchase_cost,
            b.bill_date AS last_purchase_date,
            ROW_NUMBER() OVER(
                PARTITION BY bd.product_id 
                ORDER BY b.bill_date DESC, b.id DESC
            ) as rn
        FROM bill_details bd
        INNER JOIN bills b ON bd.bill_id = b.id
        WHERE b.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
          AND b.branch_id = 34
          AND b.current_status NOT IN ('Draft', 'Void')
    ) lp ON lp.product_id = p.id AND lp.rn = 1

    -- Category Joins
    LEFT JOIN product_categories pc ON p.category_id = pc.id
    LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id
    LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id

    WHERE p.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
) cm
-- Subquery 4: Expiry Alert Check
LEFT JOIN (
    SELECT 
        bd.product_id,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
    FROM bill_details AS bd
    INNER JOIN bills AS bill ON bd.bill_id = bill.id
    WHERE bd.expiry_date IS NOT NULL
      AND bill.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND bill.branch_id = 34
      AND bill.current_status != 'Void'
    GROUP BY bd.product_id
) AS exp ON exp.product_id IN (
    SELECT id FROM products WHERE sku = cm.sku AND business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
)
ORDER BY weekly_revenue_loss DESC;