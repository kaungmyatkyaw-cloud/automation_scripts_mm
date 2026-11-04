import os
import io
import pandas as pd
import mysql.connector
import smtplib
import warnings
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from dotenv import load_dotenv

# Crucial: Set matplotlib backend to 'Agg' for server-side/cron execution (no GUI)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

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
    'receiver_emails': parse_email_list('finance_mail'),
    'cc_emails': parse_email_list('cccccc')
}

# ==========================================
# 2. SQL QUERY (Bulk Extract 2026)
# ==========================================
SQL_QUERY = """
SELECT 
    si.invoice_date                                   AS invoice_date,
    DATE(si.invoice_date)                             AS date,
    c.name                                            AS customer_name,
    si.invoice_number                                 AS invoice_number,
    COALESCE(p.sku, pv.sku, 'N/A')                    AS sku,
    COALESCE(p.name, sid.name)                        AS product_name,
    p.sales_price                                     AS master_standard_price,
    sid.detail_unit_rate                              AS actual_unit_rate,
    
    CASE 
        WHEN p.sales_price IS NULL OR p.sales_price <= 0 OR p.sales_price = 1 THEN NULL
        ELSE (sid.detail_unit_rate - p.sales_price)
    END                                               AS unit_price_variance,

    CASE 
        WHEN p.sales_price IS NULL OR p.sales_price <= 0 OR p.sales_price = 1 THEN 'no_master_price'
        WHEN sid.detail_unit_rate < p.sales_price        THEN 'under_priced'
        WHEN sid.detail_unit_rate > p.sales_price        THEN 'over_priced'
        ELSE 'as_per_master'
    END                                               AS variance_status,

    sid.detail_qty                                    AS qty,
    (sid.detail_unit_rate * sid.detail_qty)           AS calculated_amount,
    sid.detail_total_amount                           AS amount,
    (sid.detail_total_amount - (sid.detail_unit_rate * sid.detail_qty)) AS line_amount_variance,
    COALESCE(sid.detail_discount_amount, 0)           AS line_discount_amount,
    COALESCE(sid.detail_tax_amount, 0)                AS line_tax_amount,

    CASE 
        WHEN ABS(sid.detail_total_amount - (sid.detail_unit_rate * sid.detail_qty)) <= 0.01 THEN 'exact_match'
        WHEN sid.detail_discount_amount > 0 AND sid.detail_tax_amount > 0 THEN 'discount_and_tax_applied'
        WHEN sid.detail_discount_amount > 0 THEN 'discount_applied'
        WHEN sid.detail_tax_amount > 0 THEN 'tax_applied'
        ELSE 'unexplained_variance'
    END                                               AS amount_variance_status,

    si.sales_person_id                                AS sales_person_id,
    sp.name                                           AS sales_person_name

FROM sales_invoices si
JOIN customers c 
    ON si.customer_id = c.id AND si.business_id = c.business_id
LEFT JOIN branches b 
    ON si.branch_id = b.id
JOIN sales_invoice_details sid 
    ON si.id = sid.sales_invoice_id
LEFT JOIN products p 
    ON sid.product_id = p.id AND si.business_id = p.business_id
LEFT JOIN product_variants pv 
    ON sid.product_id = pv.id AND si.business_id = pv.business_id AND sid.product_type = 'V'
LEFT JOIN sales_people sp 
    ON si.sales_person_id = sp.id AND si.business_id = sp.business_id

WHERE si.current_status IN ('Confirmed', 'Partial Paid', 'Paid', 'Write Off')
  AND (
      (si.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(b.id AS CHAR)) != '34' OR b.id IS NULL))
      OR 
      (si.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642')
  )
  AND si.invoice_date >= '2026-01-01' 
  AND si.invoice_date < '2027-01-01'
  
ORDER BY date DESC, ABS(COALESCE(CASE WHEN p.sales_price > 0 AND p.sales_price != 1 THEN (sid.detail_unit_rate - p.sales_price) ELSE 0 END, 0)) * sid.detail_qty DESC;
"""

# ==========================================
# 3. CHART GENERATION FUNCTION
# ==========================================
def generate_impact_chart_bytes(df):
    """Generates a Financial Impact Bar Chart and returns raw PNG bytes."""
    if df.empty or 'unit_price_variance' not in df.columns:
        return None

    # Calculate impact
    df_chart = df.copy()
    df_chart['impact'] = df_chart['unit_price_variance'] * df_chart['qty']
    
    # Group by variance status and sum the impact
    chart_data = df_chart.groupby('variance_status')['impact'].sum().reset_index()
    
    # Filter out 'as_per_master' and 'no_master_price' for the impact chart
    chart_data = chart_data[chart_data['variance_status'].isin(['under_priced', 'over_priced', 'unexplained_variance'])]
    
    if chart_data.empty:
        return None

    # Create the plot
    fig, ax = plt.subplots(figsize=(8, 4.5))
    
    # Define corporate colors
    colors = {
        'under_priced': '#dc2626',      # Red
        'over_priced': '#16a34a',       # Green
        'unexplained_variance': '#ea580c' # Orange
    }
    bar_colors = [colors.get(status, '#64748b') for status in chart_data['variance_status']]

    # Convert to Millions for cleaner axis
    chart_data['impact_million'] = chart_data['impact'] / 1000000

    # Plot
    bars = ax.bar(chart_data['variance_status'].str.replace('_', ' ').str.title(), 
                  chart_data['impact_million'], 
                  color=bar_colors, width=0.6)

    # Formatting
    ax.set_title('Net Financial Impact by Deviation Type (in Million MMK)', 
                 fontsize=14, fontweight='bold', color='#1e293b', pad=15)
    ax.set_ylabel('Impact (Million MMK)', fontsize=12, color='#475569')
    ax.set_xlabel('') 
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#e2e8f0')
    ax.spines['bottom'].set_color('#e2e8f0')
    ax.tick_params(colors='#64748b')
    ax.axhline(0, color='#334155', linewidth=0.8)

    # Add value labels on top of bars
    for bar in bars:
        yval = bar.get_height()
        offset = 0.05 if yval >= 0 else -0.15
        ax.text(bar.get_x() + bar.get_width()/2, yval + offset, 
                f'{yval:,.2f}', ha='center', va='bottom' if yval >= 0 else 'top', 
                fontsize=11, fontweight='bold', color='#1e293b')

    plt.tight_layout()

    # Save to bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_bytes = buf.read()
    plt.close(fig)
    
    return img_bytes

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting MTrading Price Deviation Email...")
    
    # --- A. Fetch Data ---
    try:
        print("Connecting to database and fetching 2026 data...")
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql_query(SQL_QUERY, conn)  # type: ignore[arg-type]
        conn.close()
        print(f"Successfully fetched {len(df)} records for 2026.")
    except Exception as e:
        print(f"Database Error: {e}")
        return

    if df.empty:
        print("No data found for 2026. Exiting.")
        return

    # --- B. Data Processing ---
    df['date'] = pd.to_datetime(df['date'])
    today = pd.to_datetime('today').normalize()
    seven_days_ago = today - timedelta(days=7)
    
    # Pre-calculate variance impact for efficiency
    df['variance_impact'] = df['unit_price_variance'] * df['qty']
    
    # 1. Filter for Last 7 Days
    df_last_7 = df[df['date'] >= seven_days_ago].copy()
    
    # 2. Monthly Aggregation (Full 2026)
    df['month'] = df['date'].dt.to_period('M').astype(str)
    
    underpriced_skus_monthly = df[df['variance_status'] == 'under_priced'].groupby('month')['sku'].nunique().reset_index(name='underpriced_skus')
    overpriced_skus_monthly = df[df['variance_status'] == 'over_priced'].groupby('month')['sku'].nunique().reset_index(name='overpriced_skus')
    unique_customers_monthly = df[df['variance_status'].isin(['under_priced', 'over_priced', 'unexplained_variance', 'no_master_price'])].groupby('month')['customer_name'].nunique().reset_index(name='unique_customers_with_deviation')
    
    monthly_summary = df.groupby('month').agg(
        total_lines=('invoice_number', 'count'),
        total_variance_amount=('variance_impact', 'sum')
    ).reset_index()
    
    monthly_summary = monthly_summary.merge(underpriced_skus_monthly, on='month', how='left').fillna(0)
    monthly_summary = monthly_summary.merge(overpriced_skus_monthly, on='month', how='left').fillna(0)
    monthly_summary = monthly_summary.merge(unique_customers_monthly, on='month', how='left').fillna(0)
    
    monthly_summary['underpriced_skus'] = monthly_summary['underpriced_skus'].astype(int)
    monthly_summary['overpriced_skus'] = monthly_summary['overpriced_skus'].astype(int)
    monthly_summary['unique_customers_with_deviation'] = monthly_summary['unique_customers_with_deviation'].astype(int)
    monthly_summary = monthly_summary.sort_values('month', ascending=False)

    # 3. Last 7 Days Summary Metrics
    last_7_total_lines = len(df_last_7)
    last_7_unique_invoices = df_last_7['invoice_number'].nunique() # NEW METRIC
    last_7_underpriced_skus = df_last_7[df_last_7['variance_status'] == 'under_priced']['sku'].nunique()
    last_7_overpriced_skus = df_last_7[df_last_7['variance_status'] == 'over_priced']['sku'].nunique()
    last_7_unique_customers = df_last_7[df_last_7['variance_status'].isin(['under_priced', 'over_priced', 'unexplained_variance', 'no_master_price'])]['customer_name'].nunique()
    last_7_financial_impact = df_last_7['variance_impact'].sum()
    
    # 4. Top 10 SKUs (Last 7 Days)
    top_10_skus = df_last_7.groupby(['sku', 'product_name'])['variance_impact'].sum().reset_index()
    top_10_skus['abs_impact'] = top_10_skus['variance_impact'].abs()
    top_10_skus = top_10_skus.sort_values('abs_impact', ascending=False).head(10)

    # 5. Generate Chart Bytes
    chart_bytes = generate_impact_chart_bytes(df_last_7)

    # --- C. Generate CSV Attachment (Last 7 Days Only) ---
    csv_buffer = io.StringIO()
    df_last_7.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_data = csv_buffer.getvalue()

    # --- D. Build HTML Email Body ---
    report_date = datetime.now().strftime("%B %d, %Y")
    
    def fmt_curr(val):
        return f"{val:,.2f} MMK" if pd.notnull(val) else "0.00 MMK"

    # Build Monthly Table Rows
    monthly_html_rows = ""
    for _, row in monthly_summary.iterrows():
        month_str = row['month']
        try:
            month_obj = datetime.strptime(month_str, "%Y-%m")
            month_display = month_obj.strftime("%B %Y")
        except Exception:
            month_display = month_str
            
        variance_color = "warning" if row['total_variance_amount'] < 0 else "success"
        monthly_html_rows += f"""
        <tr>
            <td><strong>{month_display}</strong></td>
            <td class="text-right">{int(row['total_lines']):,}</td>
            <td class="text-right warning">{int(row['underpriced_skus']):,}</td>
            <td class="text-right warning">{int(row['overpriced_skus']):,}</td>
            <td class="text-right">{int(row['unique_customers_with_deviation']):,}</td>
            <td class="text-right {variance_color}">{fmt_curr(row['total_variance_amount'])}</td>
        </tr>
        """
    
    monthly_table = f"""
    <table>
        <tr>
            <th>Month</th>
            <th class="text-right">Total Lines</th>
            <th class="text-right">Under-Priced SKUs</th>
            <th class="text-right">Over-Priced SKUs</th>
            <th class="text-right">Unique Customers w/ Deviation</th>
            <th class="text-right">Net Variance Amount</th>
        </tr>
        {monthly_html_rows if monthly_html_rows else "<tr><td colspan='6' style='text-align:center;'>No deviations recorded in 2026.</td></tr>"}
    </table>
    """

    # Build Top 10 Table Rows
    top_10_html_rows = ""
    for _, row in top_10_skus.iterrows():
        variance_color = "warning" if row['variance_impact'] < 0 else "success"
        product_name = str(row['product_name'])
        display_name = product_name[:60] + '...' if len(product_name) > 60 else product_name
        
        top_10_html_rows += f"""
        <tr>
            <td><strong>{row['sku']}</strong></td>
            <td>{display_name}</td>
            <td class="text-right {variance_color}">{fmt_curr(row['variance_impact'])}</td>
        </tr>
        """

    top_10_table = f"""
    <table>
        <tr>
            <th>SKU</th>
            <th>Product Name</th>
            <th class="text-right">Total Variance Impact</th>
        </tr>
        {top_10_html_rows if top_10_html_rows else "<tr><td colspan='3' style='text-align:center;'>No significant deviations found in the last 7 days.</td></tr>"}
    </table>
    """

    # Build Chart HTML (Using CID reference)
    # Note: We use src="cid:financial_chart" which links to the attached image
    chart_html = """
    <div class="section">
        <h3 class="section-title">Financial Impact Visualization (Last 7 Days)</h3>
        <p style="font-size: 14px; color: #64748b; margin-bottom: 15px;">
            Visual representation of revenue leakage (Under-priced) vs. overcharging (Over-priced).
        </p>
        <div style="text-align: center;">
            <img src="cid:financial_chart" alt="Financial Impact Chart" style="max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 8px;">
        </div>
    </div>
    """

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; background-color: #f4f6f8; margin: 0; padding: 20px; }}
            .container {{ max-width: 1200px; width: 95%; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .header {{ background-color: #2563eb; color: white; padding: 24px; }}
            .header h2 {{ margin: 0; font-size: 24px; }}
            .header p {{ margin: 8px 0 0 0; opacity: 0.9; font-size: 14px; }}
            .section {{ padding: 24px; border-bottom: 1px solid #e2e8f0; }}
            .section:last-child {{ border-bottom: none; }}
            .section-title {{ margin-top: 0; color: #1e293b; font-size: 18px; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 16px; display: inline-block; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
            th {{ background-color: #f8fafc; text-align: left; padding: 12px; border-bottom: 2px solid #cbd5e1; color: #475569; font-weight: 600; }}
            td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; color: #334155; }}
            .text-right {{ text-align: right; }}
            .warning {{ color: #dc2626; font-weight: bold; }}
            .success {{ color: #16a34a; font-weight: bold; }}
            .logic-box {{ background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 16px; margin-top: 10px; border-radius: 4px; }}
            .logic-box h3 {{ margin-top: 0; color: #0369a1; font-size: 16px; }}
            .logic-box ul {{ margin-bottom: 0; padding-left: 20px; }}
            .logic-box li {{ margin-bottom: 8px; }}
            .footer-note {{ text-align: center; padding: 20px; background-color: #f8fafc; color: #64748b; font-size: 13px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>MTrading Price Deviation Analysis</h2>
                <p>Generated on: {report_date} (Data Scope: Full Year 2026)</p>
            </div>

            <!-- LAST 7 DAYS SUMMARY -->
            <div class="section">
                <h3 class="section-title">Last 7 Days Executive Summary</h3>
                <table style="max-width: 600px;">
                    <tr>
                        <th>Metric</th>
                        <th class="text-right">Value</th>
                    </tr>
                    <tr>
                        <td>Total Unique Invoices Checked</td>
                        <td class="text-right">{last_7_unique_invoices:,}</td>
                    </tr>
                    <tr>
                        <td>Total Invoice Lines Checked</td>
                        <td class="text-right">{last_7_total_lines:,}</td>
                    </tr>
                    <tr>
                        <td>Unique SKUs Under-Priced</td>
                        <td class="text-right warning">{last_7_underpriced_skus:,}</td>
                    </tr>
                    <tr>
                        <td>Unique SKUs Over-Priced</td>
                        <td class="text-right warning">{last_7_overpriced_skus:,}</td>
                    </tr>
                    <tr>
                        <td>Unique Customers with Deviations</td>
                        <td class="text-right">{last_7_unique_customers:,}</td>
                    </tr>
                    <tr>
                        <td>Net Financial Impact (Variance)</td>
                        <td class="text-right {'warning' if last_7_financial_impact < 0 else 'success'}">{fmt_curr(last_7_financial_impact)}</td>
                    </tr>
                </table>
            </div>

            {chart_html}

            <!-- MONTHLY ANALYSIS (Full 2026) -->
            <div class="section">
                <h3 class="section-title">2026 Monthly Deviation Summary</h3>
                <p style="font-size: 14px; color: #64748b; margin-bottom: 10px;">Aggregated view of pricing variances, unique affected SKUs, and unique customers per month.</p>
                {monthly_table}
            </div>

            <!-- TOP 10 SKUs -->
            <div class="section">
                <h3 class="section-title">Top 10 SKUs Requiring Attention (Last 7 Days)</h3>
                <p style="font-size: 14px; color: #64748b; margin-bottom: 10px;">Products with the highest absolute financial variance impact recently.</p>
                {top_10_table}
            </div>

            <!-- BUSINESS LOGIC & EXPLANATION -->
            <div class="section">
                <h3 class="section-title">Business Logic Explanation</h3>
                <div class="logic-box">
                    <p>This report automatically checks every sales invoice to ensure items are being sold at the official Master Standard Price.</p>
                    <ul>
                        <li><strong>Under-priced:</strong> The item was sold for less than the master price. This directly reduces profit margin and should be reviewed.</li>
                        <li><strong>Over-priced:</strong> The item was sold for more than the master price. This may indicate a manual override or data entry error.</li>
                        <li><strong>Exact Match / Discount Applied:</strong> The final line amount perfectly matches the math (Unit Price x Quantity), or a documented discount/tax was correctly applied. These are healthy transactions.</li>
                        <li><strong>Unexplained Variance:</strong> The final invoice line total does not match the calculated unit price x quantity, and no discount/tax is recorded. This requires immediate investigation.</li>
                    </ul>
                    <p style="margin-top: 12px; margin-bottom: 0;"><em><strong>Why this matters:</strong> Catching these deviations early prevents revenue leakage, ensures sales teams follow pricing guidelines, and keeps our financial reporting accurate.</em></p>
                </div>
            </div>
            
            <div class="footer-note">
                A detailed CSV file containing every single line-item deviation from the last 7 days is attached to this email for your deep-dive analysis.
            </div>
        </div>
    </body>
    </html>
    """

    # --- E. Send Email ---
    if not SMTP_CONFIG['receiver_emails']:
        print("No receiver emails configured. Skipping email send.")
        return

    try:
        print("Connecting to SMTP server...")
        msg = MIMEMultipart()
        msg['From'] = SMTP_CONFIG['sender_email']
        msg['To'] = ", ".join(SMTP_CONFIG['receiver_emails'])
        if SMTP_CONFIG['cc_emails']:
            msg['Cc'] = ", ".join(SMTP_CONFIG['cc_emails'])
        msg['Subject'] = f"MTrading Price Deviation Analysis - {datetime.now().strftime('%Y-%m-%d')}"
        
        msg.attach(MIMEText(html_body, 'html'))

        # Attach Chart Image (CID Method)
        if chart_bytes:
            img_attachment = MIMEImage(chart_bytes, _subtype='png')
            img_attachment.add_header('Content-ID', '<financial_chart>')
            img_attachment.add_header('Content-Disposition', 'inline', filename='financial_impact_chart.png')
            msg.attach(img_attachment)
            print("Chart image attached successfully.")
        else:
            print("No chart data available to attach.")

        # Attach CSV
        part = MIMEApplication(csv_data.encode('utf-8'), Name="mtrading_last_7_days_deviations.csv")
        part['Content-Disposition'] = 'attachment; filename="mtrading_last_7_days_deviations.csv"'
        msg.attach(part)

        server = smtplib.SMTP(SMTP_CONFIG['smtp_server'], SMTP_CONFIG['smtp_port'])
        server.starttls()
        server.login(SMTP_CONFIG['sender_email'], SMTP_CONFIG['sender_password'])
        server.send_message(msg)
        server.quit()
        
        print(f"[SUCCESS] Email sent successfully to {', '.join(SMTP_CONFIG['receiver_emails'])}!")
    except Exception as e:
        print(f"Email Sending Error: {e}")

if __name__ == "__main__":
    main()