#!/bin/bash

# Project directory
cd /root/k_workspace/projects/automation_scripts_mm

# Virtual Environment Python path
PYTHON="/root/k_workspace/projects/automation_scripts_mm/venv/bin/python"

echo "=================================================="
echo "Starting Daily BI Database Pipeline: $(date)"
echo "=================================================="

# 1. Run Daily FS Sync SQL Script First
$PYTHON -c "
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv('BI_DB_HOST'),
    user=os.getenv('BI_DB_USER'),
    password=os.getenv('BI_DB_PASS'),
    database=os.getenv('BI_DB_NAME'),
    port=int(os.getenv('BI_DB_PORT') or 25060)
)
cursor = conn.cursor()

with open('queries/daily_fs_sync.sql', 'r', encoding='utf-8') as f:
    sql_script = f.read()

for result in cursor.execute(sql_script, multi=True):
    pass
    
conn.commit()
cursor.close()
conn.close()
print('[SUCCESS] Daily FS Sync SQL executed successfully!')
"

# 2. Run update_products_in_db.py
echo "Running update_products_in_db.py..."
$PYTHON update_products_in_db.py

# 3. Run ABC Analysis Views SQL Script After
$PYTHON -c "
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv('BI_DB_HOST'),
    user=os.getenv('BI_DB_USER'),
    password=os.getenv('BI_DB_PASS'),
    database=os.getenv('BI_DB_NAME'),
    port=int(os.getenv('BI_DB_PORT') or 25060)
)
cursor = conn.cursor()

with open('queries/abc_analysis_views.sql', 'r', encoding='utf-8') as f:
    sql_script = f.read()

for result in cursor.execute(sql_script, multi=True):
    pass
    
conn.commit()
cursor.close()
conn.close()
print('[SUCCESS] ABC Analysis SQL script executed successfully!')
"

# 4. Run etl_master_catalog.py
echo "Running etl_master_catalog.py..."
$PYTHON etl_master_catalog.py

# 5. Run etl_purchase_bi.py
echo "Running etl_purchase_bi.py..."
$PYTHON etl_purchase_bi.py

echo "=================================================="
echo "Pipeline completed successfully at $(date)!"
echo "=================================================="