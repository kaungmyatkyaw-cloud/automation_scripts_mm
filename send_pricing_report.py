import os
import pandas as pd
import mysql.connector
import smtplib
import warnings
from typing import Any
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from dotenv import load_dotenv

# Suppress Pandas SQL Connection Warning
warnings.filterwarnings('ignore', category=UserWarning)

# ==========================================
# 0. LOAD ENV WITH EXPLICIT PATH
# ==========================================
base_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_dir, '.env')

if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=True)
else:
    load_dotenv()

# ==========================================
# 1. CONFIGURATIONS
# ==========================================
DB_CONFIG = {
    'user': os.getenv('MYSQL_USERNAME_DAS') or os.getenv('BI_DB_USER'),
    'password': os.getenv('MYSQL_PASSWORD_DAS') or os.getenv('BI_DB_PASS'),
    'host': os.getenv('MYSQL_HOSTNAME_DAS') or os.getenv('BI_DB_HOST'),
    'port': int(os.getenv('MYSQL_PORT_DAS') or os.getenv('BI_DB_PORT') or 25060),
    'database': os.getenv('DAS_DB_NAME', 'das-db'),
    'use_pure': True,
    'ssl_disabled': False
}

def parse_email_list(env_var_name):
    raw_val = os.getenv(env_var_name, '')
    if not raw_val:
        return []
    return [e.strip() for e in raw_val.split(',') if e.strip()]

SMTP_CONFIG = {
    'sender_email': os.getenv('SMTP_SENDER_EMAIL'),
    'sender_password': os.getenv('SMTP_SENDER_PASSWORD'),
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'receiver_emails': parse_email_list('catalog_email'),
    'cc_emails': parse_email_list('catalog_cc')
}

# ==========================================
# 2. RECURSIVE PRICING SQL QUERY
# ==========================================
SQL_QUERY = """
WITH RECURSIVE BaseData AS (
    SELECT 
        p.*,
        NULLIF(TRIM(SUBSTRING_INDEX(p.description, ';', 1)), '') AS Ref_SKU_From_Product
    FROM products AS p
    WHERE p.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND p.is_sellable = TRUE 
      AND p.is_active = TRUE
),

DirectLinks AS (
    SELECT 
        product_id AS source_product_id,
        to_product_id AS target_product_id,
        (CAST(to_qty AS DECIMAL(18,6)) / NULLIF(CAST(qty AS DECIMAL(18,6)), 0)) AS ratio
    FROM product_conversion_links
    WHERE is_active = TRUE
      AND qty > 0 AND to_qty > 0
    
    UNION ALL
    
    SELECT 
        to_product_id AS source_product_id,
        product_id AS target_product_id,
        (CAST(qty AS DECIMAL(18,6)) / NULLIF(CAST(to_qty AS DECIMAL(18,6)), 0)) AS ratio
    FROM product_conversion_links
    WHERE is_active = TRUE
      AND qty > 0 AND to_qty > 0
),

RecursiveGraph AS (
    SELECT 
        id AS root_product_id,
        id AS connected_product_id,
        CAST(1.0 AS DECIMAL(18,6)) AS cumulative_ratio,
        0 AS depth,
        CAST(CONCAT('/', id, '/') AS CHAR(1000)) AS visited_path
    FROM BaseData
    
    UNION ALL
    
    SELECT 
        rg.root_product_id,
        dl.target_product_id AS connected_product_id,
        CAST(rg.cumulative_ratio * dl.ratio AS DECIMAL(18,6)) AS cumulative_ratio,
        rg.depth + 1 AS depth,
        CAST(CONCAT(rg.visited_path, dl.target_product_id, '/') AS CHAR(1000)) AS visited_path
    FROM RecursiveGraph rg
    JOIN DirectLinks dl ON dl.source_product_id = rg.connected_product_id
    WHERE rg.visited_path NOT LIKE CONCAT('%/', dl.target_product_id, '/%')
      AND rg.depth < 5
),

FamilyBills AS (
    SELECT 
        rg.root_product_id,
        b.warehouse_id,
        bd_item.product_id AS Billed_Product_ID,
        p_billed.sku AS Billed_SKU,
        p_billed.weight AS Billed_SKU_Weight,
        COALESCE(b.bill_number, CAST(b.id AS CHAR)) AS Bill_Number,
        (bd_item.detail_total_amount / NULLIF(bd_item.detail_qty, 0)) AS Raw_PO_Price,
        ((bd_item.detail_total_amount / NULLIF(bd_item.detail_qty, 0)) * rg.cumulative_ratio) AS Normalized_PO_Price,
        rg.cumulative_ratio AS Conversion_Ratio_Used,
        b.updated_at AS bill_updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY rg.root_product_id, b.warehouse_id 
            ORDER BY 
                b.updated_at DESC, 
                rg.depth ASC, 
                bd_item.id DESC
        ) AS rn
    FROM RecursiveGraph rg
    JOIN products p_billed ON p_billed.id = rg.connected_product_id
    JOIN bill_details bd_item ON bd_item.product_id = p_billed.id
    JOIN bills b ON b.id = bd_item.bill_id
    WHERE b.current_status IN ('Paid', 'Confirmed')
),

PriceCalculation AS (
    SELECT
        wh.name AS Warehouse_Name,
        br.name AS Branch_Name,
        bd.sku, 
        bd.name AS Product_Name, 
        bd.weight AS Product_Weight, 
        bd.length AS Product_Repacking_Cost, 
        bd.sales_price AS Catalogue_Price, 
        bd.is_sellable AS Sellable, 
        bd.is_purchasable AS Purchasable,
        fb.Bill_Number AS Last_Bill_Number,
        fb.Billed_SKU AS Last_Purchased_SKU,
        fb.Billed_SKU_Weight AS Last_Purchased_SKU_Weight,
        fb.Raw_PO_Price AS Purchased_Raw_PO_Price,
        fb.Normalized_PO_Price AS Calculated_Last_PO_Price,
        fb.Conversion_Ratio_Used AS Purchased_Conversion_Rate,
        fb.bill_updated_at AS Last_Bill_Date,
        COALESCE(pl.name, 'Catalogue Default') AS Price_List_Name,
        COALESCE(plri.unit_price, bd.sales_price) AS Price_List_Unit_Price,
        COALESCE(pc2.name, pc1.name, pc.name) AS Category_L1,
        CASE WHEN pc2.name IS NOT NULL THEN pc1.name WHEN pc1.name IS NOT NULL THEN pc.name ELSE NULL END AS Category_L2,
        CASE WHEN pc2.name IS NOT NULL THEN pc.name ELSE NULL END AS Category_L3
    FROM BaseData AS bd
    CROSS JOIN warehouses AS wh
    LEFT JOIN branches AS br ON wh.branch_id = br.id
    LEFT JOIN FamilyBills fb ON fb.root_product_id = bd.id AND fb.warehouse_id = wh.id AND fb.rn = 1
    LEFT JOIN product_categories AS pc ON bd.category_id = pc.id
    LEFT JOIN product_categories AS pc1 ON pc.parent_category_id = pc1.id
    LEFT JOIN product_categories AS pc2 ON pc1.parent_category_id = pc2.id
    LEFT JOIN price_lists pl ON pl.business_id = bd.business_id AND pl.is_active = TRUE
    LEFT JOIN price_list_rule_items plri ON plri.price_list_id = pl.id AND plri.product_id = bd.id
    WHERE wh.business_id = bd.business_id 
      AND wh.is_active = TRUE
      AND wh.name LIKE 'WH%'
),

FinalCalculations AS (
    SELECT 
        pc.*,
        ROUND(Product_Weight * 300, 2) AS Delivery_Cost
    FROM PriceCalculation pc
)

SELECT
    Warehouse_Name, Branch_Name, SKU, Product_Name, 
    Category_L1, Category_L2, Category_L3,
    Sellable, Purchasable, Price_List_Name, Price_List_Unit_Price,
    CASE 
        WHEN Calculated_Last_PO_Price IS NULL OR Price_List_Unit_Price = 1 THEN 'NA'
        ELSE CAST(ROUND(Price_List_Unit_Price - Total_Cost, 2) AS CHAR)
    END AS Margin_Amount,
    CASE 
        WHEN Calculated_Last_PO_Price IS NULL OR Price_List_Unit_Price = 1 THEN 'NA'
        ELSE CAST(ROUND((Price_List_Unit_Price - Total_Cost) / NULLIF(Price_List_Unit_Price, 0), 4) AS CHAR)
    END AS Margin_Percent,
    CASE 
        WHEN Calculated_Last_PO_Price IS NULL THEN 'No PO price known'
        WHEN Price_List_Unit_Price = 1 THEN 'Price undefined'
        WHEN Price_List_Unit_Price < Total_Cost THEN 'Negative margin'
        ELSE 'No alert'
    END AS Price_Alert,
    Last_Purchased_SKU, Last_Bill_Number, Last_Bill_Date, Purchased_Raw_PO_Price,
    Product_Weight, Last_Purchased_SKU_Weight, Purchased_Conversion_Rate,
    Calculated_Last_PO_Price AS Est_PO_Price,
    Product_Repacking_Cost, Delivery_Cost, Total_Cost
FROM (
    SELECT f.*, 
    ROUND(COALESCE(Calculated_Last_PO_Price, 0) + COALESCE(Product_Repacking_Cost, 0) + COALESCE(Delivery_Cost, 0), 2) AS Total_Cost
    FROM FinalCalculations f
) Final
ORDER BY Warehouse_Name ASC, Category_L3 ASC, Product_Name ASC, Price_List_Unit_Price DESC, Price_List_Name ASC;
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def extract_pricing_data():
    print("⏳ Fetching Pricing & Margin Analysis Data from Database...")
    try:
        conn: Any = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql(SQL_QUERY, conn)
        conn.close()
        print(f" SQL Extract Completed: Total {len(df):,} pricing records fetched.")
        return df.fillna('')
    except Exception as e:
        print(f"❌ Database Connection Failed: {str(e)}")
        raise e

def generate_data_fetching_info_html():
    code_style = "background-color: #202124; color: #34a853; padding: 2px 6px; border-radius: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; font-weight: 500;"
    
    return f"""
    <div style="background-color: #f8f9fa; border-left: 4px solid #1a73e8; padding: 16px; margin-top: 30px; margin-bottom: 20px; font-size: 13px; border-radius: 0 4px 4px 0; font-family: Arial, sans-serif;">
        <h4 style="margin-top: 0; margin-bottom: 12px; color: #1a73e8; font-size: 14px; font-weight: bold;">
            ℹ️ Data Fetching Scope & Business Logic
        </h4>
        <ul style="margin: 0; padding-left: 20px; color: #3c4043; line-height: 1.8;">
            <li><b>Business Scope:</b> Target Business Unit ID [<code style="{code_style}">business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'</code>] across <b>All Active Branches & Warehouses</b> [<code style="{code_style}">WH%</code>].</li>
            <li><b>Product Eligibility:</b> Active & Sellable products [<code style="{code_style}">is_active = true</code>, <code style="{code_style}">is_sellable = true</code>] mapped dynamically across active price lists.</li>
            <li><b>Recursive Conversion Links:</b> Evaluates bi-directional product conversion graphs (up to 5 levels deep) [<code style="{code_style}">depth &lt; 5</code>] to fetch normalized PO costs.</li>
            <li><b>Family Purchase Matching:</b> Matches the latest confirmed/paid bill date [<code style="{code_style}">status IN ('Paid', 'Confirmed')</code>] per product family across all active warehouses.</li>
            <li><b>Cost Calculation:</b> <code style="{code_style}">Total_Cost = Est_PO_Price + Repacking_Cost + Delivery_Cost (Weight × 300)</code>.</li>
            <li><b>Margin Calculation Logic:</b>
                <ul style="margin-top: 4px; padding-left: 20px; line-height: 1.7;">
                    <li><b>Margin Amount:</b> <code style="{code_style}">Margin_Amount = Price_List_Unit_Price - Total_Cost</code> (Calculated as 'NA' if PO Price is missing or Unit Price = 1.00).</li>
                    <li><b>Margin Percentage:</b> <code style="{code_style}">Margin_Percent = (Price_List_Unit_Price - Total_Cost) / Price_List_Unit_Price</code> (Expressed as decimal ratio; 'NA' if invalid).</li>
                </ul>
            </li>
            <li><b>Price Alerts Classification:</b>
                <ul style="margin-top: 4px; padding-left: 20px; line-height: 1.7;">
                    <li><b style="color: #137333;">Healthy margin (No alert):</b> Valid selling price yielding non-negative margin.</li>
                    <li><b style="color: #c5221f;">Negative margin:</b> Selling price is lower than calculated Total Cost [<code style="{code_style}">Price_List_Unit_Price &lt; Total_Cost</code>].</li>
                    <li><b style="color: #b06000;">Missing standard price (Price undefined):</b> Active Price List unit price is set to default nominal value [<code style="{code_style}">Price_List_Unit_Price = 1.00</code>].</li>
                    <li><b style="color: #5f6368;">No PO price known:</b> Warehouse has never purchased this item; excluded from catalogue margin analysis.</li>
                </ul>
            </li>
        </ul>
    </div>
    """

def generate_breakdown_table_html(df, group_col, title):
    grouped = df.groupby(group_col).agg(
        healthy_margin=('Price_Alert', lambda x: (x == 'No alert').sum()),
        negative_margin=('Price_Alert', lambda x: (x == 'Negative margin').sum()),
        price_undefined=('Price_Alert', lambda x: (x == 'Price undefined').sum()),
        no_po_known=('Price_Alert', lambda x: (x == 'No PO price known').sum())
    ).reset_index()

    grouped['total_catalogue'] = grouped['healthy_margin'] + grouped['negative_margin'] + grouped['price_undefined']

    # Sort descending by total catalogue
    grouped = grouped.sort_values(by='total_catalogue', ascending=False)

    rows = ""
    for _, row in grouped.iterrows():
        rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0; text-align: center;">
            <td style="padding: 8px 10px; text-align: left; font-weight: bold; color: #202124;">{row[group_col]}</td>
            <td style="padding: 8px 10px; color: #137333; font-weight: bold; background-color: #e6f4ea;">{row['healthy_margin']:,}</td>
            <td style="padding: 8px 10px; color: #c5221f; font-weight: bold; background-color: #fce8e6;">{row['negative_margin']:,}</td>
            <td style="padding: 8px 10px; color: #b06000; font-weight: bold; background-color: #fef7e0;">{row['price_undefined']:,}</td>
            <td style="padding: 8px 10px; color: #3c4043; font-weight: bold; background-color: #f1f3f4;">{row['total_catalogue']:,}</td>
            <td style="padding: 8px 10px; color: #5f6368;">{row['no_po_known']:,}</td>
        </tr>
        """

    # Add Total Summary Row
    tot_healthy = grouped['healthy_margin'].sum()
    tot_neg = grouped['negative_margin'].sum()
    tot_undef = grouped['price_undefined'].sum()
    tot_cat = grouped['total_catalogue'].sum()
    tot_no_po = grouped['no_po_known'].sum()

    total_row = f"""
    <tr style="background-color: #f8f9fa; font-weight: bold; border-top: 2px solid #bdc1c6; text-align: center;">
        <td style="padding: 8px 10px; text-align: left; color: #202124;">Total</td>
        <td style="padding: 8px 10px; color: #137333;">{tot_healthy:,}</td>
        <td style="padding: 8px 10px; color: #c5221f;">{tot_neg:,}</td>
        <td style="padding: 8px 10px; color: #b06000;">{tot_undef:,}</td>
        <td style="padding: 8px 10px; color: #202124;">{tot_cat:,}</td>
        <td style="padding: 8px 10px; color: #5f6368;">{tot_no_po:,}</td>
    </tr>
    """

    return f"""
    <div style="margin-top: 20px;">
        <h4 style="margin-bottom: 8px; color: #202124; font-size: 13px;">📌 {title}</h4>
        <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 11px; border: 1px solid #e0e0e0;">
            <thead>
                <tr style="background-color: #f1f3f4; color: #3c4043; text-align: center; border-bottom: 2px solid #dc3545;">
                    <th style="padding: 8px 10px; text-align: left;">{group_col.replace('_Name', '')} Name</th>
                    <th style="padding: 8px 10px; color: #137333;">Healthy Margin</th>
                    <th style="padding: 8px 10px; color: #c5221f;">Negative Margin</th>
                    <th style="padding: 8px 10px; color: #b06000;">Missing Std Price</th>
                    <th style="padding: 8px 10px; color: #202124; background-color: #e8eaed;">Total Prices in Catalogue</th>
                    <th style="padding: 8px 10px; color: #5f6368;">No PO Price Known (Excluded)</th>
                </tr>
            </thead>
            <tbody>
                {rows}
                {total_row}
            </tbody>
        </table>
    </div>
    """

def generate_executive_summary_html(df):
    alert_counts = df['Price_Alert'].value_counts().to_dict()
    
    no_alert_count = alert_counts.get('No alert', 0)
    neg_margin_count = alert_counts.get('Negative margin', 0)
    undef_price_count = alert_counts.get('Price undefined', 0)
    no_po_count = alert_counts.get('No PO price known', 0)

    # 1 + 2 + 3 = Total prices in catalogue
    total_catalogue = no_alert_count + neg_margin_count + undef_price_count

    # Filter critical SKUs for executive review (Max top 10 items)
    critical_df = df[df['Price_Alert'] == 'Negative margin'].head(10)
    
    critical_rows = ""
    for _, row in critical_df.iterrows():
        margin_val = row['Margin_Percent']
        if margin_val != 'NA' and margin_val is not None:
            try:
                margin_pct = f"{float(margin_val)*100:.2f}%"
            except ValueError:
                margin_pct = str(margin_val)
        else:
            margin_pct = 'NA'

        critical_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding: 6px 10px;">{row['sku']}</td>
            <td style="padding: 6px 10px;"><b>{row['Product_Name']}</b></td>
            <td style="padding: 6px 10px;">{row['Warehouse_Name']}</td>
            <td style="padding: 6px 10px;">{row['Price_List_Name']}</td>
            <td style="padding: 6px 10px; text-align: right;">{float(row['Price_List_Unit_Price']):,.2f}</td>
            <td style="padding: 6px 10px; text-align: right;">{float(row['Total_Cost']):,.2f}</td>
            <td style="padding: 6px 10px; text-align: right; color: #c5221f; font-weight: bold;">{margin_pct}</td>
        </tr>
        """

    critical_table = f"""
    <p style="font-weight: bold; margin-top: 20px; margin-bottom: 5px; color: #c5221f; font-size: 12px;">Top Negative Margin SKUs (Action Required):</p>
    <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 11px; border: 1px solid #e0e0e0;">
        <thead>
            <tr style="background-color: #fce8e6; color: #c5221f; text-align: left;">
                <th style="padding: 6px 10px;">SKU</th>
                <th style="padding: 6px 10px;">Product Name</th>
                <th style="padding: 6px 10px;">Warehouse</th>
                <th style="padding: 6px 10px;">Price List</th>
                <th style="padding: 6px 10px; text-align: right;">Selling Price</th>
                <th style="padding: 6px 10px; text-align: right;">Total Cost</th>
                <th style="padding: 6px 10px; text-align: right;">Margin %</th>
            </tr>
        </thead>
        <tbody>
            {critical_rows if critical_rows else '<tr><td colspan="7" style="padding: 8px; text-align: center;">No Negative Margin Items Found</td></tr>'}
        </tbody>
    </table>
    """

    # Generate Breakdowns
    branch_breakdown_html = generate_breakdown_table_html(df, 'Branch_Name', 'Margin Alert Breakdown by Branch')
    wh_breakdown_html = generate_breakdown_table_html(df, 'Warehouse_Name', 'Margin Alert Breakdown by Warehouse')

    return f"""
    <div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; margin-bottom: 15px;">
        <h3 style="margin-top: 0; color: #202124; font-size: 15px; border-bottom: 1px solid #eee; padding-bottom: 8px;">
            📊 Executive Summary Dashboard
        </h3>
        
        <!-- Key Metrics Cards -->
        <table border="0" cellpadding="0" cellspacing="0" style="width: 100%; margin-bottom: 15px; font-size: 12px; border-spacing: 5px;">
            <tr>
                <td style="width: 20%; padding: 10px; background-color: #e6f4ea; text-align: center; border-radius: 4px; border: 1px solid #ceead6;">
                    <span style="font-size: 11px; color: #137333; font-weight: bold;">Healthy Margin</span><br>
                    <b style="font-size: 16px; color: #137333;">{no_alert_count:,}</b>
                </td>
                <td style="width: 20%; padding: 10px; background-color: #fce8e6; text-align: center; border-radius: 4px; border: 1px solid #fad2cf;">
                    <span style="font-size: 11px; color: #c5221f; font-weight: bold;">Negative Margin</span><br>
                    <b style="font-size: 16px; color: #c5221f;">{neg_margin_count:,}</b>
                </td>
                <td style="width: 20%; padding: 10px; background-color: #fef7e0; text-align: center; border-radius: 4px; border: 1px solid #feefc3;">
                    <span style="font-size: 11px; color: #b06000; font-weight: bold;">Missing Std Price</span><br>
                    <b style="font-size: 16px; color: #b06000;">{undef_price_count:,}</b>
                </td>
                <td style="width: 20%; padding: 10px; background-color: #e8eaed; text-align: center; border-radius: 4px; border: 1px solid #dadce0;">
                    <span style="font-size: 11px; color: #202124; font-weight: bold;">Total Catalogue</span><br>
                    <b style="font-size: 16px; color: #202124;">{total_catalogue:,}</b>
                </td>
                <td style="width: 20%; padding: 10px; background-color: #f1f3f4; text-align: center; border-radius: 4px; border: 1px solid #bdc1c6;">
                    <span style="font-size: 11px; color: #5f6368; font-weight: bold;">No PO Price Known</span><br>
                    <b style="font-size: 16px; color: #5f6368;">{no_po_count:,}</b>
                </td>
            </tr>
        </table>

        {critical_table if neg_margin_count > 0 else ''}
        
        <!-- Breakdown Tables -->
        {branch_breakdown_html}
        {wh_breakdown_html}
    </div>
    """

def send_pricing_report_email():
    df = extract_pricing_data()
    if df.empty:
        print("⚠️ No pricing records found. Email process aborted.")
        return

    to_emails = SMTP_CONFIG['receiver_emails']
    cc_emails = SMTP_CONFIG['cc_emails']

    if not to_emails:
        print("⚠️ No receiver email defined in .env.")
        return

    msg = MIMEMultipart()
    msg['From'] = SMTP_CONFIG['sender_email']
    msg['To'] = ", ".join(to_emails)
    if cc_emails:
        msg['Cc'] = ", ".join(cc_emails)

    msg['Subject'] = f"Weekly Price List & Margin Report (M-Kitchen system) - {datetime.now().strftime('%Y-%m-%d')}"

    fetching_info_html = generate_data_fetching_info_html()
    executive_summary_html = generate_executive_summary_html(df)

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333333; line-height: 1.5;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
           Weekly Price List & Margin Report (M-Kitchen system)
        </h2>
        
        <p style="font-size: 14px;">Hello everyone,</p>
        <p>I’ve compiled the latest Pricing & Profitability report as of <b>{datetime.now().strftime('%d %B %Y')}</b> for your review.</p>
        
        {executive_summary_html}
        
        <p style="font-size: 12px; color: #5f6368; margin-top: 15px;">
            <i>Note: The complete dynamic pricing analysis dataset is attached as a CSV file for detailed review.</i>
        </p>

        {fetching_info_html}

        <hr style="border: 0; border-top: 1px solid #e0e0e0; margin-top: 30px;">
        <p style="font-size: 11px; color: #9aa0a6;">Marathon Myanmar | BI</p>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_content, 'html'))

    # ==========================================
    # CSV ATTACHMENT LOGIC
    # ==========================================
    csv_bytes = df.to_csv(index=False).encode('utf-8-sig')
    filename = f"Pricing_Margin_Audit_{datetime.now().strftime('%Y%m%d')}.csv"
    
    attachment = MIMEApplication(csv_bytes, Name=filename)
    attachment['Content-Disposition'] = f'attachment; filename="{filename}"'
    msg.attach(attachment)

    all_recipients = to_emails + cc_emails

    try:
        print("⏳ Sending Pricing Audit Email with Attachment...")
        server = smtplib.SMTP(SMTP_CONFIG['smtp_server'], SMTP_CONFIG['smtp_port'])
        server.starttls()
        server.login(SMTP_CONFIG['sender_email'], SMTP_CONFIG['sender_password'])
        server.sendmail(SMTP_CONFIG['sender_email'], all_recipients, msg.as_string())
        server.quit()
        print(f" Pricing Audit Email Sent Successfully! (To: {to_emails})")
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")

if __name__ == "__main__":
    send_pricing_report_email()