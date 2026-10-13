-- CityMall product categorization migration
-- Target: MySQL 8.0 or later; the temporary-table update also works on MySQL 5.7.
-- Run each numbered section in order.

/* -------------------------------------------------------------------------
   0. Select the application database
   ------------------------------------------------------------------------- */
-- USE your_database_name;

/* -------------------------------------------------------------------------
   1. Create a backup before changing the table
   ------------------------------------------------------------------------- */
CREATE TABLE citymall_products_backup LIKE citymall_products;
INSERT INTO citymall_products_backup
SELECT * FROM citymall_products;

/* -------------------------------------------------------------------------
   2. Add category columns

   category_l1: broad department, such as Foods
   category_l2: product family, such as Noodles & Pasta
   category_l3: specific type, such as Instant Noodles
   category_path: convenient display and filtering value
   category_rule: the keyword that caused the match
   categorized_at: timestamp for the categorization operation
   ------------------------------------------------------------------------- */
ALTER TABLE citymall_products
    ADD COLUMN category_l1 VARCHAR(100) NULL AFTER product_url,
    ADD COLUMN category_l2 VARCHAR(100) NULL AFTER category_l1,
    ADD COLUMN category_l3 VARCHAR(100) NULL AFTER category_l2,
    ADD COLUMN category_path VARCHAR(320) NULL AFTER category_l3,
    ADD COLUMN category_rule VARCHAR(100) NULL AFTER category_path,
    ADD COLUMN categorized_at TIMESTAMP NULL AFTER category_rule;

ALTER TABLE citymall_products
    ADD INDEX idx_citymall_category_l1 (category_l1),
    ADD INDEX idx_citymall_category_l2 (category_l2),
    ADD INDEX idx_citymall_category_l3 (category_l3),
    ADD INDEX idx_citymall_category_path (category_path);

/* -------------------------------------------------------------------------
   3. Recommended timestamp correction

   Your current scraped_at definition has ON UPDATE CURRENT_TIMESTAMP.
   Therefore, updating category columns also changes scraped_at. If scraped_at
   is intended to mean the actual scrape time, remove the ON UPDATE behavior.
   Skip this statement if you intentionally want scraped_at to change whenever
   any column changes.
   ------------------------------------------------------------------------- */
ALTER TABLE citymall_products
    MODIFY COLUMN scraped_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

/* -------------------------------------------------------------------------
   4. Create a maintainable keyword rule table

   Lower priority numbers win. If multiple keywords match one product, the
   lowest priority is selected. For equal priority, the longer keyword wins.
   This means "instant noodle" wins before the generic "noodle" rule.
   ------------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS citymall_category_rules (
    rule_id INT AUTO_INCREMENT PRIMARY KEY,
    priority INT NOT NULL,
    keyword VARCHAR(100) NOT NULL,
    category_l1 VARCHAR(100) NOT NULL,
    category_l2 VARCHAR(100) NOT NULL,
    category_l3 VARCHAR(100) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_citymall_category_keyword (keyword),
    KEY idx_citymall_category_rule_priority (priority, active),
    CONSTRAINT chk_citymall_category_rule_active CHECK (active IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/* -------------------------------------------------------------------------
   5. Load the starter taxonomy rules

   The rules are intentionally plain English keywords. Add new keywords with
   a smaller priority number when they must override a generic rule.
   ------------------------------------------------------------------------- */
INSERT INTO citymall_category_rules
    (priority, keyword, category_l1, category_l2, category_l3)
VALUES
    (10, 'instant noodle', 'Foods', 'Noodles & Pasta', 'Instant Noodles'),
    (10, 'instant ramen', 'Foods', 'Noodles & Pasta', 'Instant Noodles'),
    (10, 'cup noodle', 'Foods', 'Noodles & Pasta', 'Instant Noodles'),
    (10, 'noodle soup', 'Foods', 'Noodles & Pasta', 'Instant Noodles'),
    (15, 'rice noodle', 'Foods', 'Noodles & Pasta', 'Rice Noodles'),
    (15, 'shan noodle', 'Foods', 'Noodles & Pasta', 'Shan Noodles'),
    (20, 'vermicelli', 'Foods', 'Noodles & Pasta', 'Vermicelli'),
    (30, 'noodle', 'Foods', 'Noodles & Pasta', 'Other Noodles'),
    (30, 'pasta', 'Foods', 'Noodles & Pasta', 'Pasta'),
    (30, 'spaghetti', 'Foods', 'Noodles & Pasta', 'Pasta'),
    (30, 'macaroni', 'Foods', 'Noodles & Pasta', 'Pasta'),

    (40, 'paw san rice', 'Foods', 'Rice & Grains', 'Rice'),
    (40, 'pawsan rice', 'Foods', 'Rice & Grains', 'Rice'),
    (40, 'brown rice', 'Foods', 'Rice & Grains', 'Rice'),
    (40, 'sticky rice', 'Foods', 'Rice & Grains', 'Rice'),
    (50, 'rice', 'Foods', 'Rice & Grains', 'Rice'),
    (50, 'bean', 'Foods', 'Rice & Grains', 'Beans & Pulses'),
    (50, 'chickpea', 'Foods', 'Rice & Grains', 'Beans & Pulses'),
    (50, 'lentil', 'Foods', 'Rice & Grains', 'Beans & Pulses'),
    (60, 'flour', 'Foods', 'Rice & Grains', 'Other Grains'),
    (60, 'wheat', 'Foods', 'Rice & Grains', 'Other Grains'),
    (60, 'oat', 'Foods', 'Rice & Grains', 'Other Grains'),

    (70, 'dried prawn', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (70, 'dried fish', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (70, 'seafood', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (70, 'prawn', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (70, 'shrimp', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (70, 'fish', 'Foods', 'Meat & Seafood', 'Fish & Seafood'),
    (75, 'chicken', 'Foods', 'Meat & Seafood', 'Poultry'),
    (75, 'duck', 'Foods', 'Meat & Seafood', 'Poultry'),
    (80, 'sausage', 'Foods', 'Meat & Seafood', 'Meat & Sausages'),
    (80, 'pork', 'Foods', 'Meat & Seafood', 'Meat & Sausages'),
    (80, 'beef', 'Foods', 'Meat & Seafood', 'Meat & Sausages'),
    (80, 'mutton', 'Foods', 'Meat & Seafood', 'Meat & Sausages'),

    (90, 'peanut oil', 'Foods', 'Cooking Oils', 'Edible Oils'),
    (90, 'olive oil', 'Foods', 'Cooking Oils', 'Edible Oils'),
    (90, 'sesame oil', 'Foods', 'Cooking Oils', 'Edible Oils'),
    (90, 'coconut oil', 'Foods', 'Cooking Oils', 'Edible Oils'),
    (100, 'oil', 'Foods', 'Cooking Oils', 'Edible Oils'),

    (110, 'soy sauce', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (110, 'fish sauce', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (110, 'oyster sauce', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (110, 'chilli paste', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (110, 'chili paste', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (110, 'gochujang', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (120, 'sauce', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (120, 'ketchup', 'Foods', 'Sauces & Condiments', 'Sauces & Dressings'),
    (125, 'pickled', 'Foods', 'Sauces & Condiments', 'Pickles & Preserves'),
    (125, 'pickle', 'Foods', 'Sauces & Condiments', 'Pickles & Preserves'),
    (125, 'jam', 'Foods', 'Sauces & Condiments', 'Pickles & Preserves'),

    (130, 'seasoning', 'Foods', 'Spices & Seasonings', 'Seasoning & Stock'),
    (130, 'stock', 'Foods', 'Spices & Seasonings', 'Seasoning & Stock'),
    (140, 'chilli', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (140, 'chili', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (140, 'pepper', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (140, 'turmeric', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (140, 'ginger', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (140, 'garlic', 'Foods', 'Spices & Seasonings', 'Spices & Herbs'),
    (150, 'sugar', 'Foods', 'Baking & Pantry', 'Sugar & Salt'),
    (150, 'salt', 'Foods', 'Baking & Pantry', 'Sugar & Salt'),
    (155, 'vinegar', 'Foods', 'Baking & Pantry', 'Vinegar & Pantry Basics'),
    (155, 'tamarind', 'Foods', 'Baking & Pantry', 'Vinegar & Pantry Basics'),

    (160, 'tofu', 'Foods', 'Tofu & Soy Products', 'Tofu'),
    (170, 'vegetable', 'Foods', 'Fruits & Vegetables', 'Fresh & Frozen Produce'),
    (170, 'mushroom', 'Foods', 'Fruits & Vegetables', 'Fresh & Frozen Produce'),
    (170, 'tomato', 'Foods', 'Fruits & Vegetables', 'Fresh & Frozen Produce'),
    (170, 'potato', 'Foods', 'Fruits & Vegetables', 'Fresh & Frozen Produce'),
    (170, 'mango', 'Foods', 'Fruits & Vegetables', 'Fresh & Frozen Produce'),
    (180, 'ready', 'Foods', 'Prepared & Ready-to-Eat', 'Ready Meals'),
    (180, 'salad', 'Foods', 'Prepared & Ready-to-Eat', 'Ready Meals'),
    (180, 'soup', 'Foods', 'Prepared & Ready-to-Eat', 'Ready Meals'),
    (180, 'curry', 'Foods', 'Prepared & Ready-to-Eat', 'Ready Meals'),
    (180, 'fried', 'Foods', 'Prepared & Ready-to-Eat', 'Ready Meals'),

    (190, 'peanut', 'Foods', 'Snacks & Nuts', 'Nuts & Seeds'),
    (190, 'almond', 'Foods', 'Snacks & Nuts', 'Nuts & Seeds'),
    (190, 'cashew', 'Foods', 'Snacks & Nuts', 'Nuts & Seeds'),
    (200, 'biscuit', 'Foods', 'Snacks & Nuts', 'Biscuits & Crackers'),
    (200, 'cracker', 'Foods', 'Snacks & Nuts', 'Biscuits & Crackers'),
    (210, 'chip', 'Foods', 'Snacks & Nuts', 'Chips & Savoury Snacks'),
    (220, 'chocolate', 'Foods', 'Desserts & Sweets', 'Candy & Chocolate'),
    (220, 'candy', 'Foods', 'Desserts & Sweets', 'Candy & Chocolate'),
    (220, 'mochi', 'Foods', 'Desserts & Sweets', 'Candy & Chocolate'),

    (230, 'milk tea', 'Beverages', 'Tea & Coffee', 'Tea'),
    (230, 'green tea', 'Beverages', 'Tea & Coffee', 'Tea'),
    (230, 'tea', 'Beverages', 'Tea & Coffee', 'Tea'),
    (240, 'coffee', 'Beverages', 'Tea & Coffee', 'Coffee'),
    (250, 'juice', 'Beverages', 'Soft Drinks & Juices', 'Juices & Drinks'),
    (250, 'cola', 'Beverages', 'Soft Drinks & Juices', 'Juices & Drinks'),
    (250, 'soda', 'Beverages', 'Soft Drinks & Juices', 'Juices & Drinks'),

    (260, 'detergent', 'Household', 'Cleaning', 'Household Cleaning'),
    (260, 'dishwash', 'Household', 'Cleaning', 'Household Cleaning'),
    (270, 'shampoo', 'Personal Care', 'Body Care', 'Personal Care'),
    (270, 'toothpaste', 'Personal Care', 'Body Care', 'Personal Care'),
    (270, 'soap', 'Personal Care', 'Body Care', 'Personal Care')
ON DUPLICATE KEY UPDATE
    priority = VALUES(priority),
    category_l1 = VALUES(category_l1),
    category_l2 = VALUES(category_l2),
    category_l3 = VALUES(category_l3),
    active = 1;

/* -------------------------------------------------------------------------
   6. Preview the classification before updating products

   This query demonstrates the requested example:
   product_name containing "instant noodle"
   -> Foods / Noodles & Pasta / Instant Noodles
   ------------------------------------------------------------------------- */
SELECT
    p.id,
    p.product_name,
    COALESCE(m.category_l1, 'Foods') AS proposed_category_l1,
    COALESCE(m.category_l2, 'Other Grocery') AS proposed_category_l2,
    COALESCE(m.category_l3, 'Unclassified') AS proposed_category_l3,
    COALESCE(m.keyword, 'fallback') AS proposed_category_rule
FROM citymall_products AS p
LEFT JOIN (
    SELECT p1.id, r1.keyword, r1.category_l1, r1.category_l2, r1.category_l3
    FROM citymall_products AS p1
    INNER JOIN citymall_category_rules AS r1
        ON r1.active = 1
       AND LOWER(p1.product_name) LIKE CONCAT('%', LOWER(r1.keyword), '%')
    WHERE NOT EXISTS (
        SELECT 1
        FROM citymall_category_rules AS r2
        WHERE r2.active = 1
          AND LOWER(p1.product_name) LIKE CONCAT('%', LOWER(r2.keyword), '%')
          AND (
                r2.priority < r1.priority
                OR (
                    r2.priority = r1.priority
                    AND CHAR_LENGTH(r2.keyword) > CHAR_LENGTH(r1.keyword)
                )
                OR (
                    r2.priority = r1.priority
                    AND CHAR_LENGTH(r2.keyword) = CHAR_LENGTH(r1.keyword)
                    AND r2.rule_id < r1.rule_id
                )
          )
    )
) AS m ON m.id = p.id
ORDER BY p.id;

/* -------------------------------------------------------------------------
   7. Update the category columns

   The temporary table contains at most one winning rule per product.
   Products with no keyword match receive a deliberate review queue value.
   ------------------------------------------------------------------------- */
DROP TEMPORARY TABLE IF EXISTS tmp_citymall_product_categories;

CREATE TEMPORARY TABLE tmp_citymall_product_categories (
    id INT PRIMARY KEY,
    category_l1 VARCHAR(100) NOT NULL,
    category_l2 VARCHAR(100) NOT NULL,
    category_l3 VARCHAR(100) NOT NULL,
    category_rule VARCHAR(100) NOT NULL
) ENGINE=InnoDB;

INSERT INTO tmp_citymall_product_categories
    (id, category_l1, category_l2, category_l3, category_rule)
SELECT
    p.id,
    COALESCE(m.category_l1, 'Foods'),
    COALESCE(m.category_l2, 'Other Grocery'),
    COALESCE(m.category_l3, 'Unclassified'),
    COALESCE(m.keyword, 'fallback')
FROM citymall_products AS p
LEFT JOIN (
    SELECT p1.id, r1.keyword, r1.category_l1, r1.category_l2, r1.category_l3
    FROM citymall_products AS p1
    INNER JOIN citymall_category_rules AS r1
        ON r1.active = 1
       AND LOWER(p1.product_name) LIKE CONCAT('%', LOWER(r1.keyword), '%')
    WHERE NOT EXISTS (
        SELECT 1
        FROM citymall_category_rules AS r2
        WHERE r2.active = 1
          AND LOWER(p1.product_name) LIKE CONCAT('%', LOWER(r2.keyword), '%')
          AND (
                r2.priority < r1.priority
                OR (
                    r2.priority = r1.priority
                    AND CHAR_LENGTH(r2.keyword) > CHAR_LENGTH(r1.keyword)
                )
                OR (
                    r2.priority = r1.priority
                    AND CHAR_LENGTH(r2.keyword) = CHAR_LENGTH(r1.keyword)
                    AND r2.rule_id < r1.rule_id
                )
          )
    )
) AS m ON m.id = p.id;

SET SQL_SAFE_UPDATES=0;

UPDATE citymall_products AS p
INNER JOIN tmp_citymall_product_categories AS c ON c.id = p.id
SET
    p.category_l1 = c.category_l1,
    p.category_l2 = c.category_l2,
    p.category_l3 = c.category_l3,
    p.category_path = CONCAT_WS(' > ', c.category_l1, c.category_l2, c.category_l3),
    p.category_rule = c.category_rule,
    p.categorized_at = CURRENT_TIMESTAMP;

DROP TEMPORARY TABLE tmp_citymall_product_categories;

/* -------------------------------------------------------------------------
   8. Validate the update
   ------------------------------------------------------------------------- */
SELECT
    COUNT(*) AS total_products,
    SUM(category_l1 IS NOT NULL AND category_l2 IS NOT NULL AND category_l3 IS NOT NULL) AS categorized_products,
    SUM(category_l3 = 'Unclassified') AS unclassified_products,
    SUM(category_path IS NULL OR category_path = '') AS blank_category_paths
FROM citymall_products;

SELECT
    category_l1,
    category_l2,
    category_l3,
    COUNT(*) AS product_count,
    ROUND(AVG(price_numeric), 2) AS average_price
FROM citymall_products
GROUP BY category_l1, category_l2, category_l3
ORDER BY category_l1, category_l2, category_l3;

/* Verify the example rule specifically. */
SELECT
    id,
    product_name,
    category_l1,
    category_l2,
    category_l3,
    category_path,
    category_rule
FROM citymall_products
WHERE LOWER(product_name) LIKE '%instant noodle%'
ORDER BY id;

/* Find products needing manual review. */
SELECT id, product_name, price_numeric, product_url
FROM citymall_products
WHERE category_l3 = 'Unclassified'
ORDER BY product_name;

/* -------------------------------------------------------------------------
   9. Future maintenance examples
   ------------------------------------------------------------------------- */

-- Add a more specific rule. Smaller priority wins.
-- INSERT INTO citymall_category_rules
--     (priority, keyword, category_l1, category_l2, category_l3)
-- VALUES
--     (5, 'hot chicken instant noodle', 'Foods', 'Noodles & Pasta', 'Instant Noodles');

-- Disable a rule without deleting its history.
-- UPDATE citymall_category_rules
-- SET active = 0
-- WHERE keyword = 'some keyword';

-- After changing rules, rerun Sections 6 and 7 to reclassify all products.

-- To restore the original table from the backup, use this only if necessary:
-- TRUNCATE TABLE citymall_products;
-- INSERT INTO citymall_products
-- SELECT * FROM citymall_products_backup_20260924;
