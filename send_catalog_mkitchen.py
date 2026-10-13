import os
import pandas as pd
import mysql.connector
import smtplib
import warnings
from typing import Any
from urllib.parse import quote, urlparse, urlunparse
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
# 2. MASTERDATA CATALOG SQL QUERY
# ==========================================
SQL_QUERY = """
SELECT 
    b.name AS branch_name,
    p.sku, 
    p.name, 
    p.weight, 
    p.brand_name, 
    p.description,
    COALESCE(grandparent_c.name, 'NA') AS CategoryL1,
    COALESCE(parent_c.name, 'NA') AS CategoryL2,
    c.name AS CategoryL3,
    CASE 
        WHEN p.is_expiry_date_tracking = true AND (p.shelf_life_days < 30 OR p.shelf_life_days IS NULL) THEN 'Confirm shelf life'
        WHEN p.brand_name IS NULL OR TRIM(p.brand_name) = '' THEN 'Confirm brand name'
        WHEN p.is_batch_tracking = false AND parent_c.name != 'Containers' THEN 'No batch tracking'
        WHEN p.is_expiry_date_tracking = false AND c.name = 'Perishable' THEN 'No expiry date tracking'
        WHEN exp.red_qty > 0 THEN 'Expired Stock (Red Alert)'
        WHEN exp.orange_qty > 0 THEN 'Near Expiry Stock (Orange Alert)'
        ELSE 'OK'
    END AS MasterdataAlert,
    COALESCE(exp.orange_qty, 0) AS orange_qty,
    COALESCE(exp.red_qty, 0) AS red_qty,
    (COALESCE(exp.orange_qty, 0) + COALESCE(exp.red_qty, 0)) AS alert_quantities,
    img.image_url AS product_image_url
FROM products AS p
-- Branch 34 ကို Business ID ဖြင့် တိုက်ရိုက် Inner Join ချိတ်ဆက်ခြင်း
INNER JOIN branches AS b 
    ON b.id = 34 
   AND b.business_id = p.business_id
   AND b.is_active = 1
LEFT JOIN product_categories AS c ON p.category_id = c.id
LEFT JOIN product_categories AS parent_c ON c.parent_category_id = parent_c.id
LEFT JOIN product_categories AS grandparent_c ON parent_c.parent_category_id = grandparent_c.id
LEFT JOIN (
    SELECT 
        bd.product_id,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
        SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
    FROM bill_details AS bd
    -- bills table ကို JOIN ချိတ်ပြီး branch_id = 34 နှင့် business_id ကို စစ်ဆေးခြင်း
    INNER JOIN bills AS bill ON bd.bill_id = bill.id
    WHERE bd.expiry_date IS NOT NULL
      AND bill.branch_id = 34
      AND bill.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
      AND bill.current_status != 'Void' -- Current status Active ဖြစ်သော Bill များကိုသာ တွက်ချက်ရန်
    GROUP BY bd.product_id
) AS exp ON p.id = exp.product_id
LEFT JOIN (
    SELECT reference_id, MIN(image_url) AS image_url
    FROM images 
    WHERE reference_type LIKE '%Product%' 
    GROUP BY reference_id
) AS img ON p.id = img.reference_id
WHERE (p.is_sellable = true OR p.is_purchasable = true)
    AND p.is_active = true 
    AND p.nature = 'G'
    AND p.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
ORDER BY CategoryL3 ASC, p.weight ASC, p.name ASC;
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def clean_image_url(url_str):
    """ Clean spaces and sanitize raw URL string """
    if not url_str or pd.isna(url_str):
        return ""
    
    raw_url = str(url_str).strip()
    raw_url = raw_url.split('](')[0].replace('[', '').replace(']', '')

    if not (raw_url.startswith('http://') or raw_url.startswith('https://')):
        return ""
    
    try:
        parsed = urlparse(raw_url)
        encoded_path = quote(parsed.path)
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            encoded_path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
    except Exception:
        return raw_url.replace(" ", "%20")

def extract_masterdata():
    print("⏳ Fetching Master Data Catalog from Database...")
    try:
        conn: Any = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql(SQL_QUERY, conn)
        conn.close()
        print(f" SQL Extract Completed: Total {len(df)} products fetched.")
        return df.fillna('')
    except Exception as e:
        print(f"❌ Database Connection Failed: {str(e)}")
        raise e

def generate_data_fetching_info_html():
    code_style = "background-color: #202124; color: #34a853; padding: 2px 6px; border-radius: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; font-weight: 500;"
    mark_style = "background-color: #e8f0fe; color: #1a73e8; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px;"
    
    return f"""
    <div style="background-color: #f8f9fa; border-left: 4px solid #1a73e8; padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 0 4px 4px 0; font-family: Arial, sans-serif;">
        <h4 style="margin-top: 0; margin-bottom: 12px; color: #1a73e8; font-size: 14px; font-weight: bold;">
            ℹ️ Data Fetching Scope & Business Rules
        </h4>
        <ul style="margin: 0; padding-left: 20px; color: #3c4043; line-height: 1.8;">
            <li><b>Database:</b> Marathon DAS-DB [<code style="{code_style}">MySQL 8.0</code>]</li>
            <li><b>Business Unit:</b> [<code style="{code_style}">business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' (M-Kitchen)</code>]</li>
            <li><b>Scope:</b> Active Goods [<code style="{code_style}">is_active = true</code>, <code style="{code_style}">nature = 'G'</code>] that are <span style="{mark_style}">Sellable</span> or <span style="{mark_style}">Purchasable</span>.</li>
            <li><b>Expiration Rules (bill_details):</b>
                <ul style="margin-top: 4px; padding-left: 20px; line-height: 1.7;">
                    <li><b style="color: #34a853;">Green:</b> Expiration date &gt; 14 days remaining.</li>
                    <li><b style="color: #f2994a;">Orange:</b> Expiration date &lt;= 14 days (Near Expiry).</li>
                    <li><b style="color: #d93025;">Red:</b> Expiration date &lt;= 0 days (Expired Stock).</li>
                </ul>
            </li>
        </ul>
    </div>
    """

def generate_alert_summary_table(df):
    summary_df = df.groupby('MasterdataAlert').agg(
        TotalSKUs=('sku', 'count'),
        Quantities=('alert_quantities', 'sum')
    ).reset_index()
    
    rows_html = ""
    for _, row in summary_df.iterrows():
        alert_status = str(row['MasterdataAlert'])
        
        # Color Logic Optimization Based on Alert Type
        if alert_status == "OK":
            bg_color = "#e6f4ea"    # Soft Light Green
            text_color = "#137333"  # Dark Green
        elif "Orange" in alert_status or alert_status == "Near Expiry Stock (Orange Alert)":
            bg_color = "#feefe3"    # Soft Light Orange
            text_color = "#b06000"  # Dark Orange / Amber
        else:
            bg_color = "#fce8e6"    # Soft Light Red
            text_color = "#c5221f"  # Dark Red
            
        qty_display = f"{float(row['Quantities']):,.2f}" if row['Quantities'] > 0 else "-"
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding: 8px 12px;">
                <span style="background-color: {bg_color}; color: {text_color}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">
                    {alert_status}
                </span>
            </td>
            <td style="padding: 8px 12px; text-align: center; font-weight: bold;">{row['TotalSKUs']:,}</td>
            <td style="padding: 8px 12px; text-align: center; font-weight: bold; color: {text_color};">{qty_display}</td>
        </tr>
        """
    
    return f"""
    <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 65%; font-size: 12px; border: 1px solid #e0e0e0; margin-bottom: 25px;">
        <thead>
            <tr style="background-color: #f1f3f4; color: #333333; text-align: left; border-bottom: 2px solid #e0e0e0;">
                <th style="padding: 8px 12px;">Product Alert Type</th>
                <th style="padding: 8px 12px; text-align: center;">Total SKUs</th>
                <th style="padding: 8px 12px; text-align: center;">Quantities (Orange/Red)</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    """

def generate_catalog_table(df_alerts, max_rows=10):
    if df_alerts.empty:
        return "<p style='color: #137333; font-weight: bold;'>🎉 Great news! No Product Alerts found today.</p>", "2. Action Required: Product Alerts"

    df_alerts_cleaned = df_alerts.copy()
    df_alerts_cleaned['clean_url'] = df_alerts_cleaned['product_image_url'].apply(clean_image_url)

    # 1. Filter ONLY items where URL is not empty/null AND alert exists
    df_valid_with_img = df_alerts_cleaned[df_alerts_cleaned['clean_url'] != ""].copy()
    
    total_alerts_count = len(df_alerts)
    total_valid_img_count = len(df_valid_with_img)

    if df_valid_with_img.empty:
        return "<p style='color: #5f6368;'>ℹ️ Alerts exist, but no valid product image URLs were available to display in the email body.</p>", "2. Action Required: Product Alerts"

    # 2. Limit to top N rows (max_rows = 10)
    display_df = df_valid_with_img.head(max_rows)
    shown_count = len(display_df)

    rows_html = ""
    for _, row in display_df.iterrows():
        img_url = row['clean_url']
        alert = row['MasterdataAlert']
        
        alert_badge = f'<span style="background-color: #fce8e6; color: #c5221f; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;">{alert}</span>'

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding: 8px; text-align: center; width: 60px;">
                <a href="{img_url}" target="_blank">
                    <img src="{img_url}" width="45" height="45" style="object-fit: cover; border-radius: 4px; border: 1px solid #dcdfe6; display: block; margin: 0 auto;" alt="Product">
                </a>
            </td>
            <td style="padding: 8px; font-family: monospace; font-weight: bold; font-size: 11px;">{row['sku']}</td>
            <td style="padding: 8px;">
                <b style="color: #1a73e8;">{row['name']}</b><br>
                <span style="font-size: 11px; color: #5f6368;">Brand: {row['brand_name'] if row['brand_name'] else 'N/A'}</span>
            </td>
            <td style="padding: 8px; font-size: 11px; color: #3c4043;">
                {row['CategoryL1']} > {row['CategoryL2']} > <b>{row['CategoryL3']}</b>
            </td>
            <td style="padding: 8px; text-align: right; font-size: 11px;">{row['weight']}</td>
            <td style="padding: 8px; text-align: center;">{alert_badge}</td>
        </tr>
        """

    # Dynamic Header Title based on actual rows displayed
    section_title = f"Action Required: Product Alerts with Images"
    
    footer_note = f"<p style='font-size: 11px; color: #5f6368;'>Showing top {shown_count} of {total_valid_img_count} alert items with valid images (Total {total_alerts_count} alert items). Complete list is available in attached CSV.</p>"

    table_html = f"""
    <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 12px; border: 1px solid #e0e0e0;">
        <thead>
            <tr style="background-color: #d93025; color: #ffffff; text-align: left;">
                <th style="padding: 10px; text-align: center;">Image</th>
                <th style="padding: 10px;">SKU</th>
                <th style="padding: 10px;">Product Name & Brand</th>
                <th style="padding: 10px;">Category Hierarchy (L1 > L2 > L3)</th>
                <th style="padding: 10px; text-align: right;">Weight</th>
                <th style="padding: 10px; text-align: center;">Alert Status</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    {footer_note}
    """
    return table_html, section_title

def send_catalog_email():
    df_all = extract_masterdata()
    if df_all.empty:
        print("⚠️ No product records found. Email process aborted.")
        return

    df_alerts = df_all[df_all['MasterdataAlert'] != 'OK'].copy()

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

    msg['Subject'] = f"M-Kitchen Report - Product Catalogue - {datetime.now().strftime('%Y-%m-%d')}"

    fetching_info_html = generate_data_fetching_info_html()
    summary_table_html = generate_alert_summary_table(df_all)
    catalog_table_html, dynamic_section_title = generate_catalog_table(df_alerts, max_rows=10)

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333333; line-height: 1.5;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
           M-Kitchen Product Catalogue
        </h2>
        
        <p style="font-size: 14px;">Hello everyone,</p>
        <p>Please find the M-Kitchen catalog as of <b>{datetime.now().strftime('%d %B %Y')}</b>.</p>
        
        <h4 style="color: #202124; margin-bottom: 8px;">Product Alert Type Summary</h4> 
        {summary_table_html}

        <h4 style="color: #d93025; margin-bottom: 8px;">{dynamic_section_title}</h4>
        {catalog_table_html}

        <br>
        {fetching_info_html}

        <hr style="border: 0; border-top: 1px solid #e0e0e0; margin-top: 30px;">
        <p style="font-size: 11px; color: #9aa0a6;">Marathon Myanmar | Data Engineering & Master Data Governance</p>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_content, 'html'))

    df_all['product_image_url'] = df_all['product_image_url'].apply(clean_image_url)
    csv_bytes = df_all.to_csv(index=False).encode('utf-8-sig')
    filename = f"M-Kitchen_Product_Catalogue_{datetime.now().strftime('%Y%m%d')}.csv"
    
    attachment = MIMEApplication(csv_bytes, Name=filename)
    attachment['Content-Disposition'] = f'attachment; filename="{filename}"'
    msg.attach(attachment)

    all_recipients = to_emails + cc_emails

    try:
        print("⏳ Sending Master Data Catalog Email with CSV Attachment...")
        server = smtplib.SMTP(SMTP_CONFIG['smtp_server'], SMTP_CONFIG['smtp_port'])
        server.starttls()
        server.login(SMTP_CONFIG['sender_email'], SMTP_CONFIG['sender_password'])
        server.sendmail(SMTP_CONFIG['sender_email'], all_recipients, msg.as_string())
        server.quit()
        print(f" Email Catalog with CSV Sent Successfully! (To: {to_emails})")
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")

if __name__ == "__main__":
    send_catalog_email()