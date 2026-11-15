CREATE OR REPLACE VIEW bi_database.vw_shwezay_all_stores_inventory AS
-- 1. ShweZay NPT
SELECT
    'ShweZay NPT' AS store_name,
    '2d393763-d5c7-42be-b345-84b7be787f10' AS business_id,
    cm.warehouse_name,
    cm.sku,
    cm.product_name,
    cm.brand_name,
    cm.is_expiry_date_tracking,
    cm.shelf_life_days,
    cm.is_batch_tracking,
    cm.standard_selling_price,
    cm.category_L1,
    cm.category_L2,
    cm.category_L3,
    cm.total_stock,
    cm.avg_weekly_sales,
    cm.weeks_of_supply,
    cm.recommended_replenishment_qty,
    cm.last_purchased_batch,
    cm.last_purchase_date,
    cm.last_purchase_cost,
    cm.actual_margin_amount,
    cm.actual_margin_percentage,
    ROUND(cm.avg_weekly_sales * cm.standard_selling_price, 2) AS weekly_revenue_loss,
    CASE 
        WHEN cm.actual_margin_amount IS NOT NULL THEN ROUND(cm.avg_weekly_sales * cm.actual_margin_amount, 2)
        ELSE 0 
    END AS weekly_margin_loss,
    CASE 
        WHEN cm.is_expiry_date_tracking = true AND (cm.shelf_life_days < 30 OR cm.shelf_life_days IS NULL) THEN 'Confirm shelf life'
        WHEN cm.brand_name IS NULL OR TRIM(cm.brand_name) = '' THEN 'Confirm brand name'
        WHEN cm.is_batch_tracking = false AND cm.category_L1 != 'Containers' THEN 'No batch tracking'
        WHEN cm.is_expiry_date_tracking = false AND cm.category_L3 = 'Perishable' THEN 'No expiry date tracking'
        WHEN COALESCE(exp.red_qty, 0) > 0 THEN 'Expired Stock (Red Alert)'
        WHEN COALESCE(exp.orange_qty, 0) > 0 THEN 'Near Expiry Stock (Orange Alert)'
        ELSE 'OK'
    END AS MasterdataAlert,
    CASE 
        WHEN cm.weeks_of_supply = 0 AND cm.recommended_replenishment_qty > 0 THEN '1. Shortage'
        WHEN cm.weeks_of_supply > 0 AND cm.weeks_of_supply <= 1 AND cm.recommended_replenishment_qty > 0 THEN '2. Urgent need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty > 0 THEN '3. Identified need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty = 0 THEN '4. No need'
        ELSE '6. Ageing stock'
    END AS stock_status
FROM (
    SELECT 
        wh.name AS warehouse_name,
        p.sku,
        p.name AS product_name,
        p.brand_name,
        p.is_expiry_date_tracking,
        p.shelf_life_days,
        p.is_batch_tracking,
        p.sales_price AS standard_selling_price,
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
        COALESCE(stk.total_current_stock, 0) AS total_stock,
        COALESCE(sls.avg_weekly_sales, 0) AS avg_weekly_sales,
        CASE 
            WHEN COALESCE(sls.avg_weekly_sales, 0) = 0 THEN 999.0 
            ELSE ROUND(COALESCE(stk.total_current_stock, 0) / sls.avg_weekly_sales, 2)
        END AS weeks_of_supply,
        GREATEST(0, ROUND((sls.avg_weekly_sales * 2) - COALESCE(stk.total_current_stock, 0), 0)) AS recommended_replenishment_qty,
        lp.last_purchased_batch,
        DATE(lp.last_purchase_date) AS last_purchase_date,
        lp.last_purchase_cost,
        CASE 
            WHEN lp.last_purchase_cost IS NULL THEN NULL 
            ELSE (p.sales_price - lp.last_purchase_cost) 
        END AS actual_margin_amount,
        CASE 
            WHEN p.sales_price IS NULL OR p.sales_price = 0 OR lp.last_purchase_cost IS NULL THEN NULL
            ELSE ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
        END AS actual_margin_percentage
    FROM products p
    CROSS JOIN warehouses wh
    LEFT JOIN (
        SELECT 
            posi.warehouse_id,
            posd.product_id,
            SUM(posd.detail_qty) / 4.0 AS avg_weekly_sales
        FROM pos_checkout_details posd
        JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
        WHERE posi.business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
          AND posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
          AND posi.current_status != 'Void'
        GROUP BY posi.warehouse_id, posd.product_id
    ) sls ON sls.product_id = p.id AND sls.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            warehouse_id,
            product_id,
            SUM(current_qty) AS total_current_stock
        FROM stock_summaries
        WHERE business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
        GROUP BY warehouse_id, product_id
    ) stk ON stk.product_id = p.id AND stk.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            bd.product_id,
            b.warehouse_id,
            bd.batch_number AS last_purchased_batch,
            bd.detail_unit_rate AS last_purchase_cost,
            b.bill_date AS last_purchase_date,
            ROW_NUMBER() OVER(PARTITION BY bd.product_id, b.warehouse_id ORDER BY b.bill_date DESC, b.id DESC) as rn
        FROM bill_details bd
        INNER JOIN bills b ON bd.bill_id = b.id
        WHERE b.business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
          AND b.current_status NOT IN ('Draft', 'Void')
    ) lp ON lp.product_id = p.id AND lp.warehouse_id = wh.id AND lp.rn = 1
    LEFT JOIN product_categories pc ON p.category_id = pc.id
    LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id
    LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id
    WHERE p.business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
      AND wh.business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
      AND (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
) cm
LEFT JOIN (
    SELECT 
        bd.product_id,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
    FROM bill_details AS bd
    INNER JOIN bills AS bill ON bd.bill_id = bill.id
    WHERE bd.expiry_date IS NOT NULL
      AND bill.business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
      AND bill.current_status != 'Void'
    GROUP BY bd.product_id
) AS exp ON exp.product_id IN (
    SELECT id FROM products WHERE sku = cm.sku AND business_id = '2d393763-d5c7-42be-b345-84b7be787f10'
)

UNION ALL

-- 2. ShweZay YGN
SELECT 
    'ShweZay YGN' AS store_name,
    'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08' AS business_id,
    cm.warehouse_name,
    cm.sku,
    cm.product_name,
    cm.brand_name,
    cm.is_expiry_date_tracking,
    cm.shelf_life_days,
    cm.is_batch_tracking,
    cm.standard_selling_price,
    cm.category_L1,
    cm.category_L2,
    cm.category_L3,
    cm.total_stock,
    cm.avg_weekly_sales,
    cm.weeks_of_supply,
    cm.recommended_replenishment_qty,
    cm.last_purchased_batch,
    cm.last_purchase_date,
    cm.last_purchase_cost,
    cm.actual_margin_amount,
    cm.actual_margin_percentage,
    ROUND(cm.avg_weekly_sales * cm.standard_selling_price, 2) AS weekly_revenue_loss,
    CASE 
        WHEN cm.actual_margin_amount IS NOT NULL THEN ROUND(cm.avg_weekly_sales * cm.actual_margin_amount, 2)
        ELSE 0 
    END AS weekly_margin_loss,
    CASE 
        WHEN cm.is_expiry_date_tracking = true AND (cm.shelf_life_days < 30 OR cm.shelf_life_days IS NULL) THEN 'Confirm shelf life'
        WHEN cm.brand_name IS NULL OR TRIM(cm.brand_name) = '' THEN 'Confirm brand name'
        WHEN cm.is_batch_tracking = false AND cm.category_L1 != 'Containers' THEN 'No batch tracking'
        WHEN cm.is_expiry_date_tracking = false AND cm.category_L3 = 'Perishable' THEN 'No expiry date tracking'
        WHEN COALESCE(exp.red_qty, 0) > 0 THEN 'Expired Stock (Red Alert)'
        WHEN COALESCE(exp.orange_qty, 0) > 0 THEN 'Near Expiry Stock (Orange Alert)'
        ELSE 'OK'
    END AS MasterdataAlert,
    CASE 
        WHEN cm.weeks_of_supply = 0 AND cm.recommended_replenishment_qty > 0 THEN '1. Shortage'
        WHEN cm.weeks_of_supply > 0 AND cm.weeks_of_supply <= 1 AND cm.recommended_replenishment_qty > 0 THEN '2. Urgent need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty > 0 THEN '3. Identified need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty = 0 THEN '4. No need'
        ELSE '6. Ageing stock'
    END AS stock_status
FROM (
    SELECT 
        wh.name AS warehouse_name,
        p.sku,
        p.name AS product_name,
        p.brand_name,
        p.is_expiry_date_tracking,
        p.shelf_life_days,
        p.is_batch_tracking,
        p.sales_price AS standard_selling_price,
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
        COALESCE(stk.total_current_stock, 0) AS total_stock,
        COALESCE(sls.avg_weekly_sales, 0) AS avg_weekly_sales,
        CASE 
            WHEN COALESCE(sls.avg_weekly_sales, 0) = 0 THEN 999.0 
            ELSE ROUND(COALESCE(stk.total_current_stock, 0) / sls.avg_weekly_sales, 2)
        END AS weeks_of_supply,
        GREATEST(0, ROUND((sls.avg_weekly_sales * 2) - COALESCE(stk.total_current_stock, 0), 0)) AS recommended_replenishment_qty,
        lp.last_purchased_batch,
        DATE(lp.last_purchase_date) AS last_purchase_date,
        lp.last_purchase_cost,
        CASE 
            WHEN lp.last_purchase_cost IS NULL THEN NULL 
            ELSE (p.sales_price - lp.last_purchase_cost) 
        END AS actual_margin_amount,
        CASE 
            WHEN p.sales_price IS NULL OR p.sales_price = 0 OR lp.last_purchase_cost IS NULL THEN NULL
            ELSE ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
        END AS actual_margin_percentage
    FROM products p
    CROSS JOIN warehouses wh
    LEFT JOIN (
        SELECT 
            posi.warehouse_id,
            posd.product_id,
            SUM(posd.detail_qty) / 4.0 AS avg_weekly_sales
        FROM pos_checkout_details posd
        JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
        WHERE posi.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
          AND posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
          AND posi.current_status != 'Void'
        GROUP BY posi.warehouse_id, posd.product_id
    ) sls ON sls.product_id = p.id AND sls.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            warehouse_id,
            product_id,
            SUM(current_qty) AS total_current_stock
        FROM stock_summaries
        WHERE business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
        GROUP BY warehouse_id, product_id
    ) stk ON stk.product_id = p.id AND stk.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            bd.product_id,
            b.warehouse_id,
            bd.batch_number AS last_purchased_batch,
            bd.detail_unit_rate AS last_purchase_cost,
            b.bill_date AS last_purchase_date,
            ROW_NUMBER() OVER(PARTITION BY bd.product_id, b.warehouse_id ORDER BY b.bill_date DESC, b.id DESC) as rn
        FROM bill_details bd
        INNER JOIN bills b ON bd.bill_id = b.id
        WHERE b.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
          AND b.current_status NOT IN ('Draft', 'Void')
    ) lp ON lp.product_id = p.id AND lp.warehouse_id = wh.id AND lp.rn = 1
    LEFT JOIN product_categories pc ON p.category_id = pc.id
    LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id
    LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id
    WHERE p.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
      AND wh.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
      AND (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
) cm
LEFT JOIN (
    SELECT 
        bd.product_id,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
    FROM bill_details AS bd
    INNER JOIN bills AS bill ON bd.bill_id = bill.id
    WHERE bd.expiry_date IS NOT NULL
      AND bill.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
      AND bill.current_status != 'Void'
    GROUP BY bd.product_id
) AS exp ON exp.product_id IN (
    SELECT id FROM products WHERE sku = cm.sku AND business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08'
)

UNION ALL

-- 3. ShweZay KPG
SELECT 
    'ShweZay KPG' AS store_name,
    '1eb52cc2-7a34-43d8-b646-67cc60402916' AS business_id,
    cm.warehouse_name,
    cm.sku,
    cm.product_name,
    cm.brand_name,
    cm.is_expiry_date_tracking,
    cm.shelf_life_days,
    cm.is_batch_tracking,
    cm.standard_selling_price,
    cm.category_L1,
    cm.category_L2,
    cm.category_L3,
    cm.total_stock,
    cm.avg_weekly_sales,
    cm.weeks_of_supply,
    cm.recommended_replenishment_qty,
    cm.last_purchased_batch,
    cm.last_purchase_date,
    cm.last_purchase_cost,
    cm.actual_margin_amount,
    cm.actual_margin_percentage,
    ROUND(cm.avg_weekly_sales * cm.standard_selling_price, 2) AS weekly_revenue_loss,
    CASE 
        WHEN cm.actual_margin_amount IS NOT NULL THEN ROUND(cm.avg_weekly_sales * cm.actual_margin_amount, 2)
        ELSE 0 
    END AS weekly_margin_loss,
    CASE 
        WHEN cm.is_expiry_date_tracking = true AND (cm.shelf_life_days < 30 OR cm.shelf_life_days IS NULL) THEN 'Confirm shelf life'
        WHEN cm.brand_name IS NULL OR TRIM(cm.brand_name) = '' THEN 'Confirm brand name'
        WHEN cm.is_batch_tracking = false AND cm.category_L1 != 'Containers' THEN 'No batch tracking'
        WHEN cm.is_expiry_date_tracking = false AND cm.category_L3 = 'Perishable' THEN 'No expiry date tracking'
        WHEN COALESCE(exp.red_qty, 0) > 0 THEN 'Expired Stock (Red Alert)'
        WHEN COALESCE(exp.orange_qty, 0) > 0 THEN 'Near Expiry Stock (Orange Alert)'
        ELSE 'OK'
    END AS MasterdataAlert,
    CASE 
        WHEN cm.weeks_of_supply = 0 AND cm.recommended_replenishment_qty > 0 THEN '1. Shortage'
        WHEN cm.weeks_of_supply > 0 AND cm.weeks_of_supply <= 1 AND cm.recommended_replenishment_qty > 0 THEN '2. Urgent need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty > 0 THEN '3. Identified need'
        WHEN cm.weeks_of_supply > 1 AND cm.recommended_replenishment_qty = 0 THEN '4. No need'
        ELSE '6. Ageing stock'
    END AS stock_status
FROM (
    SELECT 
        wh.name AS warehouse_name,
        p.sku,
        p.name AS product_name,
        p.brand_name,
        p.is_expiry_date_tracking,
        p.shelf_life_days,
        p.is_batch_tracking,
        p.sales_price AS standard_selling_price,
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
        COALESCE(stk.total_current_stock, 0) AS total_stock,
        COALESCE(sls.avg_weekly_sales, 0) AS avg_weekly_sales,
        CASE 
            WHEN COALESCE(sls.avg_weekly_sales, 0) = 0 THEN 999.0 
            ELSE ROUND(COALESCE(stk.total_current_stock, 0) / sls.avg_weekly_sales, 2)
        END AS weeks_of_supply,
        GREATEST(0, ROUND((sls.avg_weekly_sales * 2) - COALESCE(stk.total_current_stock, 0), 0)) AS recommended_replenishment_qty,
        lp.last_purchased_batch,
        DATE(lp.last_purchase_date) AS last_purchase_date,
        lp.last_purchase_cost,
        CASE 
            WHEN lp.last_purchase_cost IS NULL THEN NULL 
            ELSE (p.sales_price - lp.last_purchase_cost) 
        END AS actual_margin_amount,
        CASE 
            WHEN p.sales_price IS NULL OR p.sales_price = 0 OR lp.last_purchase_cost IS NULL THEN NULL
            ELSE ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
        END AS actual_margin_percentage
    FROM products p
    CROSS JOIN warehouses wh
    LEFT JOIN (
        SELECT 
            posi.warehouse_id,
            posd.product_id,
            SUM(posd.detail_qty) / 4.0 AS avg_weekly_sales
        FROM pos_checkout_details posd
        JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
        WHERE posi.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
          AND posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
          AND posi.current_status != 'Void'
        GROUP BY posi.warehouse_id, posd.product_id
    ) sls ON sls.product_id = p.id AND sls.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            warehouse_id,
            product_id,
            SUM(current_qty) AS total_current_stock
        FROM stock_summaries
        WHERE business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
        GROUP BY warehouse_id, product_id
    ) stk ON stk.product_id = p.id AND stk.warehouse_id = wh.id
    LEFT JOIN (
        SELECT 
            bd.product_id,
            b.warehouse_id,
            bd.batch_number AS last_purchased_batch,
            bd.detail_unit_rate AS last_purchase_cost,
            b.bill_date AS last_purchase_date,
            ROW_NUMBER() OVER(PARTITION BY bd.product_id, b.warehouse_id ORDER BY b.bill_date DESC, b.id DESC) as rn
        FROM bill_details bd
        INNER JOIN bills b ON bd.bill_id = b.id
        WHERE b.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
          AND b.current_status NOT IN ('Draft', 'Void')
    ) lp ON lp.product_id = p.id AND lp.warehouse_id = wh.id AND lp.rn = 1
    LEFT JOIN product_categories pc ON p.category_id = pc.id
    LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id
    LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id
    WHERE p.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
      AND wh.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
      AND (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
) cm
LEFT JOIN (
    SELECT 
        bd.product_id,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
    FROM bill_details AS bd
    INNER JOIN bills AS bill ON bd.bill_id = bill.id
    WHERE bd.expiry_date IS NOT NULL
      AND bill.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
      AND bill.current_status != 'Void'
    GROUP BY bd.product_id
) AS exp ON exp.product_id IN (
    SELECT id FROM products WHERE sku = cm.sku AND business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916'
);