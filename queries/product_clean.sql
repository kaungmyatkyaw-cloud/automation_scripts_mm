show databases;

SELECT * FROM bi_marathon.products;

describe products;
select * from products;

-- Barcode တူပြီး Product အချက်အလက် ကွဲပြားနေမှုများကို စစ်ဆေးခြင်း
SELECT 
    barcode,
    COUNT(DISTINCT business_id) AS total_business_units,
    COUNT(DISTINCT sku) AS total_unique_skus,
    COUNT(DISTINCT name) AS total_unique_names,
    GROUP_CONCAT(DISTINCT business_id SEPARATOR ' | ') AS affected_businesses,
    GROUP_CONCAT(DISTINCT name SEPARATOR ' | ') AS product_names
FROM bi_marathon.products
WHERE barcode IS NOT NULL AND barcode != ''
GROUP BY barcode
HAVING COUNT(DISTINCT sku) > 1 OR COUNT(DISTINCT name) > 1;

-- SKU တူပြီး Name နှင့် Description ကွဲလွဲနေမှုများကို စစ်ဆေးခြင်း
SELECT 
    sku,
    COUNT(DISTINCT name) AS total_unique_names,
    COUNT(DISTINCT description) AS total_unique_descriptions,
    GROUP_CONCAT(DISTINCT name SEPARATOR ' | ') AS mismatched_names
FROM bi_marathon.products
WHERE sku IS NOT NULL AND sku != ''
GROUP BY sku
HAVING COUNT(DISTINCT name) > 1;

-- Barcode ကော SKU ပါ Blank/Null ဖြစ်နေပြီး အမှိုက်ဖြစ်နိုင်ခြေရှိသော Data များ ရှာဖွေခြင်း
SELECT 
    business_id, 
    COUNT(*) AS incomplete_products_count 
FROM bi_marathon.products 
WHERE (barcode IS NULL OR barcode = '') AND (sku IS NULL OR sku = '')
GROUP BY business_id;

/* Product Master Definition & Staging Table Strategy
Data တိုက်ရိုက် မပျက်စီးစေဖို့အတွက် Raw Data တွေကို တိုက်ရိုက် မဖျက်ဘဲ bi_marathon ထဲမှာ Staging/Master Mapping Table တစ်ခု ဆောက်ပြီး Master Product တွေကို ID သစ် (သို့) Golden Record တစ်ခုအနေနဲ့ သတ်မှတ်မှာဖြစ်ပါတယ်
Dynamic Master Matching Priority Rules
> 	နမူနာအားဖြင့် ဒေတာ clean တဲ့အခါ အောက်ပါ Priority အတိုင်း 'Master Record' ကို ရွေးချယ်ပါမယ်-
> 	Priority 1 (Primary Key): barcode ရှိရင် barcode ကို အဓိက Identifier အဖြစ် ယူမည်။
> 	Priority 2 (Secondary Key): barcode မရှိဘဲ sku ပဲရှိရင် sku ကို ယူမည်။
> 	Golden Record Rules (ဘယ် Record ကို အမှန်ယူမလဲ):
> 	Record Multiple ဖြစ်နေရင် updated_at (သို့) created_at နောက်ဆုံးဖြစ်တဲ့ Record ကို နာမည်/ဈေးနှုန်းအတွက် Master Standard အဖြစ် ယူမည်။
	သို့မဟုတ် sales_price > 0 ဖြစ်ပြီး is_sellable = 1 ဖြစ်သော Active Data ကို ဦးစားပေးမည်။
*/

-- Create a Unified Master Products Staging Table
CREATE TABLE IF NOT EXISTS bi_marathon.dim_master_products (
    master_product_id BIGINT NOT NULL,
    primary_source_id BIGINT NOT NULL,
    primary_business_id VARCHAR(191),
    master_match_key VARCHAR(255),
    master_barcode VARCHAR(100),
    master_sku VARCHAR(100),
    master_product_name VARCHAR(255),
    master_description TEXT,
    brand_name VARCHAR(100),
    category_id BIGINT,
    unit_id BIGINT,
    sales_price DECIMAL(20,4),
    purchase_price DECIMAL(20,4),
    last_updated_at DATETIME(3),
    PRIMARY KEY (master_product_id),
    INDEX idx_master_match_key (master_match_key),
    INDEX idx_master_barcode (master_barcode),
    INDEX idx_master_sku (master_sku)
);

INSERT INTO bi_marathon.dim_master_products
WITH RankedProducts AS (
    SELECT 
        id AS original_product_id,
        business_id,
        name,
        description,
        brand_name,
        category_id,
        unit_id,
        NULLIF(TRIM(barcode), '') AS clean_barcode,
        NULLIF(TRIM(sku), '') AS clean_sku,
        sales_price,
        purchase_price,
        is_active,
        created_at,
        updated_at,
        COALESCE(NULLIF(TRIM(barcode), ''), NULLIF(TRIM(sku), '')) AS master_match_key,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(NULLIF(TRIM(barcode), ''), NULLIF(TRIM(sku), ''))
            ORDER BY 
                is_active DESC,
                updated_at DESC, 
                created_at DESC,
                id DESC
        ) AS rank_order
    FROM bi_marathon.products
    WHERE (barcode IS NOT NULL AND TRIM(barcode) != '') 
       OR (sku IS NOT NULL AND TRIM(sku) != '')
)
SELECT 
    DENSE_RANK() OVER (ORDER BY master_match_key) AS master_product_id,
    original_product_id AS primary_source_id,
    business_id AS primary_business_id,
    master_match_key,
    clean_barcode AS master_barcode,
    clean_sku AS master_sku,
    name AS master_product_name,
    description AS master_description,
    brand_name,
    category_id,
    unit_id,
    sales_price,
    purchase_price,
    updated_at AS last_updated_at
FROM RankedProducts
WHERE rank_order = 1;

/* Cross-Reference Mapping Bridge Table ဆောက်ခြင်း
ဒီ Table က das-db.products ထဲမှာ ရှိသမျှ Product Record တိုင်း (Business Unit အသီးသီးက ID အဟောင်းများ) ကို Master Table က master_product_id နဲ့ ပြန်လည် ချိတ်ဆက်ပေးမှာ ဖြစ်ပါတယ်
*/

-- Bridge Table (Primary Key နှင့် Index ပါဝင်)
CREATE TABLE IF NOT EXISTS bi_marathon.bridge_product_mapping (
    original_product_id BIGINT NOT NULL,
    business_id VARCHAR(191) NOT NULL,
    master_product_id BIGINT NOT NULL,
    mapped_by_strategy VARCHAR(50),
    mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (original_product_id, business_id),
    INDEX idx_bridge_master_id (master_product_id)
);

-- Source Data များကို Clean Master Product ID များဖြင့် Mapping လုပ်ပြီး Data insert
INSERT INTO bi_marathon.bridge_product_mapping (
    original_product_id, 
    business_id, 
    master_product_id, 
    mapped_by_strategy
)
SELECT 
    p.id AS original_product_id,
    p.business_id,
    m.master_product_id,
    CASE 
        WHEN NULLIF(TRIM(p.barcode), '') = m.master_barcode THEN 'BARCODE_MATCH'
        WHEN NULLIF(TRIM(p.sku), '') = m.master_sku THEN 'SKU_MATCH'
        ELSE 'FALLBACK_MATCH'
    END AS mapped_by_strategy
FROM bi_marathon.products p
INNER JOIN bi_marathon.dim_master_products m 
    ON COALESCE(NULLIF(TRIM(p.barcode), ''), NULLIF(TRIM(p.sku), '')) = m.master_match_key;

/* bi_marathon.products Table ကို Master ID ဖြင့် ချိတ်ဆက်၍ တည်ဆောက်ခြင်း
ဒီအဆင့်မှာတော့ မူရင်း Table ရဲ့ Schema ဖွဲ့စည်းပုံအတိုင်း bi_marathon ထဲမှာ products table ကို ဆောက်မှာ ဖြစ်ပေမယ့်၊ 
ွဲပြားခြားနားသွားတာကတော့ ဒေတာတွေကို Unify လုပ်ပေးထားတဲ့ master_product_id (Foreign Key) ကိုပါ တစ်ခါတည်း ထည့်သွင်း တည်ဆောက်သွားမှာ ဖြစ်ပါတယ်။ 
နောက်ပိုင်း Reporting ဆွဲရင် Master Identity အတိုင်း Group လုပ်ရတာ လွယ်ကူအောင်ဖြစ်ပါတယ်
*/

DROP TABLE IF EXISTS bi_marathon.products;

-- Target Table Dynamic DDL Structure ဆောက်ခြင်း
CREATE TABLE bi_marathon.products (
    id BIGINT NOT NULL,
    master_product_id BIGINT NOT NULL,
    business_id VARCHAR(191) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category_id BIGINT NOT NULL DEFAULT 0,
    unit_id BIGINT,
    supplier_id BIGINT,
    sku VARCHAR(100) NOT NULL,
    barcode VARCHAR(100),
    sales_price DECIMAL(20,4) DEFAULT 0.0000,
    sales_account_id BIGINT,
    sales_tax_id BIGINT,
    sales_tax_type ENUM('I','G'),
    is_sales_tax_inclusive TINYINT(1) NOT NULL DEFAULT 1,
    purchase_price DECIMAL(20,4) DEFAULT 0.0000,
    purchase_account_id BIGINT,
    purchase_tax_id BIGINT,
    purchase_tax_type ENUM('I','G'),
    inventory_account_id BIGINT,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    is_batch_tracking TINYINT(1) NOT NULL DEFAULT 0,
    is_expiry_date_tracking TINYINT(1) NOT NULL DEFAULT 0,
    external_system_id VARCHAR(191),
    created_at DATETIME(3),
    updated_at DATETIME(3),
    nature VARCHAR(191) DEFAULT 'G',
    sequence_no DECIMAL(15,0),
    is_sellable TINYINT(1) NOT NULL DEFAULT 1,
    is_purchasable TINYINT(1) NOT NULL DEFAULT 1,
    reorder_point DECIMAL(20,4) DEFAULT 0.0000,
    cache_invalidated_at DATETIME(3),
    brand_name VARCHAR(100),
    length DECIMAL(20,4) DEFAULT 0.0000,
    width DECIMAL(20,4) DEFAULT 0.0000,
    height DECIMAL(20,4) DEFAULT 0.0000,
    weight DECIMAL(20,4) DEFAULT 0.0000,
    master_id BIGINT,
    shelf_life_days BIGINT NOT NULL DEFAULT 0,
    purchased_sku VARCHAR(100),
    PRIMARY KEY (id, business_id),
    INDEX idx_products_master_id (master_product_id),
    INDEX idx_products_barcode (barcode),
    INDEX idx_products_sku (sku)
);

INSERT INTO bi_marathon.products (
    id,
    master_product_id,
    business_id,
    name,
    description,
    category_id,
    unit_id,
    supplier_id,
    sku,
    barcode,
    sales_price,
    sales_account_id,
    sales_tax_id,
    sales_tax_type,
    is_sales_tax_inclusive,
    purchase_price,
    purchase_account_id,
    purchase_tax_id,
    purchase_tax_type,
    inventory_account_id,
    is_active,
    is_batch_tracking,
    is_expiry_date_tracking,
    external_system_id,
    created_at,
    updated_at,
    nature,
    sequence_no,
    is_sellable,
    is_purchasable,
    reorder_point,
    cache_invalidated_at,
    brand_name,
    length,
    width,
    height,
    weight,
    master_id,
    shelf_life_days,
    purchased_sku
)
SELECT 
    p.id,
    b.master_product_id,
    p.business_id,
    p.name,
    p.description,
    p.category_id,
    p.unit_id,
    p.supplier_id,
    p.sku,
    p.barcode,
    p.sales_price,
    p.sales_account_id,
    p.sales_tax_id,
    p.sales_tax_type,
    p.is_sales_tax_inclusive,
    p.purchase_price,
    p.purchase_account_id,
    p.purchase_tax_id,
    p.purchase_tax_type,
    p.inventory_account_id,
    p.is_active,
    p.is_batch_tracking,
    p.is_expiry_date_tracking,
    p.external_system_id,
    p.created_at,
    p.updated_at,
    p.nature,
    p.sequence_no,
    p.is_sellable,
    p.is_purchasable,
    p.reorder_point,
    p.cache_invalidated_at,
    p.brand_name,
    p.length,
    p.width,
    p.height,
    p.weight,
    p.master_id,
    p.shelf_life_days,
    p.purchased_sku
FROM bi_marathon.products p
INNER JOIN bi_marathon.bridge_product_mapping b 
    ON p.id = b.original_product_id AND p.business_id = b.business_id;
    
SELECT 
    m.master_product_id,
    m.master_barcode,
    m.master_product_name, -- အမှန်ဆုံး Golden Name ကို ယူသုံးမည်
    COUNT(DISTINCT p.business_id) AS total_selling_business_units,
    SUM(p.sales_price) AS aggregate_sales_value -- ဥပမာ Transaction နှင့် Join လျှင် ပိုတိကျမည်
FROM bi_marathon.dim_master_products m
INNER JOIN bi_marathon.products p ON m.master_product_id = p.master_product_id
GROUP BY m.master_product_id, m.master_barcode, m.master_product_name;

SELECT 
    p.business_id,
    p.id AS original_id,
    p.name AS source_name,
    COALESCE(m.master_product_name, '⚠️ UNMAPPED_PRODUCT') AS unified_product_name
FROM bi_marathon.products p
LEFT JOIN bi_marathon.bridge_product_mapping b ON p.id = b.original_product_id AND p.business_id = b.business_id
LEFT JOIN bi_marathon.dim_master_products m ON b.master_product_id = m.master_product_id;

/* Text Normalization Logic ကို dim_master_products တွင် ပြန်လည်ပြင်ဆင်ခြင်း
လက်ရှိ Master Table ထဲမှာ Name တွေ မတူရခြင်းရဲ့ အဓိကအကြောင်းအရင်းက master_match_key တည်ဆောက်ခဲ့စဉ်က Barcode သီးသန့်ကိုပဲ ကြည့်ခဲ့ပြီး Barcode မတူတာ 
(သို့မဟုတ်) Barcode မပါလို့ Name အပေါ် မူတည်သွားတဲ့အချိန်မှာ ကွဲလွဲကုန်တာ ဖြစ်နိုင်ပါတယ်။ 
တကယ်လို့ Barcode တူရဲ့သားနဲ့ Name ကြောင့် Master ID ခွဲထွက်သွားတာဆိုရင် PARTITION BY ထဲက Key ကို ပိုပြီး ကျစ်လျစ်အောင် လုပ်ရပါမယ်။
ဒီ Text Inflation ကို ရှင်းဖို့အတွက် MySQL ရဲ့ REPLACE() Function ကို သုံးပြီး ဒေတာကို Clean လုပ်ပါမယ်။
*/

-- လက်ရှိ Master Table ကို Clean Format ဖြင့် ပြန်လည်တည်ဆောက်ရန် အရင် Drop
DROP TABLE IF EXISTS bi_marathon.dim_master_products;

-- Table Structure ကို ပြန်ဆောက်ပါမယ် 
CREATE TABLE bi_marathon.dim_master_products (
    master_product_id BIGINT NOT NULL,
    primary_source_id BIGINT NOT NULL,
    primary_business_id VARCHAR(191),
    master_match_key VARCHAR(255),
    master_barcode VARCHAR(100),
    master_sku VARCHAR(100),
    master_product_name VARCHAR(255),
    master_description TEXT,
    brand_name VARCHAR(100),
    category_id BIGINT,
    unit_id BIGINT,
    sales_price DECIMAL(20,4),
    purchase_price DECIMAL(20,4),
    last_updated_at DATETIME(3),
    PRIMARY KEY (master_product_id),
    INDEX idx_master_match_key (master_match_key)
);

-- Text Clean Standard Logic ဖြင့် Master Data ပြန်သွင်းခြင်း
INSERT INTO bi_marathon.dim_master_products
WITH RankedProducts AS (
    SELECT 
        id AS original_product_id,
        business_id,
        name,
        description,
        brand_name,
        category_id,
        unit_id,
        NULLIF(TRIM(barcode), '') AS clean_barcode,
        NULLIF(TRIM(sku), '') AS clean_sku,
        sales_price,
        purchase_price,
        is_active,
        created_at,
        updated_at,
        
        -- Text Standardization Rule: စာလုံးကြီးပြောင်း၊ '*' ကို 'X' လဲ၊ Space များ ရှင်းထုတ်ခြင်း
        UPPER(TRIM(REPLACE(REPLACE(name, '*', 'X'), ' ', ''))) AS normalized_name,
        
        -- Master Identity dynamic build
        COALESCE(NULLIF(TRIM(barcode), ''), NULLIF(TRIM(sku), '')) AS master_match_key,
        
        -- Partition logic ထဲတွင် Normalized Name ပါ ထည့်သွင်း၍ ခွဲထုတ်ခြင်း
        ROW_NUMBER() OVER (
            PARTITION BY 
                COALESCE(NULLIF(TRIM(barcode), ''), NULLIF(TRIM(sku), '')),
                UPPER(TRIM(REPLACE(REPLACE(name, '*', 'X'), ' ', '')))
            ORDER BY 
                is_active DESC,
                updated_at DESC, 
                id DESC
        ) AS rank_order
    FROM bi_marathon.products
    WHERE (barcode IS NOT NULL AND TRIM(barcode) != '') 
       OR (sku IS NOT NULL AND TRIM(sku) != '')
)
SELECT 
    -- ၎င်း Normalized Format အတိုင်း Unique ဖြစ်သော Master ID ထုတ်ပေးခြင်း
    DENSE_RANK() OVER (ORDER BY master_match_key, normalized_name) AS master_product_id,
    original_product_id AS primary_source_id,
    business_id AS primary_business_id,
    master_match_key,
    clean_barcode AS master_barcode,
    clean_sku AS master_sku,
    
    -- Display Name အဖြစ် 'X' ပြောင်းလဲပြီးသား standard ကို သုံးမည်
    REPLACE(UPPER(TRIM(name)), '*', 'X') AS master_product_name,
    description AS master_description,
    brand_name,
    category_id,
    unit_id,
    sales_price,
    purchase_price,
    updated_at AS last_updated_at
FROM RankedProducts
WHERE rank_order = 1;

-- Bridge Table ကို ရှင်းလင်းပြီး ဒေတာအသစ်ပြန်သွင်းခြင်း
TRUNCATE TABLE bi_marathon.bridge_product_mapping;

INSERT INTO bi_marathon.bridge_product_mapping (original_product_id, business_id, master_product_id, mapped_by_strategy)
SELECT 
    p.id AS original_product_id,
    p.business_id,
    m.master_product_id,
    'NORMALIZED_TEXT_MATCH' AS mapped_by_strategy
FROM bi_marathon.products p
INNER JOIN bi_marathon.dim_master_products m 
    ON COALESCE(NULLIF(TRIM(p.barcode), ''), NULLIF(TRIM(p.sku), '')) = m.master_match_key
    AND UPPER(TRIM(REPLACE(REPLACE(p.name, '*', 'X'), ' ', ''))) = UPPER(TRIM(REPLACE(REPLACE(m.master_product_name, '*', 'X'), ' ', '')));

-- Final BI Products Table ကို ရှင်းလင်းပြီး ညှိပြီးသား Master ID များဖြင့် ဒေတာပြန်သွင်းခြင်း
TRUNCATE TABLE bi_marathon.products;

INSERT INTO bi_marathon.products (
    id, master_product_id, business_id, name, description, category_id, unit_id, supplier_id, sku, barcode,
    sales_price, sales_account_id, sales_tax_id, sales_tax_type, is_sales_tax_inclusive, purchase_price, 
    purchase_account_id, purchase_tax_id, purchase_tax_type, inventory_account_id, is_active, is_batch_tracking, 
    is_expiry_date_tracking, external_system_id, created_at, updated_at, nature, sequence_no, is_sellable, 
    is_purchasable, reorder_point, cache_invalidated_at, brand_name, length, width, height, weight, master_id, 
    shelf_life_days, purchased_sku
)
SELECT 
    p.id, b.master_product_id, p.business_id, p.name, p.description, p.category_id, p.unit_id, p.supplier_id, p.sku, p.barcode,
    p.sales_price, p.sales_account_id, p.sales_tax_id, p.sales_tax_type, p.is_sales_tax_inclusive, p.purchase_price, 
    p.purchase_account_id, p.purchase_tax_id, p.purchase_tax_type, p.inventory_account_id, p.is_active, p.is_batch_tracking, 
    p.is_expiry_date_tracking, p.external_system_id, p.created_at, p.updated_at, p.nature, p.sequence_no, p.is_sellable, 
    p.is_purchasable, p.reorder_point, p.cache_invalidated_at, p.brand_name, p.length, p.width, p.height, p.weight, p.master_id, 
    p.shelf_life_days, p.purchased_sku
FROM bi_marathon.products p
INNER JOIN bi_marathon.bridge_product_mapping b 
    ON p.id = b.original_product_id AND p.business_id = b.business_id;

-- ရလဒ်သည် 0 ထွက်လာရပါမည်။
SELECT COUNT(*) AS total_asterisk_names 
FROM bi_marathon.dim_master_products 
WHERE master_product_name LIKE '%*%';

-- ဒီ Query မှာ ရလဒ်ထွက်လာခဲ့ရင် အဲဒီကုန်ပစ္စည်းတွေက Barcode တူသော်လည်း တကယ်ပဲ Size မတူတာ (ဥပမာ- 400G နှင့် 200G ကဲ့သို့ ကုန်ပစ္စည်းအစစ်အမှန် ကွဲပြားနေခြင်း) သို့မဟုတ် ဒေတာအမှားကြောင့် နာမည်လုံးဝကွဲနေခြင်း ဖြစ်ကြောင်း သေချာစေမှာ ဖြစ်ပါတယ်။
SELECT 
    master_barcode, 
    COUNT(DISTINCT master_product_id) AS total_master_ids,
    GROUP_CONCAT(DISTINCT master_product_name SEPARATOR ' | ') AS combined_names
FROM bi_marathon.dim_master_products
WHERE master_barcode IS NOT NULL
GROUP BY master_barcode
HAVING COUNT(DISTINCT master_product_id) > 1;

-- မူရင်း Row ၄၇,၁၂၁ အားလုံး Target Table ထဲသို့ ဆုံးရှုံးမှုမရှိ ရောက်/မရောက် စစ်ဆေးခြင်း
SELECT 
    (SELECT COUNT(*) FROM bi_marathon.products WHERE (barcode IS NOT NULL AND TRIM(barcode) != '') OR (sku IS NOT NULL AND TRIM(sku) != '')) AS source_count,
    (SELECT COUNT(*) FROM bi_marathon.bridge_product_mapping) AS bridge_count,
    (SELECT COUNT(*) FROM bi_marathon.products) AS final_bi_count;
    
-- စောပိုင်းက ပြဿနာရှိခဲ့သော Super Seasoning Product Group အား နမူနာ ထုတ်ကြည့်ခြင်း
SELECT 
    master_product_id, 
    master_barcode, 
    master_product_name, 
    sales_price
FROM bi_marathon.dim_master_products
WHERE master_product_name LIKE '%SUPER SEASONING GOLDEN FISH%';

-- Barcode မပါဝင်သော Master Products အရေအတွက်နှင့် စာရင်းကို အကျဉ်းချုပ်ကြည့်ခြင်း
SELECT 
    master_product_id,
    master_sku,
    master_product_name,
    brand_name,
    sales_price,
    last_updated_at
FROM bi_marathon.dim_master_products
WHERE master_barcode IS NULL OR TRIM(master_barcode) = ''
ORDER BY master_product_id;

-- Business Unit အလိုက် Barcode မပါတဲ့ Product ဘယ်နှခုစီ ရှိနေလဲ စစ်ဆေးခြင်း (Aggregation View)
SELECT 
    primary_business_id,
    COUNT(*) AS total_no_barcode_masters,
    GROUP_CONCAT(DISTINCT master_sku SEPARATOR ' , ') AS affected_skus
FROM bi_marathon.dim_master_products
WHERE master_barcode IS NULL OR TRIM(master_barcode) = ''
GROUP BY primary_business_id
ORDER BY total_no_barcode_masters DESC;

-- မူရင်း das-db.products ထဲက Barcode/SKU လုံးဝမပါတဲ့ data ရှာဖွေစစ်ဆေးခြင်း (Full Audit)
SELECT 
    id AS original_product_id,
    business_id,
    name,
    sku,
    barcode,
    created_at
FROM bi_marathon.products
WHERE (barcode IS NULL OR TRIM(barcode) = '') 
  AND (sku IS NULL OR TRIM(sku) = '');


SELECT 
    p.business_id,
    COALESCE(p.category_id, 0) AS category_id,
    
    -- Master Identity ကို သုံး၍ Real Unique Products အရေအတွက်ကို ရေတွက်ခြင်း
    COUNT(DISTINCT p.master_product_id) AS total_unique_master_products,
    
    -- Source Table မှ Mapping အားလုံး အလုပ်လုပ်မှု ရေတွက်ခြင်း
    COUNT(p.id) AS total_source_product_rows

FROM bi_marathon.products p
INNER JOIN bi_marathon.dim_master_products m 
    ON p.master_product_id = m.master_product_id
GROUP BY 
    p.business_id, 
    COALESCE(p.category_id, 0)
ORDER BY 
    p.business_id ASC, 
    total_unique_master_products DESC;

show tables;
select * from dim_master_products dmp ;
SELECT * FROM dim_master_products_categorized ;