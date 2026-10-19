import io
import os
import smtplib
import warnings
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import pandas as pd
import pymysql
from dotenv import load_dotenv

# Google Sheets Imports
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 0. INITIAL SETTINGS & ENVIRONMENT SETUP
# ==========================================
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas.io.sql")
load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# MySQL Configuration
DB_HOST = os.getenv("BI_DB_HOST", "")
DB_PORT = int(os.getenv("BI_DB_PORT", 25060))
DB_USER = os.getenv("BI_DB_USER", "kmkyaw")
DB_PASS = os.getenv("BI_DB_PASS", "")
DB_NAME = os.getenv("DAS_DB_NAME", "bi_database")

# Google Sheet Configuration
GOOGLE_SHEET_ID = "15R0rHDzmX9b-SxttgT8liXTYtTybcBBSwLGTpTSJG98"
SERVICE_ACCOUNT_FILE = os.path.join(CURRENT_DIR, "service_account_update.json")

# M-Trading Configuration
# Aggregates data from two business IDs, excluding M-Kitchen (Branch 34) from the first one.
STORE_CONFIG = {
    "m_trading": {
        "display": "M-Trading",
        "store_code": "m_trading"
    }
}

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

receivers_raw = os.getenv("mtrading_email", "")
RECEIVER_EMAILS = [email.strip() for email in receivers_raw.split(",") if email.strip()]

cc_receivers_raw = os.getenv("cccccc", "")
CC_EMAILS = [email.strip() for email in cc_receivers_raw.split(",") if email.strip()]

# COLOR PALETTE FOR REPLENISHMENT STATUS
COLOR_SHORTAGE = "#ef4444"       # Red
COLOR_URGENT = "#f97316"         # Orange
COLOR_IDENTIFIED = "#10b981"     # Green
COLOR_NO_NEED = "#64748b"        # Slate Gray
COLOR_PRIMARY = "#004b87"


# ==========================================
# HELPER FUNCTION: GET MYSQL QUERY FOR M-TRADING
# ==========================================
def get_mtrading_replenishment_query() -> str:
    """Calculates inventory replenishment for M-Trading, combining multiple business IDs and excluding M-Kitchen (Branch 34)."""
    return """
    WITH target_branches AS (
        -- Maps the specific branch filtering logic for M-Trading
        SELECT id AS branch_id, business_id
        FROM branches
        WHERE 
            (business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND id != 34)
            OR 
            (business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
    ),
    target_businesses AS (
        SELECT DISTINCT business_id FROM target_branches
    )
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
            p.id AS product_id,
            p.sku,
            p.name AS product_name,
            p.business_id,
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
            
            -- Actual Margin Percentage
            CASE 
                WHEN lp.last_purchase_cost IS NULL THEN NULL
                WHEN p.sales_price > 0 THEN 
                    ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
                ELSE 0 
            END AS actual_margin_percentage

        FROM products p
        
        -- Subquery 1: COMBINED Sales Summary (POS + Invoices)
        LEFT JOIN (
            SELECT 
                product_id,
                business_id,
                SUM(total_sales_qty) / 4.0 AS avg_weekly_sales
            FROM (
                -- 1a. POS Sales
                SELECT 
                    posd.product_id,
                    posi.business_id,
                    SUM(posd.detail_qty) AS total_sales_qty
                FROM pos_checkout_details posd
                JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
                INNER JOIN target_branches tb ON posi.branch_id = tb.branch_id AND posi.business_id = tb.business_id
                WHERE posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
                  AND posi.current_status != 'Void'
                GROUP BY posd.product_id, posi.business_id
                
                UNION ALL
                
                -- 1b. Standard Invoice Sales
                SELECT 
                    sid.product_id,
                    si.business_id,
                    SUM(sid.detail_qty) AS total_sales_qty
                FROM sales_invoice_details sid
                JOIN sales_invoices si ON si.id = sid.sales_invoice_id
                INNER JOIN target_branches tb ON si.branch_id = tb.branch_id AND si.business_id = tb.business_id
                WHERE si.invoice_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
                  AND si.current_status NOT IN ('Draft', 'Void')
                GROUP BY sid.product_id, si.business_id
            ) AS combined_sales
            GROUP BY product_id, business_id
        ) sls ON sls.product_id = p.id AND sls.business_id = p.business_id

        -- Subquery 2: Stock Summary (Filtered via target_branches -> warehouses)
        LEFT JOIN (
            SELECT 
                ss.product_id,
                ss.business_id,
                SUM(ss.current_qty) AS total_current_stock
            FROM stock_summaries ss
            INNER JOIN warehouses w ON ss.warehouse_id = w.id AND ss.business_id = w.business_id
            INNER JOIN target_branches tb ON w.branch_id = tb.branch_id AND w.business_id = tb.business_id
            GROUP BY ss.product_id, ss.business_id
        ) stk ON stk.product_id = p.id AND stk.business_id = p.business_id

        -- Subquery 3: Last Purchased Batch & Cost
        LEFT JOIN (
            SELECT 
                bd.product_id,
                b.business_id,
                bd.batch_number AS last_purchased_batch,
                bd.detail_unit_rate AS last_purchase_cost,
                b.bill_date AS last_purchase_date,
                ROW_NUMBER() OVER(
                    PARTITION BY bd.product_id, b.business_id 
                    ORDER BY b.bill_date DESC, b.id DESC
                ) as rn
            FROM bill_details bd
            INNER JOIN bills b ON bd.bill_id = b.id
            INNER JOIN target_branches tb ON b.branch_id = tb.branch_id AND b.business_id = tb.business_id
            WHERE b.current_status NOT IN ('Draft', 'Void')
        ) lp ON lp.product_id = p.id AND lp.business_id = p.business_id AND lp.rn = 1

        -- Category Joins
        LEFT JOIN product_categories pc ON p.category_id = pc.id AND p.business_id = pc.business_id
        LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id AND pc.business_id = pc1.business_id
        LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id AND pc1.business_id = pc2.business_id

        INNER JOIN target_businesses tbiz ON p.business_id = tbiz.business_id
        
        WHERE (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
    ) cm
    -- Subquery 4: Expiry Alert Check
    LEFT JOIN (
        SELECT 
            bd.product_id,
            bill.business_id,
            SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
            SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
        FROM bill_details AS bd
        INNER JOIN bills AS bill ON bd.bill_id = bill.id
        INNER JOIN target_branches tb ON bill.branch_id = tb.branch_id AND bill.business_id = tb.business_id
        WHERE bd.expiry_date IS NOT NULL
          AND bill.current_status != 'Void'
        GROUP BY bd.product_id, bill.business_id
    ) AS exp ON exp.product_id = cm.product_id AND exp.business_id = cm.business_id
    ORDER BY weekly_revenue_loss DESC;
    """


# ==========================================
# HELPER FUNCTION: UPLOAD TO GOOGLE SHEETS
# ==========================================
def update_google_sheet(df: pd.DataFrame, store_display_name: str):
    """Updates Google Sheet with 1 sheet per store, excluding cost/margin columns and converting dates to string"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"⚠️ Service account file not found at {SERVICE_ACCOUNT_FILE}. Skipping Google Sheet update.")
        return

    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
        client = gspread.authorize(creds) # type: ignore

        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

        # Columns to exclude as per request
        excluded_cols = ['last_purchase_cost', 'actual_margin_amount', 'actual_margin_percentage', 'weekly_margin_loss']
        sheet_df = df.drop(columns=[col for col in excluded_cols if col in df.columns], errors='ignore').copy()

        # Convert datetime/date objects to string to prevent JSON serialization errors
        for col in sheet_df.select_dtypes(include=['object', 'datetime64', 'datetimetz']).columns:
            sheet_df[col] = sheet_df[col].astype(str).replace(['NaT', 'None', 'nan'], '')

        # Try to select worksheet or create if not exists
        try:
            worksheet = spreadsheet.worksheet(store_display_name)
            worksheet.clear()  # Erase previous week's data
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=store_display_name, rows=1000, cols=30)

        # Prepare data for upload
        data_to_upload = [sheet_df.columns.tolist()] + sheet_df.fillna("").values.tolist()
        worksheet.update(data_to_upload)
        print(f"✅ Google Sheet updated successfully for [{store_display_name}]!")

    except Exception as e:
        print(f"❌ Failed to update Google Sheet for [{store_display_name}]: {str(e)}")


# ==========================================
# HELPER FUNCTION: BUILD & SEND REPLENISHMENT EMAIL
# ==========================================
def send_replenishment_email(
    df: pd.DataFrame, 
    store_display_name: str, 
    store_code: str,
    date_str: str,
    sender: str, 
    password: str, 
    receivers: list, 
    cc_receivers: Optional[list] = None
):
    if df.empty:
        print(f"⚠️ Replenishment DataFrame for {store_display_name} is empty. Skipping email.")
        return

    cc_list = cc_receivers if cc_receivers is not None else []

    # Filter out "No need" as per requirements
    needed_df = df[df['stock_status'].str.contains('1. Shortage|2. Urgent need|3. Identified need', case=False, regex=True)].copy()

    # Section 1: Calculate Summary Counts
    shortage_count = len(df[df['stock_status'].str.contains('Shortage', case=False)])
    urgent_count = len(df[df['stock_status'].str.contains('Urgent need', case=False)])
    identified_count = len(df[df['stock_status'].str.contains('Identified need', case=False)])

    total_propositions = len(needed_df)

    # Sort explicitly by weekly_revenue_loss descending as requested
    needed_df = needed_df.sort_values(by='weekly_revenue_loss', ascending=False)

    # Build Section 2 Table HTML (Including Estimated Weekly Losses)
    table_rows_html = ""
    for idx, row in needed_df.iterrows():
        status_text = row['stock_status']
        if 'Shortage' in status_text:
            badge_color = COLOR_SHORTAGE
            clean_status = "Shortage"
        elif 'Urgent' in status_text:
            badge_color = COLOR_URGENT
            clean_status = "Urgent need"
        else:
            badge_color = COLOR_IDENTIFIED
            clean_status = "Identified need"

        alert_status = row.get('MasterdataAlert', 'OK')
        
        # Alert Badge Color Styling
        if alert_status == "OK":
            alert_bg = "#e6f4ea"
            alert_color = "#137333"
        elif "Orange" in alert_status or "Near Expiry" in alert_status:
            alert_bg = "#feefe3"
            alert_color = "#b06000"
        else:
            alert_bg = "#fce8e6"
            alert_color = "#c5221f"

        # Format Values Handling Nulls gracefully
        last_cost = f"{row['last_purchase_cost']:,.0f}" if pd.notnull(row['last_purchase_cost']) else "N/A"
        margin_amt = f"{row['actual_margin_amount']:,.0f}" if pd.notnull(row['actual_margin_amount']) else "N/A"
        margin_pct = f"{row['actual_margin_percentage']:.1f}%" if pd.notnull(row['actual_margin_percentage']) else "N/A"
        rev_loss = f"{row['weekly_revenue_loss']:,.0f}" if pd.notnull(row['weekly_revenue_loss']) else "0"
        mgn_loss = f"{row['weekly_margin_loss']:,.0f}" if pd.notnull(row['weekly_margin_loss']) else "0"

        table_rows_html += f"""
        <tr>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; white-space: nowrap;">
                <span style="background-color: {badge_color}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">
                    {clean_status}
                </span>
            </td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; white-space: nowrap;">
                <span style="background-color: {alert_bg}; color: {alert_color}; padding: 3px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;">
                    {alert_status}
                </span>
            </td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; font-weight: 600;">{row['sku']}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0;">{row['product_name']}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{row['total_stock']:,.0f}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{row['avg_weekly_sales']:,.2f}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold; color: #004b87;">
                {row['recommended_replenishment_qty']:,.0f}
            </td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold; color: #dc2626;">{rev_loss}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold; color: #d97706;">{mgn_loss}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{row['standard_selling_price']:,.0f}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; color: #64748b;">{last_cost}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600;">{margin_amt}</td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600; color: #16a34a;">{margin_pct}</td>
        </tr>
        """

    # Subject & Email Title Setup
    email_subject = f"{store_display_name} report - Replenishment - {date_str}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          body {{
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
            line-height: 1.5;
            background-color: #f1f5f9;
            margin: 0;
            padding: 10px;
          }}
          .container {{
            width: 100%;
            max-width: 100%;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            box-sizing: border-box;
          }}
          .header {{
            border-bottom: 3px solid #004b87;
            padding-bottom: 12px;
            margin-bottom: 20px;
          }}
          .header h2 {{
            color: #004b87;
            margin: 0;
            font-size: 22px;
            font-weight: 700;
          }}
          .summary-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 24px;
          }}
          .summary-item {{
            display: inline-block;
            margin-right: 25px;
            font-size: 14px;
            font-weight: 600;
          }}
          .section-title {{
            color: #004b87;
            font-size: 16px;
            font-weight: 700;
            margin-top: 24px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 6px;
          }}
          .table-responsive {{
            width: 100%;
            overflow-x: auto;
          }}
          table.styled-table {{
            border-collapse: collapse;
            width: 100%;
            font-size: 12px;
            margin-bottom: 20px;
          }}
          table.styled-table th {{
            background-color: #004b87;
            color: #ffffff;
            padding: 10px 10px;
            text-align: left;
            font-weight: 600;
            white-space: nowrap;
          }}
          .formula-box {{
            background-color: #f0f7ff;
            border-left: 4px solid #004b87;
            padding: 14px 16px;
            font-size: 12.5px;
            color: #334155;
            margin-top: 30px;
            border-radius: 0 6px 6px 0;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>{store_display_name} Replenishment Report</h2>
          </div>

          <!-- SECTION 1: WEEKLY REPLENISHMENT SUMMARY -->
          <div class="section-title">1. Weekly Replenishment Summary</div>
          <div class="summary-card">
            <div class="summary-item" style="color: {COLOR_SHORTAGE};">
                🚨 Shortage: <span>{shortage_count} SKUs</span>
            </div>
            <div class="summary-item" style="color: {COLOR_URGENT};">
                ⚠️ Urgent need: <span>{urgent_count} SKUs</span>
            </div>
            <div class="summary-item" style="color: {COLOR_IDENTIFIED};">
                ✅ Identified need: <span>{identified_count} SKUs</span>
            </div>
          </div>

          <!-- SECTION 2: DETAILED REPLENISHMENT PROPOSITIONS -->
          <div class="section-title">2. Detailed Replenishment Propositions ({total_propositions} SKUs - Sorted by Weekly Revenue Loss)</div>
          <div class="table-responsive">
            <table class="styled-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Alert Status</th>
                  <th>SKU</th>
                  <th>Product Name</th>
                  <th style="text-align: right;">Current Stock</th>
                  <th style="text-align: right;">Avg Sales/Wk</th>
                  <th style="text-align: right;">Rec. Order Qty</th>
                  <th style="text-align: right; color: #f87171;">Weekly Rev. Loss</th>
                  <th style="text-align: right; color: #fbbf24;">Weekly Margin Loss</th>
                  <th style="text-align: right;">Selling Price</th>
                  <th style="text-align: right;">Last Cost</th>
                  <th style="text-align: right;">Margin (MMK)</th>
                  <th style="text-align: right;">Margin (%)</th>
                </tr>
              </thead>
              <tbody>
                {table_rows_html}
              </tbody>
            </table>
          </div>

          <!-- BOTTOM SECTION: FORMULA & CALCULATION LOGIC -->
          <div class="formula-box">
            <b style="color: #004b87; font-size: 13.5px;">📐 Calculation Rules & Formulas (For Reference)</b><br/><br/>
            1. <b>Avg Weekly Sales:</b> <code>Total Sales Qty (Last 28 Days) ÷ 4</code><br/>
            2. <b>Weeks of Supply (WOS):</b> <code>Total Current Stock ÷ Avg Weekly Sales</code><br/>
            3. <b>Recommended Order Qty:</b> <code>MAX(0, (Avg Weekly Sales × 2) - Total Current Stock)</code><br/>
            4. <b>Estimated Weekly Losses:</b> <code>Weekly Revenue Loss = Avg Sales/Wk × Selling Price</code> | <code>Weekly Margin Loss = Avg Sales/Wk × Margin Amount</code><br/><br/>
            <b>📌 Status Rules:</b>
            <ul>
                <li><span style="color: {COLOR_SHORTAGE}; font-weight: bold;">Shortage:</span> WOS = 0 & Recommended Qty > 0</li>
                <li><span style="color: {COLOR_URGENT}; font-weight: bold;">Urgent need:</span> 0 < WOS ≤ 1 & Recommended Qty > 0</li>
                <li><span style="color: {COLOR_IDENTIFIED}; font-weight: bold;">Identified need:</span> WOS > 1 & Recommended Qty > 0</li>
            </ul>
          </div>
        </div>
      </body>
    </html>
    """

    msg = MIMEMultipart('alternative')
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)
    if cc_list:
        msg['Cc'] = ", ".join(cc_list)

    msg['Subject'] = email_subject
    msg.attach(MIMEText(html_body, 'html'))

    # Attach CSV Backup
    csv_file_name = f"replenishment_{store_code}_{date_str}.csv"
    csv_path = os.path.join(CURRENT_DIR, csv_file_name)
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')

    if os.path.exists(csv_path):
        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={csv_file_name}")
        msg.attach(part)

    all_recipients = receivers + cc_list

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 Replenishment Email sent successfully for [{store_display_name}]!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
print("🔄 Starting M-Trading Replenishment Email Pipeline...")

try:
    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4'
    )

    current_date_str = datetime.now().strftime("%Y-%m-%d")

    # Iterate through M-Trading configuration
    for store_code, store_info in STORE_CONFIG.items():
        display_name = store_info["display"]
        
        print(f"\n🚀 Running Replenishment Pipeline for [{display_name}]...")
        
        sql_query = get_mtrading_replenishment_query()
        store_df = pd.read_sql(sql_query, connection) # type: ignore

        if store_df.empty:
            print(f"⚠️ No inventory/sales data found for [{display_name}].")
            continue

        # 1. Send Email and attach CSV
        send_replenishment_email(
            df=store_df,
            store_display_name=display_name,
            store_code=store_code,
            date_str=current_date_str,
            sender=SENDER_EMAIL,
            password=SENDER_PASSWORD,
            receivers=RECEIVER_EMAILS,
            cc_receivers=CC_EMAILS
        )

        # 2. Update Google Sheet
        update_google_sheet(store_df, display_name)

    connection.close()
    print("\n🏁 M-Trading Replenishment Email & Google Sheet Update Processed Successfully!")

except Exception as e:
    print(f"❌ Critical Pipeline Failure: {repr(e)}")