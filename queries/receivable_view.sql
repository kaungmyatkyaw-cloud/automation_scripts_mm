CREATE OR REPLACE VIEW bi_database.vw_receivables_aging AS
SELECT
    inv.business_id,
    CASE 
        WHEN inv.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND inv.branch_id = 34 THEN 'M-Kitchen'
        WHEN (inv.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(inv.branch_id AS CHAR)) != '34' OR inv.branch_id IS NULL))
             OR inv.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642' THEN 'MTrading'
        ELSE 'Other'
    END AS business_unit,

    ANY_VALUE(so.order_number) AS order_number,
    ANY_VALUE(so.notes) AS notes,
    inv.invoice_number,
    inv.current_status,
    
    CASE 
        WHEN inv.invoice_payment_terms = 'DueOnReceipt' 
             AND MAX(CASE WHEN dm.name LIKE '%M-Express%' THEN 1 ELSE 0 END) = 1
             AND CURRENT_DATE() > inv.invoice_due_date 
             AND CURRENT_DATE() <= DATE_ADD(inv.invoice_due_date, INTERVAL 4 DAY)
             THEN 'DELAYED COD'
        WHEN CURRENT_DATE() > inv.invoice_due_date THEN 'LATE'
        WHEN inv.invoice_due_date BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY) 
            THEN 'TO BE PAID THIS WEEK'
        ELSE 'ON TIME'
    END AS payment_status,
    
    inv.invoice_payment_terms,
    GROUP_CONCAT(DISTINCT paym.name SEPARATOR ', ') AS PaymentMethods,
    ANY_VALUE(dm.name) AS delivery_method_name,
    
    CASE 
        WHEN inv.invoice_payment_terms = 'DueOnReceipt' 
             AND MAX(CASE WHEN dm.name LIKE '%M-Express%' THEN 1 ELSE 0 END) = 1
        THEN 'TRUE' 
        ELSE 'FALSE' 
    END AS MarathonCOD,
    
    GROUP_CONCAT(DISTINCT pay.payment_number ORDER BY pay.payment_date ASC SEPARATOR '; ') AS Payments,
    ROUND(DATEDIFF(inv.invoice_due_date, CURRENT_DATE()), 0) AS days_remaining,
    inv.invoice_date,
    DATE_FORMAT(inv.invoice_date, '%M') AS InvoiceMonth,
    
    ANY_VALUE(CASE 
        WHEN g3.name IS NOT NULL THEN g3.name 
        WHEN g2.name IS NOT NULL THEN g2.name 
        ELSE g1.name 
    END) AS sales_channel,
    ANY_VALUE(CASE 
        WHEN g3.name IS NOT NULL THEN g2.name 
        ELSE g1.name 
    END) AS group_l1,
    ANY_VALUE(g1.name) AS group_l2,

    ANY_VALUE(branch.name) AS branch,
    inv.invoice_due_date,
    inv.invoice_total_amount,
    inv.invoice_total_paid_amount,
    inv.remaining_balance,
    ANY_VALUE(salesp.name) AS salesp_name,
    ANY_VALUE(cust.name) AS cust_name,
    
    inv.invoice_number AS copy_invoice_number,
    inv.invoice_date AS copy_invoice_date,
    inv.remaining_balance AS copy_remaining_balance,
    ANY_VALUE(cust.name) AS copy_cust_name
    
FROM sales_invoices AS inv
LEFT JOIN customers AS cust ON inv.customer_id = cust.id
LEFT JOIN customer_groups AS g1 ON cust.group_id = g1.id
LEFT JOIN customer_groups AS g2 ON g1.parent_group_id = g2.id
LEFT JOIN customer_groups AS g3 ON g2.parent_group_id = g3.id
LEFT JOIN sales_people AS salesp ON inv.sales_person_id = salesp.id
LEFT JOIN branches AS branch ON inv.branch_id = branch.id
LEFT JOIN sales_orders AS so ON inv.sales_order_id = so.id
LEFT JOIN paid_invoices AS pi ON inv.id = pi.invoice_id
LEFT JOIN customer_payments AS pay ON pi.customer_payment_id = pay.id
LEFT JOIN payment_methods AS paym ON so.payment_method_id = paym.id 
LEFT JOIN delivery_methods AS dm ON so.delivery_method_id = dm.id

WHERE (
        (inv.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND inv.branch_id = 34)
        OR 
        ((inv.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(inv.branch_id AS CHAR)) != '34' OR inv.branch_id IS NULL))
         OR inv.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
      )
  AND inv.current_status NOT IN ('Paid', 'Void')
  AND inv.invoice_number != 'Customer Opening Balance'
  AND inv.invoice_due_date BETWEEN
      DATE_SUB(CURRENT_DATE(), INTERVAL WEEKDAY(CURRENT_DATE()) DAY)
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)

GROUP BY inv.id
ORDER BY inv.remaining_balance DESC;