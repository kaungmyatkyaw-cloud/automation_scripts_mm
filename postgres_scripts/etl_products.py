import os
import urllib.parse
import pymysql
import psycopg2
from psycopg2.extras import execute_values

# 1. MySQL Connection Configuration
mysql_conn = pymysql.connect(
    host="db-distribution-accounting-do-user-2718740-0.h.db.ondigitalocean.com",
    port=25060,
    user="kmkyaw",
    password="BOs5hA+bMo6UfmgYweaPJqrmD",
    database="das-db",
    cursorclass=pymysql.cursors.DictCursor
)

# 2. Postgres Connection Configuration
raw_password = "4Q*bc3JXj!EW&Rbh"
encoded_password = urllib.parse.quote_plus(raw_password)
postgres_uri = f"postgresql://postgres.avaevgvuwomcfbjtrsbb:{encoded_password}@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"

pg_conn = psycopg2.connect(postgres_uri)

def sync_product_categories():
    print("Starting categories sync to Postgres...")
    try:
        with mysql_conn.cursor() as mysql_cursor:
            query = "SELECT id, name, parent_category_id, is_active FROM product_categories"
            mysql_cursor.execute(query)
            categories = mysql_cursor.fetchall()
            
        print(f"Fetched {len(categories)} categories from MySQL.")
        if not categories:
            print("No categories found in MySQL.")
            return

        cursor = pg_conn.cursor()
        
        cat_tuples_pass1 = []
        parent_updates = []
        
        for row in categories:
            raw_id = row.get('id')
            if raw_id is None:
                continue
            try:
                cat_id = int(raw_id)
            except (ValueError, TypeError):
                continue

            name_val = str(row.get('name', '')) if row.get('name') is not None else ''
            is_active_val = bool(row.get('is_active', True)) if row.get('is_active') is not None else True

            # PASS 1: Explicitly pass None for parent_id to bypass bad defaults and FK checks
            cat_tuples_pass1.append((name_val, is_active_val, cat_id, None))

            raw_parent = row.get('parent_category_id')
            if raw_parent is not None:
                try:
                    p_int = int(raw_parent)
                    if p_int > 0:
                        # Store for Pass 2: (das_parent_id, das_id)
                        parent_updates.append((p_int, cat_id))
                except (ValueError, TypeError):
                    pass

        print(f"Valid Category Tuples prepared: {len(cat_tuples_pass1)}")
        if len(cat_tuples_pass1) == 0:
            print("No valid categories to insert after loop.")
            cursor.close()
            return

        # PASS 1: Upsert base data. COALESCE prevents overwriting existing parent_id with NULL on conflict.
        cat_upsert_query_pass1 = """
            INSERT INTO public.categories (name, is_active, das_id, parent_id)
            VALUES %s
            ON CONFLICT (das_id) 
            DO UPDATE SET 
                name = EXCLUDED.name,
                is_active = EXCLUDED.is_active,
                parent_id = COALESCE(EXCLUDED.parent_id, categories.parent_id);
        """
        execute_values(cursor, cat_upsert_query_pass1, cat_tuples_pass1)
        
        # PASS 2: Resolve parent_id (UUID) and das_parent_id after ALL categories safely exist
        if parent_updates:
            update_query = """
                UPDATE public.categories c
                SET 
                    das_parent_id = v.das_parent_id,
                    parent_id = p.id
                FROM (VALUES %s) AS v(das_parent_id, das_id)
                LEFT JOIN public.categories p ON v.das_parent_id = p.das_id
                WHERE c.das_id = v.das_id;
            """
            execute_values(cursor, update_query, parent_updates)
        
        pg_conn.commit()
        cursor.close()
        print(f"Successfully synced {len(cat_tuples_pass1)} categories to Postgres!")
    except Exception as e:
        pg_conn.rollback()
        print(f"Categories Sync Error: {e}")

def sync_products():
    print("\nStarting products and images sync...")
    try:
        cursor = pg_conn.cursor()
        
        # Load category mappings from Postgres
        cursor.execute("SELECT id, das_id FROM categories WHERE das_id IS NOT NULL")
        cat_mapping = {row[1]: row[0] for row in cursor.fetchall()}
        
        print(f"Loaded {len(cat_mapping)} category mappings from Postgres.")
        if len(cat_mapping) == 0:
            print("❌ Error: No category mapping found! Categories sync failed.")
            return

        # Load images mapping from MySQL
        img_mapping = {}
        with mysql_conn.cursor() as mysql_cursor:
            img_query = "SELECT reference_id, image_url FROM images WHERE reference_type = 'product' OR reference_type LIKE '%product%'"
            mysql_cursor.execute(img_query)
            for img_row in mysql_cursor.fetchall():
                ref_id = img_row.get('reference_id')
                url = img_row.get('image_url')
                if ref_id is not None and url is not None:
                    img_mapping[ref_id] = url

        # Load products from MySQL, ordered by updated_at DESC to prioritize the latest version
        with mysql_conn.cursor() as mysql_cursor:
            prod_query = """
                SELECT id, name, category_id, sku, sales_price, is_active, weight, updated_at 
                FROM products
                ORDER BY updated_at DESC
            """
            mysql_cursor.execute(prod_query)
            products = mysql_cursor.fetchall()

        if not products:
            print("No products found to sync.")
            return

        data_tuples = []
        skipped_count = 0
        seen_skus = set() 

        # Postgres 32-bit integer limits
        MAX_INT = 2147483647
        MIN_INT = -2147483648

        for row in products:
            mysql_prod_id = row.get('id')
            raw_cat_id = row.get('category_id')
            
            if raw_cat_id is None:
                skipped_count += 1
                continue
            
            try:
                mysql_cat_id = int(raw_cat_id)
            except (ValueError, TypeError):
                skipped_count += 1
                continue

            pg_category_uuid = cat_mapping.get(mysql_cat_id)
            if not pg_category_uuid:
                skipped_count += 1
                continue 

            # --- ROBUST SKU HANDLING ---
            raw_sku = row.get('sku')
            if raw_sku is not None:
                sku_val = str(raw_sku).strip()
                # CRITICAL FIX: Convert empty strings to None (NULL)
                if not sku_val:
                    sku_val = None
            else:
                sku_val = None
            
            # Only check for duplicates if SKU is not None
            if sku_val is not None:
                if sku_val in seen_skus:
                    skipped_count += 1
                    continue
                seen_skus.add(sku_val)
            # ---------------------------

            prod_image_url = img_mapping.get(mysql_prod_id, None)
            name_val = row.get('name', '')
            
            # SAFE PRICE CONVERSION
            raw_price = row.get('sales_price', 0)
            try:
                price_float = float(raw_price) if raw_price is not None else 0.0
                cat_price_val = int(price_float)
                
                if cat_price_val > MAX_INT:
                    print(f"⚠️ Warning: Price {cat_price_val} for SKU '{sku_val}' exceeds max integer. Capping at {MAX_INT}.")
                    cat_price_val = MAX_INT
                elif cat_price_val < MIN_INT:
                    cat_price_val = MIN_INT
            except (ValueError, TypeError):
                cat_price_val = 0

            # Weight conversion
            raw_weight = row.get('weight', 99.0)
            try:
                weight_val = float(raw_weight) if raw_weight is not None else 99.0
            except (ValueError, TypeError):
                weight_val = 99.0

            raw_active = row.get('is_active', True)
            is_active_val = bool(raw_active) if raw_active is not None else True

            data_tuples.append((
                pg_category_uuid,
                sku_val,
                name_val,
                cat_price_val,
                weight_val,
                is_active_val,
                mysql_cat_id,
                prod_image_url
            ))

        if skipped_count > 0:
            print(f"Skipped {skipped_count} products due to missing category mapping, invalid category ID, or duplicate SKU.")

        if len(data_tuples) == 0:
            print("No valid products to insert after mapping check.")
            return

        upsert_query = """
            INSERT INTO public.products (
                category_id, sku, name, cat_price, weight, is_active, das_category_id, image_url
            )
            VALUES %s
            ON CONFLICT (sku) 
            DO UPDATE SET 
                category_id = EXCLUDED.category_id,
                name = EXCLUDED.name,
                cat_price = EXCLUDED.cat_price,
                weight = EXCLUDED.weight,
                is_active = EXCLUDED.is_active,
                das_category_id = EXCLUDED.das_category_id,
                image_url = COALESCE(EXCLUDED.image_url, products.image_url);
        """
        
        execute_values(cursor, upsert_query, data_tuples)
        pg_conn.commit()
        cursor.close()
        
        print(f"Successfully synced {len(data_tuples)} products to Postgres!")

    except Exception as e:
        pg_conn.rollback()
        print(f"Products Sync Error: {e}")

if __name__ == "__main__":
    try:
        sync_product_categories()
        sync_products()
    finally:
        mysql_conn.close()
        pg_conn.close()
        print("\nDatabase connections closed.")