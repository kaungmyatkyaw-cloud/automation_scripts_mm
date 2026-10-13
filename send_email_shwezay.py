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
JSON_KEYFILE = os.path.join(CURRENT_DIR, "service_account_update.json")
CSV_FILE_PATH = os.path.join(CURRENT_DIR, "shwezay_consolidated_sales_report.csv")

# MySQL Configuration
DB_HOST = os.getenv("BI_DB_HOST", "")
DB_PORT = int(os.getenv("BI_DB_PORT", 25060))
DB_USER = os.getenv("BI_DB_USER", "kmkyaw")
DB_PASS = os.getenv("BI_DB_PASS", "")
DB_NAME = os.getenv("BI_DB_NAME", "bi_database")

# Google Sheet Configuration (ShweZay Target Sheet)
GOOGLE_SHEET_ID = "1SzDhjZUFwb4RnLdqmOengU8CMRxj2ksxEJotPpq3zfs"

# Multi-Branch Mapping Configuration
BRANCH_CONFIG = {
    "ygn": "ac4dd67c-738e-4dfe-a475-fc65f2a9ca08",
    "npt": "2d393763-d5c7-42be-b345-84b7be787f10",
    "kpg": "1eb52cc2-7a34-43d8-b646-67cc60402916"
}

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

# TO Recipients
receivers_raw = os.getenv("shwezay_email", "")
RECEIVER_EMAILS = [email.strip() for email in receivers_raw.split(",") if email.strip()]

# CC Recipients
cc_receivers_raw = os.getenv("cccccc", "")
CC_EMAILS = [email.strip() for email in cc_receivers_raw.split(",") if email.strip()]

# BRAND COLOR PALETTE
COLOR_PRIMARY = "#004b87"
COLOR_ACCENT = "#ff6b00"
COLOR_TEXT_MAIN = "#1e293b"
COLOR_TEXT_MUTED = "#64748b"
COLOR_BG_CARD = "#f8fafc"
COLOR_BORDER = "#e2e8f0"


# ==========================================
# HELPER FUNCTION: MONEY FORMATTER (MILLIONS)
# ==========================================
def fmt_m(val: float) -> str:
    """Converts a float amount into 'M' format. E.g., 1,500,000 -> '1.50M'"""
    if pd.isna(val) or val == 0:
        return "0.00M"
    return f"{val / 1_000_000:,.2f}M"


# ==========================================
# HELPER FUNCTION: ENHANCED CHART GENERATOR
# ==========================================
def generate_branch_chart(branch_df: pd.DataFrame) -> io.BytesIO:
    """ShweZay Brand Enhanced Branch Revenue Chart"""
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=120)
    
    # Chart Colors & Setup
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#ffffff')

    branches = branch_df['branch_name'].tolist()[::-1]
    revenues = branch_df['Revenue_Raw'].tolist()[::-1]
    
    bars = ax.barh(branches, revenues, color=COLOR_PRIMARY, height=0.55, edgecolor='none')
    
    ax.set_title('Consolidated Revenue by Branch (MMK Millions)', fontsize=11, fontweight='bold', pad=14, color=COLOR_PRIMARY)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, loc: f"{x/1e6:,.1f}M"))
    
    # Hide outer frame
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.grid(axis='x', linestyle=':', alpha=0.6, color='#cbd5e1')
    ax.tick_params(axis='both', which='both', length=0, labelsize=9.5, labelcolor=COLOR_TEXT_MAIN)
    
    # Value Labels on Bars
    max_rev = max(revenues) if revenues else 1
    for bar in bars:
        width = bar.get_width()
        ax.text(
            width + (max_rev * 0.015), 
            bar.get_y() + bar.get_height()/2, 
            f'{fmt_m(width)}', 
            va='center', 
            ha='left', 
            fontsize=9, 
            fontweight='bold', 
            color=COLOR_PRIMARY
        )

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
    img_buf.seek(0)
    plt.close(fig)
    return img_buf


# ==========================================
# HELPER FUNCTION: CONSOLIDATED REPORT EMAIL
# ==========================================
def send_consolidated_report(
    df: pd.DataFrame, 
    csv_path: str, 
    sender: str, 
    password: str, 
    receivers: list, 
    cc_receivers: Optional[list] = None
):
    if df.empty:
        print("⚠️ Consolidated DataFrame is empty. Skipping email.")
        return

    cc_list = cc_receivers if cc_receivers is not None else []

    # Numeric Conversion
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
    df['net_amount'] = pd.to_numeric(df['net_amount'], errors='coerce').fillna(0)
    df['cogs_amount'] = pd.to_numeric(df['cogs_amount'], errors='coerce').fillna(0)
    df['gross_profit'] = pd.to_numeric(df['gross_profit'], errors='coerce').fillna(0)

    # Global Date Range & Timestamps
    min_date = pd.to_datetime(df['sale_date']).min().strftime('%d-%b-%Y')
    max_date = pd.to_datetime(df['sale_date']).max().strftime('%d-%b-%Y')
    extracted_at = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Consolidated KPIs
    total_sales_value = df['net_amount'].sum()
    total_cogs = df['cogs_amount'].sum()
    total_profit = df['gross_profit'].sum()
    total_qty_sold = df['quantity'].sum()
    overall_margin_pct = (total_profit / total_sales_value * 100) if total_sales_value > 0 else 0
    total_orders = df['transaction_number'].nunique()
    avg_order_value = (total_sales_value / total_orders) if total_orders > 0 else 0

    # Branch-wise Performance Breakdown & Chart
    branch_perf_df = df.groupby('branch_name').agg(
        Orders=('transaction_number', 'nunique'),
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
    
    html_branch_perf = display_branch_df.to_html(index=False, border=0, classes='styled-table')

    # Consolidated Top 5 Products & Best Seller Insight
    prod_sku_col = 'product_sku'
    prod_name_col = 'product_name'

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

    html_top_products = top_5_display.to_html(index=False, border=0, classes='styled-table')

    # Construct Email Object
    msg = MIMEMultipart('related')
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)
    if cc_list:
        msg['Cc'] = ", ".join(cc_list)

    msg['Subject'] = f"[ShweZay Automated Report] Consolidated Performance ({min_date} to {max_date})"

    # HTML Body Design - ShweZay Theme
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
            padding: 20px 10px;
          }}
          .container {{
            max-width: 720px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 8px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
          }}
          .header {{
            border-bottom: 3px solid #004b87;
            padding-bottom: 12px;
            margin-bottom: 20px;
          }}
          .header h2 {{
            color: #004b87;
            margin: 0;
            font-size: 20px;
            font-weight: 700;
          }}
          .info-box {{
            background-color: #f0f7ff;
            border-left: 4px solid #004b87;
            padding: 12px 16px;
            font-size: 13px;
            color: #1e40af;
            margin-bottom: 20px;
            border-radius: 0 6px 6px 0;
          }}
          .insight-box {{
            background-color: #fff7ed;
            border: 1px solid #ffedd5;
            border-left: 4px solid #ff6b00;
            padding: 14px 16px;
            margin-bottom: 24px;
            border-radius: 6px;
          }}
          .insight-title {{
            font-weight: 700;
            color: #c2410c;
            font-size: 14px;
            margin-bottom: 8px;
            display: block;
          }}
          .insight-ul {{
            margin: 0;
            padding-left: 18px;
            font-size: 13px;
            color: #475569;
          }}
          .insight-ul li {{
            margin-bottom: 4px;
          }}
          
          /* Action Required Callout Box (ShweZay Blue Accent) */
          .action-box {{
            background-color: #f0f7ff;
            border: 1px solid #bfdbfe;
            border-left: 4px solid #004b87;
            padding: 16px;
            margin-top: 28px;
            margin-bottom: 20px;
            border-radius: 6px;
          }}
          .action-title {{
            font-weight: 700;
            color: #004b87;
            font-size: 14px;
            margin-bottom: 8px;
            display: block;
          }}
          .action-ul {{
            margin: 0;
            padding-left: 18px;
            font-size: 13px;
            color: #334155;
          }}
          .action-ul li {{
            margin-bottom: 6px;
          }}

          .kpi-grid {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 8px;
            margin-bottom: 16px;
            table-layout: fixed;
          }}
          .kpi-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 12px 14px;
            border-radius: 6px;
            vertical-align: top;
          }}
          .kpi-title {{
            font-size: 10px;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
          }}
          .kpi-value {{
            font-size: 18px;
            color: #004b87;
            font-weight: 700;
            line-height: 1.2;
          }}
          .section-title {{
            color: #004b87;
            font-size: 15px;
            font-weight: 700;
            margin-top: 28px;
            margin-bottom: 12px;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 6px;
          }}
          table.styled-table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 10px;
            font-size: 12.5px;
            margin-bottom: 20px;
          }}
          table.styled-table th {{
            background-color: #004b87;
            color: #ffffff;
            padding: 9px 12px;
            text-align: left;
            font-weight: 600;
          }}
          table.styled-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid #e2e8f0;
            color: #334155;
          }}
          table.styled-table tr:nth-child(even) {{
            background-color: #f8fafc;
          }}
          .chart-container {{
            text-align: center;
            margin: 16px 0;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 8px;
            background-color: #ffffff;
          }}
          .footer-note {{
            font-size: 11px;
            color: #94a3b8;
            margin-top: 24px;
            border-top: 1px solid #f1f5f9;
            padding-top: 12px;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>ShweZay Executive Sales Performance Summary</h2>
          </div>
          
          <div class="info-box">
            <b>ℹ️ Multi-Branch Pipeline Info:</b> Consolidated from MySQL (<code>bi_database</code>) on <b>{extracted_at}</b>.<br/>
            <b>Synced Branches:</b> YGN, NPT, KPG &nbsp;|&nbsp; Date Range: <b>{min_date}</b> to <b>{max_date}</b> &nbsp;|&nbsp; <b>{len(df):,} Rows</b>
          </div>

          <div class="insight-box">
            <span class="insight-title">💡 Executive Takeaways</span>
            <ul class="insight-ul">
              <li><b>Top Product Performer:</b> <code>{best_seller_name}</code> generated <b>{fmt_m(best_seller_rev)}</b> (~<b>{best_seller_pct:.1f}%</b> of total revenue).</li>
              <li><b>Gross Margin Baseline:</b> Overall margin is <b>{overall_margin_pct:.2f}%</b> generating <b>{fmt_m(total_profit)}</b> gross profit.</li>
              <li><b>Order Volume:</b> Processed <b>{total_orders:,} orders</b> with an Average Order Value (AOV) of <b>{fmt_m(avg_order_value)}</b>.</li>
            </ul>
          </div>

          <!-- KPI Grid Row 1 -->
          <table class="kpi-grid" cellspacing="0" cellpadding="0">
            <tr>
              <td class="kpi-card" width="25%"><div class="kpi-title">Total Revenue</div><div class="kpi-value">{fmt_m(total_sales_value)}</div></td>
              <td class="kpi-card" width="25%"><div class="kpi-title">Gross Profit</div><div class="kpi-value">{fmt_m(total_profit)}</div></td>
              <td class="kpi-card" width="25%"><div class="kpi-title">Profit Margin</div><div class="kpi-value" style="color: #ff6b00;">{overall_margin_pct:.2f}%</div></td>
              <td class="kpi-card" width="25%"><div class="kpi-title">Total Orders</div><div class="kpi-value">{total_orders:,}</div></td>
            </tr>
          </table>

          <!-- KPI Grid Row 2 -->
          <table class="kpi-grid" cellspacing="0" cellpadding="0">
            <tr>
              <td class="kpi-card" width="33%"><div class="kpi-title">Total Qty Sold</div><div class="kpi-value">{total_qty_sold:,.0f} Pcs</div></td>
              <td class="kpi-card" width="33%"><div class="kpi-title">Total COGS</div><div class="kpi-value">{fmt_m(total_cogs)}</div></td>
              <td class="kpi-card" width="34%"><div class="kpi-title">Avg Order Value</div><div class="kpi-value">{fmt_m(avg_order_value)}</div></td>
            </tr>
          </table>

          <div class="section-title">🏢 Branch Performance Breakdown</div>
          <div class="chart-container">
            <img src="cid:branch_chart" style="max-width:100%; height:auto;" alt="Branch Performance Chart">
          </div>
          {html_branch_perf}

          <div class="section-title">🔥 Top 5 Revenue Contributing Products</div>
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
            <p style="font-size: 12px; color: #64748b; margin-top: 10px; font-style: italic;">* Please reply to all recipients to ensure cross-departmental alignment.</p>
          </div>

          <div class="footer-note">
            * Full consolidated dataset ({len(df):,} rows) across all branches is attached as a CSV file.
          </div>
        </div>
      </body>
    </html>
    """
    
    msg_alt = MIMEMultipart('alternative')
    msg_alt.attach(MIMEText(html_body, 'html'))
    msg.attach(msg_alt)

    # Embedded Branch Chart Image
    if chart_buffer:
        img = MIMEImage(chart_buffer.read())
        img.add_header('Content-ID', '<branch_chart>')
        img.add_header('Content-Disposition', 'inline', filename='branch_chart.png')
        msg.attach(img)

    # Attach Consolidated CSV
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if os.path.exists(csv_path):
        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_path)}")
        msg.attach(part)

    # Combined TO & CC for SMTP Target
    all_recipients = receivers + cc_list

    # SMTP Send Email
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 Consolidated Executive Report Email sent successfully to {len(receivers)} TO & {len(cc_list)} CC recipient(s)!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
print("🔄 Starting ShweZay Multi-Branch ETL & Sync Pipeline...")

try:
    # Google Sheet Auth Setup
    print("🔑 Authenticating Google Sheets Service Account...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

    # Database Connection
    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4'
    )

    all_branch_dfs = []

    # 🔄 Loop through branches for Extraction & Sheet Sync
    for sheet_name, b_id in BRANCH_CONFIG.items():
        print(f"\n🚀 Processing Branch: [{sheet_name.upper()}] (Business ID: {b_id})")
        
        sql_query = f"""
            SELECT * 
            FROM fact_saless
            WHERE business_id = '{b_id}'
              AND sale_datetime >= TIMESTAMP('2026-10-05', '00:00:00')
              AND sale_datetime <= TIMESTAMP('2026-10-11', '23:59:59');
        """
                
        branch_df = pd.read_sql(sql_query, connection)  # type: ignore
        
        if branch_df.empty:
            print(f"⚠️ No data found for Branch [{sheet_name.upper()}]. Skipping Sheet update.")
            continue
            
        branch_df = branch_df.fillna("")
        
        # Date & Timestamp Format Fixes
        for col in branch_df.columns:
            if pd.api.types.is_datetime64_any_dtype(branch_df[col]):
                branch_df[col] = branch_df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                branch_df[col] = branch_df[col].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)

        branch_df['branch_name'] = sheet_name.upper()
        all_branch_dfs.append(branch_df)
        print(f"✅ Extracted {len(branch_df):,} records for {sheet_name.upper()}.")

        # Sync to individual Google Sheet Tab
        print(f"🧹 Syncing to Google Worksheet: '{sheet_name}'...")
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1, cols=len(branch_df.columns))
            
        worksheet.clear()
        worksheet.resize(rows=1, cols=len(branch_df.columns))
        
        sheet_data_df = branch_df.drop(columns=['branch_name'])
        data_to_write = [sheet_data_df.columns.values.tolist()] + sheet_data_df.values.tolist()
        worksheet.update(data_to_write, 'A1')
        print(f"🎉 Worksheet '{sheet_name}' sync complete.")

    connection.close()

    # --------------------------------------------------
    # Step 3: Consolidated Data Combine & Send Email
    # --------------------------------------------------
    print("\n📦 Combining all branch data for Consolidated Analysis...")
    if all_branch_dfs:
        consolidated_df = pd.concat(all_branch_dfs, ignore_index=True)
        print(f"📊 Total Consolidated Records: {len(consolidated_df):,} rows.")
        
        print("🚀 Triggering Automated Consolidated Email Report...")
        send_consolidated_report(
            df=consolidated_df,
            csv_path=CSV_FILE_PATH,
            sender=SENDER_EMAIL,
            password=SENDER_PASSWORD,
            receivers=RECEIVER_EMAILS,
            cc_receivers=CC_EMAILS
        )
    else:
        print("⚠️ No branch data was available to consolidate.")

    print("\n🏁 Multi-branch Pipeline Executed Successfully from Start to End!")

except Exception as e:
    print(f"❌ Critical Pipeline Failure: {repr(e)}")