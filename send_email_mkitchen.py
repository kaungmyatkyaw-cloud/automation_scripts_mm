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
from matplotlib.patches import Circle
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
CSV_FILE_PATH = os.path.join(CURRENT_DIR, "mkitchen_sales_report.csv")

# MySQL Configuration
DB_HOST = os.getenv("BI_DB_HOST", "")
DB_PORT = int(os.getenv("BI_DB_PORT", 25060))
DB_USER = os.getenv("BI_DB_USER", "kmkyaw")
DB_PASS = os.getenv("BI_DB_PASS", "")
DB_NAME = os.getenv("BI_DB_NAME", "bi_database")

# Google Sheet Configuration (M-Kitchen Sheet ID)
GOOGLE_SHEET_ID = "10g3nQNNUkWDSpcG9dAELjGDxOpI_oOlo7_68gU_9hTA"
WORKSHEET_NAME = "Sheet1"

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

# TO Recipients
receivers_raw = os.getenv("mkitchen_email", "")
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
# HELPER FUNCTION: CHART GENERATOR (BRANCHES)
# ==========================================
def generate_branch_chart(branch_df: pd.DataFrame) -> io.BytesIO:
    """Branch revenue chart (M-Kitchen Warm Red Palette)"""
    num_branches = len(branch_df)
    fig_height = max(3.5, num_branches * 0.45)
    
    fig, ax = plt.subplots(figsize=(7, fig_height), dpi=100)
    
    branches = branch_df['branch_name'].tolist()[::-1]
    revenues = branch_df['Revenue_Raw'].tolist()[::-1]
    
    bars = ax.barh(branches, revenues, color='#C53030', edgecolor='none')
    
    ax.set_title('M-Kitchen Revenue by Branch in Millions (Last 7 Days)', fontsize=11, fontweight='bold', pad=12, color='#9B2C2C')
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, loc: f"{x/1e6:,.1f}M"))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#FEB2B2')
    ax.spines['bottom'].set_color('#FEB2B2')
    ax.grid(axis='x', linestyle='--', alpha=0.5)
    
    for bar in bars:
        width = bar.get_width()
        ax.text(width, bar.get_y() + bar.get_height()/2, f' {fmt_m(width)}', 
                va='center', ha='left', fontsize=9, fontweight='bold', color='#9B2C2C')

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight')
    img_buf.seek(0)
    plt.close(fig)
    return img_buf


# ==========================================
# HELPER FUNCTION: DONUT CHART GENERATOR (SALES CHAMPIONS - LIGHT THEME)
# ==========================================
def generate_sales_donut_chart(sp_df: pd.DataFrame) -> Optional[io.BytesIO]:
    """Generates a M-Kitchen Crimson themed Donut Chart for Top 5 Sales"""
    df = sp_df.head(5).copy()
    if df.empty:
        return None
        
    names = df['sales_person_name'].tolist()
    revenues = df['Revenue_Raw'].tolist()
    total_rev = sum(revenues)
    
    if total_rev == 0:
        return None
    
    base_colors = ['#C53030', '#E53E3E', '#F56565', '#FC8181', '#FEB2B2']
    colors = base_colors[:len(names)]
    
    fig, ax = plt.subplots(figsize=(5, 5), dpi=150)
    
    fig.patch.set_facecolor('#FFF5F5') 
    ax.set_facecolor('#FFF5F5')
    
    wedges, texts = ax.pie(
        revenues, 
        colors=colors, 
        startangle=90, 
        counterclock=False,
        wedgeprops=dict(width=0.4, edgecolor='#FFF5F5', linewidth=3),
        labels=['' for _ in names] 
    )
    
    plt.text(0, 0.1, 'Top 5 Total', ha='center', va='center', fontsize=11, color='#718096', fontweight='bold', fontfamily='sans-serif')
    plt.text(0, -0.15, fmt_m(total_rev), ha='center', va='center', fontsize=22, color='#C53030', fontweight='bold', fontfamily='sans-serif')
    
    centre_circle = Circle((0, 0), 0.60, fc='#FFF5F5', ec='none')
    fig.gca().add_artist(centre_circle)
    
    ax.margins(0, 0)
    
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight', facecolor='#FFF5F5', pad_inches=0.1)
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

    if cc_receivers is None:
        cc_receivers = []

    # Numeric Columns မဖြစ်မနေ ပြောင်းလဲခြင်း
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
    df['net_amount'] = pd.to_numeric(df['net_amount'], errors='coerce').fillna(0)
    df['cogs_amount'] = pd.to_numeric(df['cogs_amount'], errors='coerce').fillna(0)
    df['gross_profit'] = pd.to_numeric(df['gross_profit'], errors='coerce').fillna(0)

    # Date Range တွက်ချက်ခြင်း 
    date_col = 'sale_datetime' if 'sale_datetime' in df.columns else 'sale_date'
    min_date = pd.to_datetime(df[date_col]).min().strftime('%d-%b-%Y')
    max_date = pd.to_datetime(df[date_col]).max().strftime('%d-%b-%Y')
    extracted_at = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Executive KPIs တွက်ချက်ခြင်း
    total_sales_value = df['net_amount'].sum()
    total_cogs = df['cogs_amount'].sum()
    total_profit = df['gross_profit'].sum()
    total_qty_sold = df['quantity'].sum()
    overall_margin_pct = (total_profit / total_sales_value * 100) if total_sales_value > 0 else 0
    
    trans_col = 'transaction_number' if 'transaction_number' in df.columns else 'invoice_number'
    total_orders = df[trans_col].nunique()
    avg_order_value = (total_sales_value / total_orders) if total_orders > 0 else 0

    # --------------------------------------------------
    # PRODUCT PERFORMANCE CALCULATIONS (REVENUE & MARGIN %)
    # --------------------------------------------------
    prod_sku_col = 'product_sku' if 'product_sku' in df.columns else 'product_sku'
    prod_name_col = 'product_name' if 'product_name' in df.columns else 'product_name'

    # Group Products & Aggregate
    grouped_products_df = df.groupby([prod_sku_col, prod_name_col]).agg(
        Total_Qty=('quantity', 'sum'),
        Total_Revenue=('net_amount', 'sum'),
        Total_Profit=('gross_profit', 'sum')
    ).reset_index()

    # Calculate Gross Margin Percentage (Safe Division)
    grouped_products_df['Margin_Pct'] = grouped_products_df.apply(
        lambda r: (r['Total_Profit'] / r['Total_Revenue'] * 100) if r['Total_Revenue'] > 0 else 0,
        axis=1
    )

    # --- 1. TOP 5 PRODUCTS BY REVENUE ---
    top_products_df = grouped_products_df.sort_values(by='Total_Revenue', ascending=False)
    best_seller_name = top_products_df.iloc[0][prod_name_col] if not top_products_df.empty else "N/A"
    best_seller_rev = top_products_df.iloc[0]['Total_Revenue'] if not top_products_df.empty else 0
    best_seller_pct = (best_seller_rev / total_sales_value * 100) if total_sales_value > 0 else 0

    top_5_rev_display = top_products_df.head(5).copy()
    top_5_rev_display['Total_Qty'] = top_5_rev_display['Total_Qty'].map('{:,.0f} Pcs'.format)
    top_5_rev_display['Total_Revenue'] = top_5_rev_display['Total_Revenue'].apply(fmt_m)
    top_5_rev_display['Total_Profit'] = top_5_rev_display['Total_Profit'].apply(fmt_m)
    top_5_rev_display['Margin_Pct'] = top_5_rev_display['Margin_Pct'].map('{:.2f}%'.format)

    top_5_rev_display = top_5_rev_display.rename(columns={
        prod_sku_col: 'SKU',
        prod_name_col: 'Product Name',
        'Total_Qty': 'Qty Sold',
        'Total_Revenue': 'Revenue',
        'Total_Profit': 'Gross Profit',
        'Margin_Pct': 'Margin %'
    })[['SKU', 'Product Name', 'Qty Sold', 'Revenue', 'Gross Profit', 'Margin %']]

    html_top_products = top_5_rev_display.to_html(index=False, border=1, classes='dataframe')

    # --- 2. TOP 5 PRODUCTS BY MARGIN % (WITH MIN QTY FILTER) ---
    MIN_QTY_THRESHOLD = 5  # Filter out low-volume one-off outliers
    margin_filtered_df = grouped_products_df[grouped_products_df['Total_Qty'] >= MIN_QTY_THRESHOLD].copy()
    
    if margin_filtered_df.empty:
        margin_filtered_df = grouped_products_df.copy()

    top_margin_df = margin_filtered_df.sort_values(by='Margin_Pct', ascending=False).head(5).copy()
    top_margin_name = top_margin_df.iloc[0][prod_name_col] if not top_margin_df.empty else "N/A"
    top_margin_val = top_margin_df.iloc[0]['Margin_Pct'] if not top_margin_df.empty else 0

    top_margin_display = top_margin_df.copy()
    top_margin_display['Total_Qty'] = top_margin_display['Total_Qty'].map('{:,.0f} Pcs'.format)
    top_margin_display['Total_Revenue'] = top_margin_display['Total_Revenue'].apply(fmt_m)
    top_margin_display['Total_Profit'] = top_margin_display['Total_Profit'].apply(fmt_m)
    top_margin_display['Margin_Pct'] = top_margin_display['Margin_Pct'].map('{:.2f}%'.format)

    top_margin_display = top_margin_display.rename(columns={
        prod_sku_col: 'SKU',
        prod_name_col: 'Product Name',
        'Margin_Pct': 'Margin %',
        'Total_Profit': 'Gross Profit',
        'Total_Revenue': 'Revenue',
        'Total_Qty': 'Qty Sold'
    })[['SKU', 'Product Name', 'Margin %', 'Gross Profit', 'Revenue', 'Qty Sold']]

    html_top_margin_products = top_margin_display.to_html(index=False, border=1, classes='dataframe')

    # Optional Branch Performance Table & Chart
    has_branch = 'branch_name' in df.columns
    branch_chart_buffer = None
    html_branch_perf = ""
    
    if has_branch and df['branch_name'].replace('', pd.NA).dropna().nunique() > 1:
        branch_perf_df = df[df['branch_name'] != ''].groupby('branch_name').agg(
            Orders=(trans_col, 'nunique'),
            Qty_Sold=('quantity', 'sum'),
            Revenue_Raw=('net_amount', 'sum'),
            Gross_Profit_Raw=('gross_profit', 'sum')
        ).reset_index().sort_values(by='Revenue_Raw', ascending=False)
        
        branch_chart_buffer = generate_branch_chart(branch_perf_df)

        branch_perf_df['Revenue'] = branch_perf_df['Revenue_Raw'].apply(fmt_m)
        branch_perf_df['Gross_Profit'] = branch_perf_df['Gross_Profit_Raw'].apply(fmt_m)
        branch_perf_df['Qty_Sold'] = branch_perf_df['Qty_Sold'].map('{:,.0f} Pcs'.format)
        
        display_branch_df = branch_perf_df[['branch_name', 'Orders', 'Qty_Sold', 'Revenue', 'Gross_Profit']]
        html_branch_perf = f"""
        <h3 style="color: #9B2C2C; margin-top: 25px;">🏢 M-Kitchen Branch Performance Breakdown</h3>
        <div style="margin-top: 15px;"><img src="cid:branch_chart" style="max-width:100%; height:auto; border:1px solid #FED7D7; border-radius: 5px;"></div>
        {display_branch_df.to_html(index=False, border=1, classes='dataframe')}
        """

    # Sales Person Visual Donut Chart & Leaderboard
    has_sales_person = 'sales_person_name' in df.columns and df['sales_person_name'].replace('', pd.NA).dropna().nunique() > 0
    sales_chart_buffer = None
    html_sales_widget = ""
    top_sales_person = "N/A"
    top_sales_rev = 0
    
    if has_sales_person:
        sp_df = df[df['sales_person_name'] != ''].copy()
        if not sp_df.empty:
            sales_perf_df = sp_df.groupby('sales_person_name').agg(
                Orders=(trans_col, 'nunique'),
                Qty_Sold=('quantity', 'sum'),
                Revenue_Raw=('net_amount', 'sum'),
                Gross_Profit_Raw=('gross_profit', 'sum')
            ).reset_index().sort_values(by='Revenue_Raw', ascending=False)
            
            top_sales_person = sales_perf_df.iloc[0]['sales_person_name']
            top_sales_rev = sales_perf_df.iloc[0]['Revenue_Raw']
            
            sales_chart_buffer = generate_sales_donut_chart(sales_perf_df)
            
            top5_df = sales_perf_df.head(5)
            total_top5_rev = top5_df['Revenue_Raw'].sum()
            html_legend_items = ""
            
            dot_colors = ['#C53030', '#E53E3E', '#F56565', '#FC8181', '#FEB2B2']
            medals_html = [
                '<span style="font-size: 16px;">🥇</span>',
                '<span style="font-size: 16px;">🥈</span>',
                '<span style="font-size: 16px;">🥉</span>',
                '<span style="font-size: 11px; color: #718096; font-weight: 800;">4th</span>',
                '<span style="font-size: 11px; color: #718096; font-weight: 800;">5th</span>'
            ]
            
            for pos, (_, row) in enumerate(top5_df.iterrows()):
                name = row['sales_person_name']
                rev = row['Revenue_Raw']
                pct = (rev / total_top5_rev * 100) if total_top5_rev > 0 else 0
                
                dot_color = dot_colors[pos]
                medal = medals_html[pos]
                
                html_legend_items += f"""
                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-bottom: 10px;">
                  <tr>
                    <td style="background: #ffffff; border: 1px solid #FED7D7; border-radius: 10px; padding: 12px 16px;">
                      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                        <tr>
                          <td width="14" style="padding-right: 10px;">
                            <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background-color: {dot_color};"></span>
                          </td>
                          <td width="32" style="padding-right: 10px;">{medal}</td>
                          <td align="left" style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; font-weight: 700; color: #2D3748;">{name}</td>
                          <td align="right" style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; font-weight: 800; color: #9B2C2C; white-space: nowrap; padding-left: 15px;">{fmt_m(rev)}&nbsp;&nbsp;({pct:.0f}%)</td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
                """

            html_sales_widget = f"""
            <div style="background: #FFF5F5; width: 100%; max-width: 550px; padding: 24px; border-radius: 16px; border: 1px solid #FED7D7; margin: 25px auto; font-family: 'Segoe UI', Arial, sans-serif;">
              <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px;">
                <tr>
                  <td align="left" style="font-size: 18px; font-weight: 800; color: #9B2C2C;">
                    🏆 Top Sales Champions
                  </td>
                  <td align="right">
                    <span style="font-size: 12px; color: #C53030; background: #FED7D7; padding: 4px 12px; border-radius: 20px; font-weight: 700;">Last 7 Days</span>
                  </td>
                </tr>
              </table>
              
              <div style="text-align: center; margin-bottom: 20px;">
                <img src="cid:sales_donut_chart" style="max-width: 280px; height: auto; display: inline-block;">
              </div>

              {html_legend_items}
            </div>
            """

    # Construct Email Object
    msg = MIMEMultipart('related')
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)
    if cc_receivers:
        msg['Cc'] = ", ".join(cc_receivers)

    msg['Subject'] = f"[M-Kitchen Automated Report] Executive Sales Performance ({min_date} to {max_date})"

    # Email HTML Body
    html_body = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #2D3748; line-height: 1.6; background-color: #ffffff; margin:0; padding:10px; }}
          .info-box {{ background-color: #FFF5F5; border-left: 4px solid #E53E3E; padding: 10px 14px; font-size: 12px; color: #9B2C2C; margin-bottom: 20px; border-radius: 0 4px 4px 0; }}
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
          .kpi-td {{ background: #FFF5F5; border: 1px solid #FED7D7; padding: 14px 16px; border-radius: 6px; vertical-align: top; box-sizing: border-box; }}
          .kpi-title {{ font-size: 11px; color: #742A2A; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px; margin-bottom: 6px; }}
          .kpi-value {{ font-size: 20px; color: #9B2C2C; font-weight: bold; line-height: 1.2; word-break: break-all; }}
          table.dataframe {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; margin-bottom: 25px; }}
          table.dataframe th {{ background-color: #C53030; color: white; padding: 10px; text-align: left; font-weight: 600; }}
          table.dataframe td {{ padding: 8px 10px; border: 1px solid #FED7D7; }}
          table.dataframe tr:nth-child(even) {{ background-color: #FFF5F5; }}
        </style>
      </head>
      <body>
        <h2 style="color: #C53030; border-bottom: 2px solid #C53030; padding-bottom: 8px; margin-top: 0;">🍳 M-Kitchen Executive Sales Performance Summary</h2>
        
        <div class="info-box">
          <b>ℹ️ Pipeline Extraction Info:</b> Data synced from MySQL (<code>bi_database</code>) on <b>{extracted_at}</b>.<br/>
          <b>Filter Criteria:</b> Business ID: <code>M-Kitchen</code> | Branch ID: <code>M-Kitchen YGN</code> | Range: <b>{min_date}</b> to <b>{max_date}</b> | <b>{len(df):,} Total Rows Processed</b>.<br/>
          <b>🚫 Exclusion Applied:</b> Customer group (<code>parent_group_id = <b>Commercial Samples</b> </code>) has been excluded from this report.
        </div>

        <div class="insight-box">
          <span class="insight-title">💡 Executive Insights & Key Takeaways</span>
          <ul class="insight-ul">
            <li><b>Top Revenue Performer:</b> <code>{best_seller_name}</code> is the highest revenue contributor at <b>{fmt_m(best_seller_rev)}</b> (~<b>{best_seller_pct:.1f}%</b> of overall sales).</li>
            <li><b>Top Margin Champion (%):</b> <code>{top_margin_name}</code> achieved the highest profit efficiency with <b>{top_margin_val:.2f}%</b> gross margin.</li>
            <li><b>Top Sales Champion:</b> <code>{top_sales_person}</code> leads the team with <b>{fmt_m(top_sales_rev)}</b> in total revenue generated.</li>
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
        
        {html_sales_widget}

        <h3 style="color: #9B2C2C; margin-top: 25px;">🔥 Top 5 Revenue Contributing Products</h3>
        {html_top_products}

        <h3 style="color: #9B2C2C; margin-top: 25px;">📈 Top 5 Highest Gross Profit Margin (%) Products</h3>
        <p style="font-size: 12px; color: #718096; margin-top: -8px; margin-bottom: 12px;">
          * Filtered for items with minimum sales volume (≥ {MIN_QTY_THRESHOLD} Pcs) to eliminate low-volume outliers.
        </p>
        {html_top_margin_products}

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

    # Embedded Images
    if branch_chart_buffer:
        img = MIMEImage(branch_chart_buffer.read())
        img.add_header('Content-ID', '<branch_chart>')
        img.add_header('Content-Disposition', 'inline', filename='branch_chart.png')
        msg.attach(img)
        
    if sales_chart_buffer:
        img_sp = MIMEImage(sales_chart_buffer.read())
        img_sp.add_header('Content-ID', '<sales_donut_chart>')
        img_sp.add_header('Content-Disposition', 'inline', filename='sales_donut_chart.png')
        msg.attach(img_sp)

    # Attach CSV File
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if os.path.exists(csv_path):
        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_path)}")
        msg.attach(part)

    # Combine All Recipients (TO + CC)
    all_recipients = receivers + cc_receivers

    # SMTP Send Email
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 M-Kitchen Automated Report sent successfully to {len(receivers)} TO recipient(s) & {len(cc_receivers)} CC recipient(s)!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
print("🔄 Starting M-Kitchen ETL, Sync, and Automated Reporting Pipeline...")

try:
    # --------------------------------------------------
    # Step 1: MySQL Extraction (M-Kitchen Logic: Branch 34)
    # --------------------------------------------------
    print("📖 Extracting last 7 days data from MySQL for M-Kitchen...")
    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4'
    )
    
    sql_query = """
        SELECT 
    fs.*,
    c.name AS customer_name,
    cg.name AS customer_group_name,
    cg.parent_group_id,
    -- Sales Person Info
    sp.name AS sales_person_name,
    sp.code AS sales_person_code,
    sp.branch_id AS sales_person_branch_id
FROM bi_database.fact_saless fs
INNER JOIN bi_database.customers c 
    ON fs.customer_id = c.id
    AND c.business_id = fs.business_id
INNER JOIN bi_database.customer_groups cg 
    ON c.group_id = cg.id
    AND cg.business_id = c.business_id
LEFT JOIN bi_database.sales_people sp 
    ON fs.sales_person_id = sp.id
    AND sp.business_id = fs.business_id
  WHERE fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69'
    AND fs.branch_id = 34
  -- Date Range: past 7 days from 00:00:00 to 23:59:59
  AND fs.sale_datetime >= TIMESTAMP('2026-10-11', '00:00:00')
  AND fs.sale_datetime <= TIMESTAMP('2026-10-17', '23:59:59')
  -- Exclude Commercial samples
  AND (cg.parent_group_id != 30 OR cg.id != 30)
  AND (cg.name != 'Commercial samples')
ORDER BY fs.sale_datetime DESC;
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
    print(f"✅ Extracted {total_rows:,} records from Database.")

    # --------------------------------------------------
    # Step 2: Sync to Google Sheet
    # --------------------------------------------------
    print("🔑 Authenticating Service Account for M-Kitchen Google Sheet...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(WORKSHEET_NAME)

    print("🧹 Cleaning existing data & syncing new dataset...")
    sheet.clear()
    sheet.resize(rows=1, cols=len(df.columns))
    
    data_to_write = [df.columns.values.tolist()] + df.values.tolist()
    sheet.update(data_to_write, 'A1')
    print("🎉 M-Kitchen Google Sheet successfully updated!")

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

    print("🏁 M-Kitchen Pipeline Executed Successfully from Start to End!")

except Exception as e:
    print(f"❌ Pipeline Execution Error: {repr(e)}")