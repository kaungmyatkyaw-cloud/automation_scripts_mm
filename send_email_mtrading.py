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
from typing import Optional

import gspread
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
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
JSON_KEYFILE = os.path.join(CURRENT_DIR, "mysql-to-sheet-502710-a1c9868da055.json")
CSV_FILE_PATH = os.path.join(CURRENT_DIR, "mtrading_sales_report.csv")

# MySQL Configuration
DB_HOST = os.getenv("BI_DB_HOST", "")
DB_PORT = int(os.getenv("BI_DB_PORT", 25060))
DB_USER = os.getenv("BI_DB_USER", "kmkyaw")
DB_PASS = os.getenv("BI_DB_PASS", "")
DB_NAME = os.getenv("BI_DB_NAME", "bi_database")

# Google Sheet Configuration (M-Trading Sheet ID)
GOOGLE_SHEET_ID = "1VRTScAR1Rec_toXUpqEJE6-5_IIvVCOUCtA-0fesw9I"
WORKSHEET_NAME = "Sheet1"

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

# TO Recipients
receivers_raw = os.getenv("mtrading_email", "")
RECEIVER_EMAILS = [email.strip() for email in receivers_raw.split(",") if email.strip()]

# CC Recipients
cc_receivers_raw = os.getenv("cccccc", "")
CC_EMAILS = [email.strip() for email in cc_receivers_raw.split(",") if email.strip()]


# ==========================================
# HELPER FUNCTION: MONEY FORMATTER (MILLIONS)
# ==========================================
def fmt_m(val: float) -> str:
    """Converts a float amount into 'M' format without '$' sign. E.g., 1,500,000 -> '1.50M'"""
    if pd.isna(val) or val == 0:
        return "0.00M"
    return f"{val / 1_000_000:,.2f}M"


# ==========================================
# HELPER FUNCTION: CHART GENERATOR
# ==========================================
def generate_branch_chart(branch_df: pd.DataFrame) -> io.BytesIO:
    """Branch revenue chart ထုတ်ယူပေးသော function ('M' Format အသုံးပြုထားသည်)"""
    num_branches = len(branch_df)
    fig_height = max(3.5, num_branches * 0.45)
    
    fig, ax = plt.subplots(figsize=(7, fig_height), dpi=100)
    
    branches = branch_df['branch_name'].tolist()[::-1]
    revenues = branch_df['Revenue_Raw'].tolist()[::-1]
    
    bars = ax.barh(branches, revenues, color='#1A365D', edgecolor='none')
    
    ax.set_title('M-Trading Revenue by Branch in Millions (Last 7 Days)', fontsize=11, fontweight='bold', pad=12, color='#1A365D')
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, loc: f"{x/1e6:,.1f}M"))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E0')
    ax.spines['bottom'].set_color('#CBD5E0')
    ax.grid(axis='x', linestyle='--', alpha=0.5)
    
    for bar in bars:
        width = bar.get_width()
        ax.text(width, bar.get_y() + bar.get_height()/2, f' {fmt_m(width)}', 
                va='center', ha='left', fontsize=9, fontweight='bold', color='#1A365D')

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight')
    img_buf.seek(0)
    plt.close(fig)
    return img_buf


# ==========================================
# HELPER FUNCTION: EMAIL & REPORT GENERATOR
# ==========================================
def send_summary_report(
    df: pd.DataFrame, 
    csv_path: str, 
    sender: str, 
    password: str, 
    receivers: list, 
    cc_receivers: Optional[list] = None
):
    if df.empty:
        print("⚠️ DataFrame is empty. Skipping email generation.")
        return

    cc_list = cc_receivers if cc_receivers is not None else []

    # Numeric Columns မဖြစ်မနေ ပြောင်းလဲခြင်း
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
    df['net_amount'] = pd.to_numeric(df['net_amount'], errors='coerce').fillna(0)
    df['cogs_amount'] = pd.to_numeric(df['cogs_amount'], errors='coerce').fillna(0)
    df['gross_profit'] = pd.to_numeric(df['gross_profit'], errors='coerce').fillna(0)

    # Date Column Fallback (Handles both sale_date and sale_datetime)
    date_col = 'sale_date' if 'sale_date' in df.columns else 'sale_datetime'
    min_date = pd.to_datetime(df[date_col]).min().strftime('%d-%b-%Y')
    max_date = pd.to_datetime(df[date_col]).max().strftime('%d-%b-%Y')
    extracted_at = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Transaction Column Fallback
    trans_col = 'transaction_number' if 'transaction_number' in df.columns else 'invoice_number'

    # Executive KPIs တွက်ချက်ခြင်း
    total_sales_value = df['net_amount'].sum()
    total_cogs = df['cogs_amount'].sum()
    total_profit = df['gross_profit'].sum()
    total_qty_sold = df['quantity'].sum()
    overall_margin_pct = (total_profit / total_sales_value * 100) if total_sales_value > 0 else 0
    total_orders = df[trans_col].nunique()
    avg_order_value = (total_sales_value / total_orders) if total_orders > 0 else 0

    # Top 5 Revenue Products Preview Table & Insight
    prod_sku_col = 'product_sku' if 'product_sku' in df.columns else 'master_sku'
    prod_name_col = 'product_name' if 'product_name' in df.columns else 'master_product_name'

    top_products_df = df.groupby([prod_sku_col, prod_name_col]).agg(
        Total_Qty=('quantity', 'sum'),
        Total_Revenue=('net_amount', 'sum'),
        Total_Profit=('gross_profit', 'sum')
    ).reset_index().sort_values(by='Total_Revenue', ascending=False)

    best_seller_name = top_products_df.iloc[0][prod_name_col] if not top_products_df.empty else "N/A"
    best_seller_rev = top_products_df.iloc[0]['Total_Revenue'] if not top_products_df.empty else 0
    best_seller_pct = (best_seller_rev / total_sales_value * 100) if total_sales_value > 0 else 0

    top_5_display = top_products_df.head(5).copy()
    top_5_display['Total_Qty'] = top_5_display['Total_Qty'].map('{:,.0f} Pcs'.format)
    top_5_display['Total_Revenue'] = top_5_display['Total_Revenue'].apply(fmt_m)
    top_5_display['Total_Profit'] = top_5_display['Total_Profit'].apply(fmt_m)

    html_top_products = top_5_display.to_html(index=False, border=1, classes='dataframe')

    # Branch Performance Breakdown
    has_branch = 'branch_name' in df.columns
    chart_buffer = None
    html_branch_perf = ""
    
    if has_branch and df['branch_name'].replace('', pd.NA).dropna().nunique() > 0:
        branch_perf_df = df[df['branch_name'] != ''].groupby('branch_name').agg(
            Orders=(trans_col, 'nunique'),
            Qty_Sold=('quantity', 'sum'),
            Revenue_Raw=('net_amount', 'sum'),
            Gross_Profit_Raw=('gross_profit', 'sum')
        ).reset_index().sort_values(by='Revenue_Raw', ascending=False)
        
        chart_buffer = generate_branch_chart(branch_perf_df)

        branch_perf_df['Revenue'] = branch_perf_df['Revenue_Raw'].apply(fmt_m)
        branch_perf_df['Gross_Profit'] = branch_perf_df['Gross_Profit_Raw'].apply(fmt_m)
        branch_perf_df['Qty_Sold'] = branch_perf_df['Qty_Sold'].map('{:,.0f} Pcs'.format)
        
        # Calculate Profit Margin % safely for each branch
        branch_perf_df['Margin_%'] = branch_perf_df.apply(
            lambda row: f"{(row['Gross_Profit_Raw'] / row['Revenue_Raw'] * 100):.2f}%" if row['Revenue_Raw'] > 0 else "0.00%", 
            axis=1
        )
        
        # Add Margin_% to the display table and rename headers
        display_branch_df = branch_perf_df[['branch_name', 'Orders', 'Qty_Sold', 'Revenue', 'Gross_Profit', 'Margin_%']]
        display_branch_df = display_branch_df.rename(columns={
            'branch_name': 'Branch',
            'Qty_Sold': 'Qty Sold',
            'Gross_Profit': 'Gross Profit',
            'Margin_%': 'Margin %'
        })
        
        html_branch_perf = f"""
        <h3 style="color: #1A365D; margin-top: 25px;">🏢 M-Trading Branch Performance Breakdown</h3>
        <div style="margin-top: 15px;"><img src="cid:branch_chart" style="max-width:100%; height:auto; border:1px solid #e2e8f0; border-radius: 5px;"></div>
        {display_branch_df.to_html(index=False, border=1, classes='dataframe')}
        """

    # Construct Email Object
    msg = MIMEMultipart('related')
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)
    if cc_list:
        msg['Cc'] = ", ".join(cc_list)

    msg['Subject'] = f"[M-Trading Automated Report] Executive Sales Performance ({min_date} to {max_date})"

    # Email HTML Body with Action Required Callout Box
    html_body = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #2D3748; line-height: 1.6; background-color: #ffffff; margin:0; padding:10px; }}
          .info-box {{ background-color: #EBF8FF; border-left: 4px solid #3182CE; padding: 10px 14px; font-size: 12px; color: #2B6CB0; margin-bottom: 20px; border-radius: 0 4px 4px 0; }}
          .insight-box {{ background-color: #FFFAF0; border: 1px solid #FEEBC8; border-left: 4px solid #DD6B20; padding: 14px; margin-bottom: 20px; border-radius: 4px; }}
          .insight-title {{ font-weight: bold; color: #C05621; font-size: 14px; margin-bottom: 8px; display: block; }}
          .insight-ul {{ margin: 0; padding-left: 18px; font-size: 13px; color: #4A5568; }}
          .insight-ul li {{ margin-bottom: 4px; }}
          
          /* Action Required Callout Box */
          .action-box {{ background-color: #EBF8FF; border: 1px solid #BEE3F8; border-left: 4px solid #3182CE; padding: 16px; margin-top: 25px; margin-bottom: 20px; border-radius: 4px; }}
          .action-title {{ font-weight: bold; color: #2B6CB0; font-size: 14px; margin-bottom: 8px; display: block; }}
          .action-ul {{ margin: 0; padding-left: 18px; font-size: 13px; color: #2D3748; }}
          .action-ul li {{ margin-bottom: 6px; }}

          .kpi-table {{ width: 100%; border-collapse: separate; border-spacing: 10px; margin-bottom: 10px; table-layout: fixed; }}
          .kpi-td {{ background: #F7FAFC; border: 1px solid #E2E8F0; padding: 14px 16px; border-radius: 6px; vertical-align: top; box-sizing: border-box; }}
          .kpi-title {{ font-size: 11px; color: #718096; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px; margin-bottom: 6px; }}
          .kpi-value {{ font-size: 20px; color: #1A365D; font-weight: bold; line-height: 1.2; word-break: break-all; }}
          table.dataframe {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; margin-bottom: 25px; }}
          table.dataframe th {{ background-color: #1A365D; color: white; padding: 10px; text-align: left; font-weight: 600; }}
          table.dataframe td {{ padding: 8px 10px; border: 1px solid #E2E8F0; }}
          table.dataframe tr:nth-child(even) {{ background-color: #F7FAFC; }}
          /* Highlight Margin % Column */
          table.dataframe th:last-child, table.dataframe td:last-child {{ text-align: center; font-weight: 700; color: #DD6B20; }}
        </style>
      </head>
      <body>
        <h2 style="color: #1A365D; border-bottom: 2px solid #1A365D; padding-bottom: 8px; margin-top: 0;">M-Trading Executive Sales Performance Summary</h2>
        
        <div class="info-box">
          <b>ℹ️ Pipeline Extraction Info:</b> Data extracted from <code>bi_database</code> on <b>{extracted_at}</b>.<br/>
          <b>Applied Logic:</b> Business ID (<code>M-Trading</code>) + Non-Branch 34 (mkitchen-ygn) (<code>84093770-...</code>) | Range: <b>{min_date}</b> to <b>{max_date}</b> | <b>{len(df):,} Total Rows</b>.
        </div>

        <div class="insight-box">
          <span class="insight-title">💡 Executive Insights & Key Takeaways</span>
          <ul class="insight-ul">
            <li><b>Top Product Performer:</b> <code>{best_seller_name}</code> is the highest revenue contributor at <b>{fmt_m(best_seller_rev)}</b> (~<b>{best_seller_pct:.1f}%</b> of overall sales).</li>
            <li><b>Profit Margin Status:</b> Overall gross profit margin stands at <b>{overall_margin_pct:.2f}%</b> generating <b>{fmt_m(total_profit)}</b> in gross profit.</li>
            <li><b>Order Value Baseline:</b> Generated <b>{total_orders:,} total orders</b> with an Average Order Value (AOV) of <b>{fmt_m(avg_order_value)}</b>.</li>
          </ul>
        </div>
        
        <table class="kpi-table" cellspacing="0" cellpadding="0">
          <tr>
            <td class="kpi-td" width="25%"><div class="kpi-title">Total Revenue</div><div class="kpi-value">{fmt_m(total_sales_value)}</div></td>
            <td class="kpi-td" width="25%"><div class="kpi-title">Gross Profit</div><div class="kpi-value">{fmt_m(total_profit)}</div></td>
            <td class="kpi-td" width="25%"><div class="kpi-title">Profit Margin</div><div class="kpi-value">{overall_margin_pct:.2f}%</div></td>
            <td class="kpi-td" width="25%"><div class="kpi-title">Total Orders</div><div class="kpi-value">{total_orders:,}</div></td>
          </tr>
        </table>

        <table class="kpi-table" cellspacing="0" cellpadding="0">
          <tr>
            <td class="kpi-td" width="33%"><div class="kpi-title">Total Qty Sold</div><div class="kpi-value">{total_qty_sold:,.0f} Pcs</div></td>
            <td class="kpi-td" width="33%"><div class="kpi-title">Total COGS</div><div class="kpi-value">{fmt_m(total_cogs)}</div></td>
            <td class="kpi-td" width="34%"><div class="kpi-title">Avg Order Value</div><div class="kpi-value">{fmt_m(avg_order_value)}</div></td>
          </tr>
        </table>

        {html_branch_perf}

        <h3 style="color: #1A365D; margin-top: 25px;">🔥 Top 5 Revenue Contributing Products</h3>
        {html_top_products}

        <!-- 🎯 Action Required / HOD Follow-up Reply Section -->
        <div class="action-box">
          <span class="action-title">📌 Action Required: Post-HOD Meeting Updates (9-15-2026)</span>
          <p style="font-size: 13px; margin: 0 0 8px 0;">Regarding the issues and matters of this report, please share your updates by replying to this email so that we can keep track of progress accordingly, as decided during the <b>9-15-2026 HOD meeting</b>:</p>
          <ul class="action-ul">
            <li><b>Action Plans:</b> Action plans to be carried out during the coming week.</li>
            <li><b>In-Progress Tasks:</b> Issues or tasks that are currently in progress.</li>
            <li><b>Status Updates:</b> Improvement updates and the status of completed actions.</li>
          </ul>
          <p style="font-size: 12px; color: #4A5568; margin-top: 10px; font-style: italic;">* Please reply to all recipients to ensure cross-departmental alignment.</p>
        </div>

        <p style="font-size: 12px; color: #718096; margin-top: 20px;">* Full raw dataset ({len(df):,} rows) is attached as a CSV file below.</p>
      </body>
    </html>
    """
    
    msg_alt = MIMEMultipart('alternative')
    msg_alt.attach(MIMEText(html_body, 'html'))
    msg.attach(msg_alt)

    # Embedded Image
    if chart_buffer:
        img = MIMEImage(chart_buffer.read())
        img.add_header('Content-ID', '<branch_chart>')
        img.add_header('Content-Disposition', 'inline', filename='branch_chart.png')
        msg.attach(img)

    # Attach CSV File
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if os.path.exists(csv_path):
        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_path)}")
        msg.attach(part)

    # Combine TO & CC recipients for SMTP Target
    all_recipients = receivers + cc_list

    # SMTP Send Email
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 M-Trading Automated Report sent successfully to {len(receivers)} TO recipient(s) & {len(cc_list)} CC recipient(s)!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
print("🔄 Starting M-Trading ETL, Sync, and Automated Reporting Pipeline...")

try:
    # --------------------------------------------------
    # Step 1: MySQL Extraction (M-Trading Consolidated Logic)
    # --------------------------------------------------
    print("📖 Extracting last 7 days data from MySQL using M-Trading Logic...")
    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4'
    )
    
    sql_query = """
        SELECT * 
        FROM fact_saless
        WHERE (
            (business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(branch_id AS CHAR)) != '34' OR branch_id IS NULL))
            OR 
            (business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
        )
        AND sale_datetime >= TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 7 DAY), '00:00:00')
        AND sale_datetime <= TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 1 DAY), '23:59:59');
    """
    
    df = pd.read_sql(sql_query, connection)  # type: ignore
    connection.close()
    
    df = df.fillna("")
    
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            df[col] = df[col].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)

    total_rows = len(df)
    print(f"✅ Extracted {total_rows:,} records from Database for M-Trading.")

    # --------------------------------------------------
    # Step 2: Sync to Google Sheet
    # --------------------------------------------------
    print("🔑 Authenticating Service Account for M-Trading Google Sheet...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(WORKSHEET_NAME)

    print("🧹 Cleaning existing data & syncing new dataset...")
    sheet.clear()
    sheet.resize(rows=1, cols=len(df.columns))
    
    data_to_write = [df.columns.values.tolist()] + df.values.tolist()
    sheet.update(data_to_write, 'A1')
    print("🎉 M-Trading Google Sheet successfully updated!")

    # --------------------------------------------------
    # Step 3: Send Email with CC, Insights & CSV Attachment
    # --------------------------------------------------
    print("🚀 Triggering Automated Email Report...")
    send_summary_report(
        df=df,
        csv_path=CSV_FILE_PATH,
        sender=SENDER_EMAIL,
        password=SENDER_PASSWORD,
        receivers=RECEIVER_EMAILS,
        cc_receivers=CC_EMAILS
    )

    print("🏁 M-Trading Pipeline Executed Successfully from Start to End!")

except Exception as e:
    print(f"❌ Pipeline Execution Error: {repr(e)}")