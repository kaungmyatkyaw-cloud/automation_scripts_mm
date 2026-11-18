import io
import os
import smtplib
import warnings
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional, cast

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import pymysql
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

# ==========================================
# 0. INITIAL SETTINGS & ENVIRONMENT SETUP
# ==========================================
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_KEYFILE = os.path.join(CURRENT_DIR, "service_account_update.json")
CSV_PRICELIST_PATH = os.path.join(CURRENT_DIR, "mkitchen_pricelist_master.csv")
CSV_INVOICE_PATH = os.path.join(CURRENT_DIR, "mkitchen_invoice_weight.csv")

# MySQL Configuration
DB_HOST = os.getenv("BI_DB_HOST", "")
DB_PORT = int(os.getenv("BI_DB_PORT", 25060))
DB_USER = os.getenv("BI_DB_USER", "kmkyaw")
DB_PASS = os.getenv("BI_DB_PASS", "")
DB_NAME = os.getenv("DAS_DB_NAME", "das-db")

# Google Sheet Configuration
GOOGLE_SHEET_ID = "10g3nQNNUkWDSpcG9dAELjGDxOpI_oOlo7_68gU_9hTA"
WORKSHEET_PRICELIST = "Sheet 2"   # Branch-level Pricelist Master Data (Long Format)
WORKSHEET_INVOICE = "Sheet 3"     # Invoice Weight / Delivery Method

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

receivers_raw = os.getenv("mkitchen_email", "")
RECEIVER_EMAILS = [email.strip() for email in receivers_raw.split(",") if email.strip()]

cc_receivers_raw = os.getenv("testing_cc", "")
CC_EMAILS = [email.strip() for email in cc_receivers_raw.split(",") if email.strip()]


# ==========================================
# HELPER: MONEY FORMATTER (MILLIONS)
# ==========================================
def fmt_m(val: float) -> str:
    if pd.isna(val) or val == 0:
        return "0.00M"
    return f"{val / 1_000_000:,.2f}M"


# ==========================================
# HELPER: ALERT DISTRIBUTION CHART
# ==========================================
def generate_alert_chart(alert_counts: pd.Series) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7, 4), dpi=100)
    issues = alert_counts[alert_counts.index != 'No alert']

    if issues.empty:
        ax.text(0.5, 0.5, '✅ All SKUs Healthy!\nNo Price Alerts Found.',
                ha='center', va='center', fontsize=14, color='#38A169', fontweight='bold')
        ax.axis('off')
    else:
        colors = ['#E53E3E', '#DD6B20', '#D69E2E', '#3182CE', '#805AD5']
        bars = ax.barh(issues.index.tolist(), issues.tolist(), color=colors[:len(issues)], edgecolor='none')
        ax.set_title('M-Kitchen SKU Price Alerts Distribution (Unique SKUs)', fontsize=12, fontweight='bold', color='#2D3748', pad=15)
        ax.invert_yaxis()
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        for bar in bars:
            width = bar.get_width()
            ax.text(width + 1, bar.get_y() + bar.get_height()/2, f'{int(width)} SKUs',
                    va='center', ha='left', fontsize=10, fontweight='bold', color='#4A5568')

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight')
    img_buf.seek(0)
    plt.close(fig)
    return img_buf


# ==========================================
# HELPER: GOOGLE SHEET SYNC
# ==========================================
def sync_df_to_worksheet(spreadsheet, worksheet_name: str, df: pd.DataFrame):
    if df.empty:
        print(f"⚠️ DataFrame is empty. Skipping sync for '{worksheet_name}'.")
        return False

    try:
        sheet = spreadsheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"⚠️ Worksheet '{worksheet_name}' not found. Creating it automatically...")
        sheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1, cols=len(df.columns))

    sheet.clear()
    if len(df.columns) > sheet.col_count:
        sheet.resize(rows=1, cols=len(df.columns))

    data_to_write = [df.columns.values.tolist()] + df.values.tolist()
    sheet.update(data_to_write, 'A1')
    print(f"🎉 Worksheet '{worksheet_name}' successfully updated ({len(df):,} rows).")
    return True


# ==========================================
# SQL 1: BRANCH-LEVEL PRICELIST RAW DATA
# ==========================================
# NOTE: DAS schema does not have a 'price_list_branches' mapping table. 
# Price lists are applied at the Business/Customer level. We use the 
# Price List Name (pl.name) as the 'branch_name', assuming you have 
# created distinct Price Lists for each branch (e.g., "Branch A", "Branch B").
PRICELIST_BRANCH_SQL = """
WITH master_data AS (
    SELECT
        p.is_active AS active, p.id,
        CASE
            WHEN p.is_expiry_date_tracking = 1 AND (p.shelf_life_days < 30 OR p.shelf_life_days IS NULL) THEN 'Confirm shelf life'
            WHEN p.brand_name IS NULL OR TRIM(p.brand_name) = '' THEN 'Confirm brand name'
            WHEN p.is_batch_tracking = 0 AND COALESCE(parent_c.name, '') <> 'Containers' AND bom.main_product_id IS NULL THEN 'No batch tracking'
            WHEN p.is_expiry_date_tracking = 0 AND c.name = 'Perishable' THEN 'No expiry date tracking'
            ELSE 'OK'
        END AS masterdata_alert,
        p.sku, p.name, p.weight, p.brand_name,
        COALESCE(grandparent_c.name, 'NA') AS category_l1,
        COALESCE(parent_c.name, 'NA') AS category_l2,
        c.name AS category_l3,
        p.description, p.is_purchasable,
        COALESCE(p.purchased_sku, p.sku) AS purchased_sku,
        CASE
            WHEN bom.main_product_id IS NOT NULL THEN 'Kit'
            WHEN p_mtrading.name IS NOT NULL THEN 'M-Trading'
            WHEN p_repacking.name IS NOT NULL THEN 'Repacking'
            ELSE 'M-Kitchen'
        END AS source,
        CASE
            WHEN p_mtrading.name IS NOT NULL THEN p_mtrading.name
            WHEN p_repacking.name IS NOT NULL THEN p_repacking.name
            ELSE 'NA'
        END AS purchased_sku_name,
        pa.name AS purchase_account_name, p.is_sellable, sa.name AS sales_account_name,
        p.is_batch_tracking, p.is_expiry_date_tracking, p.shelf_life_days,
        ia.name AS inventory_account_name, p.purchase_price, p.sales_price
    FROM products AS p
    LEFT JOIN product_categories AS c ON p.category_id = c.id
    LEFT JOIN product_categories AS parent_c ON c.parent_category_id = parent_c.id
    LEFT JOIN product_categories AS grandparent_c ON parent_c.parent_category_id = grandparent_c.id
    LEFT JOIN accounts AS pa ON p.purchase_account_id = pa.id
    LEFT JOIN accounts AS sa ON p.sales_account_id = sa.id
    LEFT JOIN accounts AS ia ON p.inventory_account_id = ia.id
    LEFT JOIN (SELECT DISTINCT main_product_id FROM bill_of_materials WHERE bom_type = 'Kit' AND is_active = 1) AS bom ON p.id = bom.main_product_id
    LEFT JOIN products AS p_mtrading ON p.purchased_sku = p_mtrading.sku AND p_mtrading.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642'
    LEFT JOIN products AS p_repacking ON p.purchased_sku = p_repacking.sku AND p_repacking.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
    WHERE p.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND p.is_active = 1 AND p.nature = 'G' AND (p.is_sellable = 1 OR p.is_purchasable = 1)
),
purchased_info AS (
    SELECT sku, weight AS purchased_sku_weight, purchase_price, purchased_sku AS supplier_sku
    FROM products
    WHERE business_id IN ('84093770-29ad-4e8e-9da1-babe583c0d69', '7ef7c6c0-b59d-4be9-960c-7fa573038642')
),
last_po AS (
    SELECT pp.sku AS purchased_sku, t.last_po_unit_rate
    FROM (
        SELECT pod.product_id, po.business_id, pod.detail_unit_rate AS last_po_unit_rate,
               ROW_NUMBER() OVER (PARTITION BY pod.product_id ORDER BY po.order_date DESC, po.id DESC) AS rn
        FROM purchase_order_details pod
        JOIN purchase_orders po ON po.id = pod.purchase_order_id
        WHERE po.business_id IN ('84093770-29ad-4e8e-9da1-babe583c0d69', '7ef7c6c0-b59d-4be9-960c-7fa573038642')
          AND po.current_status IN ('Confirmed','Partially Billed','Closed','Partially Closed')
    ) t
    JOIN products pp ON pp.id = t.product_id AND pp.business_id = t.business_id
    WHERE t.rn = 1
),
pricelist_base AS (
    SELECT md.*, pi.supplier_sku, pi.purchased_sku_weight,
        CASE WHEN pi.purchased_sku_weight > 0 THEN md.weight / pi.purchased_sku_weight ELSE 1 END AS purchased_conversion_rate,
        pi.purchase_price * (md.weight / NULLIF(pi.purchased_sku_weight, 0)) AS purchasing_price,
        lp.last_po_unit_rate * (md.weight / NULLIF(pi.purchased_sku_weight, 0)) AS last_po_price,
        pi.purchase_price * (md.weight / NULLIF(pi.purchased_sku_weight, 0)) AS final_purchasing_price,
        COALESCE(pi.purchase_price * (md.weight / NULLIF(pi.purchased_sku_weight, 0)), 0) AS total_cost,
        CASE
            WHEN md.is_purchasable = 1 AND pi.purchase_price IS NULL THEN 'No purchasing price'
            WHEN lp.last_po_unit_rate IS NULL THEN 'No PO price known'
            WHEN lp.last_po_unit_rate > pi.purchase_price THEN 'Purchasing price increased'
            ELSE 'No alert'
        END AS price_alert
    FROM master_data md
    LEFT JOIN purchased_info pi ON md.purchased_sku = pi.sku
    LEFT JOIN last_po lp ON md.purchased_sku = lp.purchased_sku
)
SELECT 
    b.sku,
    b.name AS product_name,
    b.category_l1, b.category_l2, b.category_l3,
    b.weight AS product_weight,
    ROUND(b.total_cost, 2) AS total_cost,
    pl.name AS branch_name,
    ROUND(pli.unit_price, 2) AS branch_price,
    b.price_alert, b.masterdata_alert, b.source
FROM pricelist_base b
JOIN price_list_rule_items pli ON b.id = pli.product_id AND pli.is_active = 1 AND pli.apply_type = 'P'
JOIN price_lists pl ON pl.id = pli.price_list_id AND pl.is_active = 1
WHERE pl.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
ORDER BY pl.name ASC, b.category_l3 ASC, b.weight ASC, b.name ASC;
"""

# ==========================================
# SQL 2: INVOICE WEIGHT / DELIVERY METHOD
# ==========================================
INVOICE_WEIGHT_SQL = """
SELECT 
    inv.order_number,
    inv.invoice_number,
    DATE_FORMAT(inv.created_at, '%M-%y') AS InvoiceMonth,
    inv.created_at,
    devm.name AS DeliveryMethod,
    SUM(sod.detail_qty) AS TotalQty,
    SUM(sod.detail_qty * p.weight) AS InvoiceTotalWeight
FROM sales_invoices AS inv
LEFT JOIN sales_orders AS so ON inv.sales_order_id = so.id
LEFT JOIN delivery_methods AS devm ON devm.id = so.delivery_method_id
LEFT JOIN sales_order_details AS sod ON so.id = sod.sales_order_id
LEFT JOIN products AS p ON sod.product_id = p.id
WHERE inv.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
GROUP BY 
    inv.invoice_number, 
    inv.order_number, 
    InvoiceMonth, 
    inv.created_at, 
    DeliveryMethod;
"""


# ==========================================
# HELPER: COMBINED AUDIT EMAIL
# ==========================================
def send_audit_report(
    df: pd.DataFrame,
    df_inv: pd.DataFrame,
    csv_paths: list,
    sender: str,
    password: str,
    receivers: list,
    cc_receivers: Optional[list] = None
):
    if df.empty and (df_inv is None or df_inv.empty):
        print("⚠️ Both DataFrames are empty. Skipping email generation.")
        return

    if cc_receivers is None:
        cc_receivers = []

    extracted_at = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Pricelist KPIs (Adjusted for Long Format)
    total_unique_skus = df['sku'].nunique() if not df.empty else 0
    total_branch_records = len(df)
    
    if not df.empty:
        skus_with_alerts = df[df['price_alert'] != 'No alert']['sku'].nunique()
        alert_counts = df[df['price_alert'] != 'No alert'].groupby('price_alert')['sku'].nunique()
    else:
        skus_with_alerts = 0
        alert_counts = pd.Series(dtype=int)
        
    chart_buffer = generate_alert_chart(alert_counts) if not df.empty else None

    # Invoice Weight KPIs
    html_delivery_section = ""
    total_invoices = 0
    total_weight = 0.0
    total_qty = 0.0

    if df_inv is not None and not df_inv.empty:
        dfi = df_inv.copy()
        dfi['TotalQty'] = pd.to_numeric(dfi['TotalQty'], errors='coerce').fillna(0)
        dfi['InvoiceTotalWeight'] = pd.to_numeric(dfi['InvoiceTotalWeight'], errors='coerce').fillna(0)
        dfi['DeliveryMethod'] = dfi['DeliveryMethod'].replace('', 'No Delivery Method').fillna('No Delivery Method')

        total_invoices = dfi['invoice_number'].nunique()
        total_weight = dfi['InvoiceTotalWeight'].sum()
        total_qty = dfi['TotalQty'].sum()

        dm_df = dfi.groupby('DeliveryMethod').agg(
            Invoices=('invoice_number', 'nunique'),
            Total_Qty=('TotalQty', 'sum'),
            Total_Weight=('InvoiceTotalWeight', 'sum')
        ).reset_index().sort_values('Total_Weight', ascending=False)
        dm_df['Total_Qty'] = dm_df['Total_Qty'].map('{:,.0f}'.format)
        dm_df['Total_Weight'] = dm_df['Total_Weight'].map('{:,.1f}'.format)
        html_dm_table = dm_df.to_html(index=False, border=1, classes='dataframe')

        html_delivery_section = f"""
        <h3 style="color: #2B6CB0; margin-top: 25px;">🚚 Delivery Method Weight Breakdown <span style="font-size: 12px; color: #718096;">(synced to Sheet 3)</span></h3>
        <table class="kpi-table" cellspacing="0" cellpadding="0">
          <tr>
            <td class="kpi-td" width="33%"><div class="kpi-title">Total Invoices</div><div class="kpi-value">{total_invoices:,}</div></td>
            <td class="kpi-td" width="33%"><div class="kpi-title">Total Qty</div><div class="kpi-value">{total_qty:,.0f}</div></td>
            <td class="kpi-td" width="34%"><div class="kpi-title">Total Weight</div><div class="kpi-value">{total_weight:,.1f}</div></td>
          </tr>
        </table>
        {html_dm_table}
        """

    msg = MIMEMultipart('related')
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)
    if cc_receivers:
        msg['Cc'] = ", ".join(cc_receivers)

    msg['Subject'] = f"[M-Kitchen BI Sync] Branch Price List (Sheet 2) & Invoice Weight (Sheet 3) — {extracted_at}"

    html_body = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #2D3748; line-height: 1.6; background-color: #ffffff; margin:0; padding:10px; }}
          .info-box {{ background-color: #EBF8FF; border-left: 4px solid #3182CE; padding: 10px 14px; font-size: 12px; color: #2B6CB0; margin-bottom: 20px; border-radius: 0 4px 4px 0; }}
          .kpi-table {{ width: 100%; border-collapse: separate; border-spacing: 10px; margin-bottom: 10px; table-layout: fixed; }}
          .kpi-td {{ background: #F7FAFC; border: 1px solid #E2E8F0; padding: 14px 16px; border-radius: 6px; vertical-align: top; box-sizing: border-box; }}
          .kpi-title {{ font-size: 11px; color: #718096; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px; margin-bottom: 6px; }}
          .kpi-value {{ font-size: 20px; color: #2B6CB0; font-weight: bold; line-height: 1.2; word-break: break-all; }}
          .kpi-value.alert {{ color: #E53E3E; }}
          table.dataframe {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; margin-bottom: 25px; }}
          table.dataframe th {{ background-color: #2B6CB0; color: white; padding: 10px; text-align: left; font-weight: 600; }}
          table.dataframe td {{ padding: 8px 10px; border: 1px solid #E2E8F0; }}
          table.dataframe tr:nth-child(even) {{ background-color: #F7FAFC; }}
        </style>
      </head>
      <body>
        <h2 style="color: #2B6CB0; border-bottom: 2px solid #2B6CB0; padding-bottom: 8px; margin-top: 0;">🏷️ M-Kitchen BI Sync — Branch Price List & Invoice Weight Audit</h2>

        <div class="info-box">
          <b>ℹ️ Pipeline Extraction Info:</b> Data extracted from <code>das-db</code> on <b>{extracted_at}</b>.<br/>
          <b>Sync Targets:</b> Branch Price List → <code>Sheet 2</code> ({total_branch_records:,} branch-SKU records) &nbsp;|&nbsp; Invoice Weight → <code>Sheet 3</code> ({total_invoices:,} invoices).
        </div>

        <table class="kpi-table" cellspacing="0" cellpadding="0">
          <tr>
            <td class="kpi-td" width="33%"><div class="kpi-title">Unique Active SKUs</div><div class="kpi-value">{total_unique_skus:,}</div></td>
            <td class="kpi-td" width="33%"><div class="kpi-title">SKUs with Alerts</div><div class="kpi-value alert">{skus_with_alerts:,}</div></td>
            <td class="kpi-td" width="34%"><div class="kpi-title">Total Branch Records</div><div class="kpi-value">{total_branch_records:,}</div></td>
          </tr>
        </table>

        <h3 style="color: #2B6CB0; margin-top: 25px;">📊 Price Alert Distribution <span style="font-size: 12px; color: #718096;">(Sheet 2)</span></h3>
        <div style="text-align: center; margin: 15px 0;">
            <img src="cid:alert_chart" style="max-width:100%; height:auto; border:1px solid #E2E8F0; border-radius: 5px;">
        </div>

        {html_delivery_section}

        <p style="font-size: 12px; color: #718096; margin-top: 20px;">* Both datasets are attached as CSV files below and synced to Google Sheets (Sheet 2 & Sheet 3).</p>
      </body>
    </html>
    """

    msg_alt = MIMEMultipart('alternative')
    msg_alt.attach(MIMEText(html_body, 'html'))
    msg.attach(msg_alt)

    if chart_buffer:
        img = MIMEImage(chart_buffer.read())
        img.add_header('Content-ID', '<alert_chart>')
        img.add_header('Content-Disposition', 'inline', filename='alert_chart.png')
        msg.attach(img)

    for path in csv_paths:
        if os.path.exists(path):
            with open(path, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(path)}")
            msg.attach(part)

    all_recipients = receivers + cc_receivers

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 Combined Audit Report sent to {len(receivers)} TO & {len(cc_receivers)} CC recipient(s)!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
print("🔄 Starting M-Kitchen Multi-Tab Branch ETL & Sync Pipeline...")

try:
    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4'
    )

    # Step 1a: Extract Branch-Level Price List (Long Format for BI SSOT)
    print("📖 Extracting Branch-Level Price List Data...")
    df_raw = pd.read_sql(PRICELIST_BRANCH_SQL, cast(Any, connection))
    df_raw = df_raw.fillna("")

    if not df_raw.empty:
        df_pricelist = df_raw.copy()
        
        # Ensure numeric types for calculation
        df_pricelist['branch_price'] = pd.to_numeric(df_pricelist['branch_price'], errors='coerce').fillna(0)
        df_pricelist['total_cost'] = pd.to_numeric(df_pricelist['total_cost'], errors='coerce').fillna(0)
        
        # Calculate Margin % directly at the branch-SKU level
        df_pricelist['margin_percent'] = df_pricelist.apply(
            lambda row: round((row['branch_price'] - row['total_cost']) / row['branch_price'], 4) if row['branch_price'] > 0 else 0, 
            axis=1
        )
        
        # Define optimal column order for BI consumption and human readability
        col_order = [
            'branch_name', 'sku', 'product_name', 'source', 
            'category_l1', 'category_l2', 'category_l3', 
            'product_weight', 'total_cost', 'branch_price', 'margin_percent',
            'price_alert', 'masterdata_alert'
        ]
        
        # Ensure all columns exist before reordering (safety check)
        for col in col_order:
            if col not in df_pricelist.columns:
                df_pricelist[col] = ""
                
        df_pricelist = df_pricelist[col_order]
        
        # Sort logically: Branch -> Category -> SKU for easier human reading and BI grouping
        df_pricelist = df_pricelist.sort_values(
            by=['branch_name', 'category_l1', 'category_l2', 'category_l3', 'sku']
        ).reset_index(drop=True)
        
    else:
        df_pricelist = pd.DataFrame()

    print(f"✅ Branch Price List: {len(df_pricelist):,} branch-SKU records processed.")

    # Step 1b: Extract Invoice Weight
    print("📖 Extracting Invoice Weight / Delivery Method data...")
    df_invoice = pd.read_sql(INVOICE_WEIGHT_SQL, cast(Any, connection))
    connection.close()

    df_invoice = df_invoice.fillna("")
    for col in df_invoice.columns:
        if pd.api.types.is_datetime64_any_dtype(df_invoice[col]):
            df_invoice[col] = df_invoice[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            df_invoice[col] = df_invoice[col].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
    print(f"✅ Invoice Weight: {len(df_invoice):,} records.")

    # Step 2: Google Sheets Sync
    print("🔑 Authenticating Service Account...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

    print(f"🧹 Syncing Branch Price List → '{WORKSHEET_PRICELIST}'...")
    sync_df_to_worksheet(spreadsheet, WORKSHEET_PRICELIST, df_pricelist)

    print(f"🧹 Syncing Invoice Weight → '{WORKSHEET_INVOICE}'...")
    sync_df_to_worksheet(spreadsheet, WORKSHEET_INVOICE, df_invoice)

    # Step 3: Export CSVs & Send Email
    df_pricelist.to_csv(CSV_PRICELIST_PATH, index=False, encoding='utf-8-sig')
    df_invoice.to_csv(CSV_INVOICE_PATH, index=False, encoding='utf-8-sig')

    print("🚀 Triggering Combined Audit Email...")
    send_audit_report(
        df=df_pricelist,
        df_inv=df_invoice,
        csv_paths=[CSV_PRICELIST_PATH, CSV_INVOICE_PATH],
        sender=SENDER_EMAIL,
        password=SENDER_PASSWORD,
        receivers=RECEIVER_EMAILS,
        cc_receivers=CC_EMAILS
    )

    print("🏁 Multi-Tab Branch Pipeline Executed Successfully from Start to End!")

except Exception as e:
    print(f"❌ Pipeline Execution Error: {repr(e)}")