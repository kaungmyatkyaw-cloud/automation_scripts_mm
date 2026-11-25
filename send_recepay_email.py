import os
import pandas as pd
import mysql.connector
import gspread
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
# 1. CONFIGURATIONS FROM .ENV
# ==========================================
DB_CONFIG = {
    'user': os.getenv('MYSQL_USERNAME_DAS') or os.getenv('BI_DB_USER'),
    'password': os.getenv('MYSQL_PASSWORD_DAS') or os.getenv('BI_DB_PASS'),
    'host': os.getenv('MYSQL_HOSTNAME_DAS') or os.getenv('BI_DB_HOST'),
    'port': int(os.getenv('MYSQL_PORT_DAS') or os.getenv('BI_DB_PORT') or 25060),
    'database': os.getenv('BI_DB_NAME', 'bi_database'),
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
    'mkitchen_email': parse_email_list('mkitchen_email'),
    'mtrading_email': parse_email_list('mtrading_email'),
    'cc_emails': parse_email_list('cccccc')
}

SHEETS_CONFIG = {
    'mkitchen': {
        'sheet_id': '10g3nQNNUkWDSpcG9dAELjGDxOpI_oOlo7_68gU_9hTA',
        'worksheet_name': 'Sheet4'
    },
    'mtrading': {
        'sheet_id': '1VRTScAR1Rec_toXUpqEJE6-5_IIvVCOUCtA-0fesw9I',
        'worksheet_name': 'Sheet3'
    },
    'summary': {
        'sheet_id': '1WCuxBOugkorM6zJyGmJMXu-f2EtWvOnoYGLdhgER_5w',
        'worksheet_name': 'Sheet1'
    }
}

SERVICE_ACCOUNT_FILE = os.path.join(base_dir, 'mysql-to-sheet-502710-a1c9868da055.json')
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    SERVICE_ACCOUNT_FILE = os.path.join(base_dir, 'mysql-to-sheet-502710-a1c9868da055.json')

# ==========================================
# 2. SQL QUERY (Querying from View vw_receivables_aging)
# ==========================================
SQL_QUERY = """
SELECT 
    business_unit,
    order_number,
    notes,
    invoice_number,
    current_status,
    payment_status,
    invoice_payment_terms,
    PaymentMethods,
    delivery_method_name,
    MarathonCOD,
    Payments,
    days_remaining,
    invoice_date,
    InvoiceMonth,
    sales_channel,
    group_l1,
    group_l2,
    branch,
    invoice_due_date,
    invoice_total_amount,
    invoice_total_paid_amount,
    remaining_balance,
    salesp_name,
    cust_name,
    copy_invoice_number,
    copy_invoice_date,
    copy_remaining_balance,
    copy_cust_name
FROM vw_receivables_aging
ORDER BY remaining_balance DESC;
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def extract_data_from_db():
    print("⏳ Connecting to MySQL Database...")
    try:
        conn: Any = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql(SQL_QUERY, conn)
        conn.close()
        print(f" SQL Extract Completed: Total {len(df)} records fetched.")
        
        # Clean NULL / Empty Values
        df['branch'] = df['branch'].replace('', 'Unknown').fillna('Unknown')
        df['sales_channel'] = df['sales_channel'].replace('', 'NULL').fillna('NULL')
        df['salesp_name'] = df['salesp_name'].replace('', 'NULL').fillna('NULL')
        df['group_l1'] = df['group_l1'].replace('', 'NULL').fillna('NULL')
        df['remaining_balance'] = pd.to_numeric(df['remaining_balance'], errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        print(f"❌ Database Connection Failed: {str(e)}")
        raise e

def get_gspread_client():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return gspread.service_account(filename=SERVICE_ACCOUNT_FILE, scopes=scopes)

def write_to_google_sheet(client, sheet_id, worksheet_name, df):
    try:
        spreadsheet = client.open_by_key(sheet_id)
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"⚠️ Worksheet '{worksheet_name}' not found. Creating new...")
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=30)

        worksheet.clear()
        
        # Convert all to string for clean GSHEET sync
        df_sheet = df.copy()
        for col in df_sheet.columns:
            df_sheet[col] = df_sheet[col].astype(str)

        payload = [df_sheet.columns.values.tolist()] + df_sheet.values.tolist()
        worksheet.update(values=payload, range_name='A1')
        print(f" Sheet Updated Successfully: ID -> {sheet_id} | Tab -> {worksheet_name}")

    except Exception as e:
        print(f"❌ Failed to update Google Sheet ({sheet_id}): {str(e)}")

def format_num(val):
    return f"{val:,.0f}".replace(',', ' ') if val > 0 else ""

def generate_pivot_table_html(df_unit):
    """
    Generates Excel-Style Multi-level Pivot Table identical to the user's screenshot:
    Rows: branch -> sales_channel -> salesp_name -> group_l1
    Cols: LATE, DELAYED COD, ON TIME, TO BE PAID THIS WEEK, Grand Total
    """
    if df_unit.empty:
        return "<p>No data available for this business unit.</p>"

    # Define Column Order
    target_statuses = ['LATE', 'DELAYED COD', 'ON TIME', 'TO BE PAID THIS WEEK']
    
    # Pivot Data
    pivot_df = pd.pivot_table(
        df_unit,
        index=['branch', 'sales_channel', 'salesp_name', 'group_l1'],
        columns='payment_status',
        values='remaining_balance',
        aggfunc='sum',
        fill_value=0
    ).reset_index()

    # Ensure all target status columns exist
    for st in target_statuses:
        if st not in pivot_df.columns:
            pivot_df[st] = 0.0

    # Calculate Row Grand Total
    pivot_df['Grand Total'] = pivot_df[target_statuses].sum(axis=1)

    # HTML Header
    # HTML Header (Proper 2-Row Aligned Header)
    html_out = """
    <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; border: 1px solid #a6b9d1; color: #000000;">
        <thead>
            <tr style="background-color: #dce6f1; font-weight: bold; text-align: left; border-bottom: 1px solid #b8cce4;">
                <th style="padding: 6px; border: 1px solid #b8cce4; color: #1b4f72;" colspan="4">
                    Sum of Remaining Balance (MMK)
                </th>
                <th style="padding: 6px; border: 1px solid #b8cce4; text-align: center; color: #1b4f72;" colspan="5">
                    Payment Aging Status
                </th>
            </tr>
            <tr style="background-color: #edf2f8; font-weight: bold; text-align: left; border-bottom: 2px solid #8ea9db; color: #1f2937;">
                <th style="padding: 6px; border: 1px solid #b8cce4; width: 18%;">Branch</th>
                <th style="padding: 6px; border: 1px solid #b8cce4; width: 14%;">Sales Channel</th>
                <th style="padding: 6px; border: 1px solid #b8cce4; width: 15%;">Sales Person</th>
                <th style="padding: 6px; border: 1px solid #b8cce4; width: 15%;">Customer Group</th>
                <th style="padding: 6px; text-align: right; border: 1px solid #b8cce4; background-color: #f2d7d5; color: #900c3f;">LATE</th>
                <th style="padding: 6px; text-align: right; border: 1px solid #b8cce4; background-color: #d4efdf; color: #1e8449;">DELAYED COD</th>
                <th style="padding: 6px; text-align: right; border: 1px solid #b8cce4; background-color: #d4efdf; color: #1e8449;">ON TIME</th>
                <th style="padding: 6px; text-align: right; border: 1px solid #b8cce4; background-color: #fdebd0; color: #b9770e;">TO BE PAID THIS WEEK</th>
                <th style="padding: 6px; text-align: right; border: 1px solid #b8cce4; background-color: #ebf5fb; color: #1b4f72;">Grand Total</th>
            </tr>
        </thead>
        <tbody>
    """

    # Grouping Logic for Subtotals
    for branch_name, branch_group in pivot_df.groupby('branch', sort=True):
        
        # Branch Subtotal Calculation
        branch_late = branch_group['LATE'].sum()
        branch_delayed = branch_group['DELAYED COD'].sum()
        branch_ontime = branch_group['ON TIME'].sum()
        branch_week = branch_group['TO BE PAID THIS WEEK'].sum()
        branch_total = branch_group['Grand Total'].sum()

        for channel_name, channel_group in branch_group.groupby('sales_channel', sort=False):
            channel_first = True
            
            for salesp_name, salesp_group in channel_group.groupby('salesp_name', sort=False):
                salesp_first = True
                
                for _, row in salesp_group.iterrows():
                    html_out += "<tr>"
                    
                    # Branch Column (Merged Visual via Hierarchy)
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; font-weight: bold; width: 18%;">{("- " + str(branch_name)) if channel_first and salesp_first else ""}</td>'
                    
                    # Sales Channel
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; color: #1a5276; font-weight: 500; width: 14%;">{("- " + str(channel_name)) if salesp_first else ""}</td>'
                    salesp_first = False
                    channel_first = False
                    
                    # Sales Person
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; color: #229954; width: 15%;">- {salesp_name}</td>'
                    
                    # Group L1
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; color: #5d6d7e; width: 15%;">{row["group_l1"]}</td>'
                    
                    # Measures
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; text-align: right;">{format_num(row["LATE"])}</td>'
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; text-align: right;">{format_num(row["DELAYED COD"])}</td>'
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; text-align: right;">{format_num(row["ON TIME"])}</td>'
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; text-align: right;">{format_num(row["TO BE PAID THIS WEEK"])}</td>'
                    html_out += f'<td style="padding: 4px; border: 1px solid #e0e0e0; text-align: right; font-weight: 500;">{format_num(row["Grand Total"])}</td>'
                    
                    html_out += "</tr>"

        # Branch Total Row (Matching Excel Pivot Subtotal Style)
        html_out += f"""
        <tr style="background-color: #f2f4f4; font-weight: bold; border-top: 1px solid #a6b9d1; border-bottom: 2px solid #a6b9d1;">
            <td style="padding: 5px; border: 1px solid #b8cce4;" colspan="4">{branch_name} Total</td>
            <td style="padding: 5px; border: 1px solid #b8cce4; text-align: right;">{format_num(branch_late)}</td>
            <td style="padding: 5px; border: 1px solid #b8cce4; text-align: right;">{format_num(branch_delayed)}</td>
            <td style="padding: 5px; border: 1px solid #b8cce4; text-align: right;">{format_num(branch_ontime)}</td>
            <td style="padding: 5px; border: 1px solid #b8cce4; text-align: right;">{format_num(branch_week)}</td>
            <td style="padding: 5px; border: 1px solid #b8cce4; text-align: right; color: #1b4f72;">{format_num(branch_total)}</td>
        </tr>
        """

    # Overall Grand Total Row
    g_late = pivot_df['LATE'].sum()
    g_delayed = pivot_df['DELAYED COD'].sum()
    g_ontime = pivot_df['ON TIME'].sum()
    g_week = pivot_df['TO BE PAID THIS WEEK'].sum()
    g_total = pivot_df['Grand Total'].sum()

    html_out += f"""
        <tr style="background-color: #d9e1f2; font-weight: bold; border-top: 2px solid #2f5597; border-bottom: 2px solid #2f5597; font-size: 12px;">
            <td style="padding: 6px; border: 1px solid #8ea9db;" colspan="4">Grand Total</td>
            <td style="padding: 6px; border: 1px solid #8ea9db; text-align: right; color: #900c3f;">{format_num(g_late)}</td>
            <td style="padding: 6px; border: 1px solid #8ea9db; text-align: right; color: #1e8449;">{format_num(g_delayed)}</td>
            <td style="padding: 6px; border: 1px solid #8ea9db; text-align: right; color: #1e8449;">{format_num(g_ontime)}</td>
            <td style="padding: 6px; border: 1px solid #8ea9db; text-align: right; color: #b9770e;">{format_num(g_week)}</td>
            <td style="padding: 6px; border: 1px solid #8ea9db; text-align: right; color: #1b4f72;">{format_num(g_total)}</td>
        </tr>
        </tbody>
    </table>
    """
    return html_out

def generate_masterdata_to_be_fixed_html(df_unit):
    """
    Masterdata check for invoices with sales_channel = NULL or 'NULL'
    """
    null_df = df_unit[df_unit['sales_channel'].isin(['NULL', ''])]
    null_count = len(null_df)

    return f"""
    <div style="background-color: #fce8e6; border-left: 4px solid #d93025; padding: 12px 15px; margin-top: 20px; margin-bottom: 20px; font-size: 13px;">
        <h4 style="margin-top: 0; margin-bottom: 6px; color: #d93025; font-size: 14px;">⚠️ Masterdata to be fixed</h4>
        <p style="margin: 0; color: #3c4043; line-height: 1.5;">
            Mentioning <b>{null_count} invoice(s)</b> with <code style="background-color: #ffffff; color: #d93025; padding: 2px 6px; border: 1px solid #f5c6cb; border-radius: 3px; font-weight: bold;">sales_channel = NULL</code> 
            as a reminder to the teams that these customers are not linked to a customer group on DAS.
        </p>
    </div>
    """

def generate_data_fetching_info_html():
    code = "background-color: #202124; color: #34a853; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; font-size: 12px;"
    
    return f"""
    <div style="background-color: #f8f9fa; border-left: 4px solid #1a73e8; padding: 15px; margin-top: 20px; margin-bottom: 20px; font-size: 13px;">
        <h4 style="margin-top: 0; color: #1a73e8; font-size: 14px;">ℹ️ Data Fetching Scope & Business Logic (from View)</h4>
        <ul style="margin: 0; padding-left: 20px; color: #4a4a4a; line-height: 1.8;">
            <li><b>Database View:</b> [<code style="{code}">vw_receivables_aging</code>]</li>
            <li><b>Business Scope & Entity Partitioning:</b> Automatically handled via view definitions for M-Kitchen and MTrading.</li>
            <li><b>Data Scope & Exclusions:</b> Unpaid & Outstanding invoices (Excludes Paid, Void, and Opening Balances).</li>
            <li><b>Payment Status Classification Logic:</b> ON TIME, DELAYED COD, TO BE PAID THIS WEEK, and LATE pre-calculated via view.</li>
            <li><b>Delivery & Payment Aggregation:</b> Flagged <code style="{code}">MarathonCOD</code> and payment strings aggregated via view.</li>
            <li><b>Customer Hierarchy Mapping:</b> Multi-level customer groups mapped dynamically.</li>
        </ul>
    </div>
    """

def send_individual_email(unit_name, df_unit, to_emails, cc_emails):
    if not to_emails:
        print(f"⚠️ Skipped sending email for {unit_name}: No receiver emails specified in .env.")
        return

    msg = MIMEMultipart()
    msg['From'] = SMTP_CONFIG['sender_email']
    msg['To'] = ", ".join(to_emails)
    if cc_emails:
        msg['Cc'] = ", ".join(cc_emails)
        
    # Standard Title
    msg['Subject'] = f"Weekly Accounts Receivable & Outstanding Report ({unit_name}) - {datetime.now().strftime('%Y-%m-%d')}"

    # Generate Components
    pivot_table_html = generate_pivot_table_html(df_unit)
    masterdata_fix_html = generate_masterdata_to_be_fixed_html(df_unit)
    info_html = generate_data_fetching_info_html()

    dashboard_url = "https://datastudio.google.com/reporting/e8c5cfd8-ca34-448e-8336-efefd8b297ad"
    summary_sheet_url = "https://docs.google.com/spreadsheets/d/1WCuxBOugkorM6zJyGmJMXu-f2EtWvOnoYGLdhgER_5w/edit?gid=0#gid=0"

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333333; line-height: 1.6;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
          Weekly Accounts Receivable & Outstanding Report ({unit_name} system)
        </h2>
        <p>Hi EVERYONE!</p>
        
        <p>Here is the weekly outstanding balance breakdown for <b>{unit_name}</b> as of <b>{datetime.now().strftime('%d %B %Y')}</b>:</p>
        
        {pivot_table_html}

        <div style="margin: 25px 0;">
          <a href="{dashboard_url}" target="_blank" 
             style="background-color: #1a73e8; color: #ffffff; padding: 10px 18px; text-decoration: none; font-weight: bold; font-size: 13px; border-radius: 4px;">
             📊 Open Interactive Dashboard
          </a>
          &nbsp;
          <a href="{summary_sheet_url}" target="_blank" 
             style="background-color: #34a853; color: #ffffff; padding: 10px 18px; text-decoration: none; font-weight: bold; font-size: 13px; border-radius: 4px;">
             📗 View Consolidated Master Sheet
          </a>
        </div>

        {masterdata_fix_html}

        {info_html}

        <p style="font-size: 13px; color: #5f6368;">
          <i>Note: Full itemized data is synchronized live in the Google Sheet. The attached CSV contains raw data for {unit_name}.</i>
        </p>
        
        <hr style="border: 0; border-top: 1px solid #e0e0e0; margin-top: 25px;">
        <p style="font-size: 11px; color: #9aa0a6;">Marathon Myanmar | Data Engineering & Analytics</p>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, 'html'))

    csv_bytes = df_unit.to_csv(index=False).encode('utf-8')
    attachment = MIMEApplication(csv_bytes, Name=f"{unit_name}_Outstanding_{datetime.now().strftime('%Y%m%d')}.csv")
    attachment['Content-Disposition'] = f'attachment; filename="{unit_name}_Outstanding_{datetime.now().strftime("%Y%m%d")}.csv"'
    msg.attach(attachment)

    all_recipients = to_emails + cc_emails

    try:
        server = smtplib.SMTP(SMTP_CONFIG['smtp_server'], SMTP_CONFIG['smtp_port'])
        server.starttls()
        server.login(SMTP_CONFIG['sender_email'], SMTP_CONFIG['sender_password'])
        server.sendmail(SMTP_CONFIG['sender_email'], all_recipients, msg.as_string())
        server.quit()
        print(f" Email Sent Successfully to {unit_name} Team (To: {to_emails}, CC: {cc_emails})")
    except Exception as e:
        print(f"❌ Failed to send email to {unit_name}: {str(e)}")

# ==========================================
# 4. MAIN PIPELINE EXECUTION
# ==========================================
def main():
    print("=== AUTOMATION PIPELINE STARTED ===")

    # 1. Fetch Data from View
    df_all = extract_data_from_db()
    if df_all.empty:
        print("⚠️ Warning: No records found from MySQL view. Exiting process.")
        return

    # 2. Partition Data by Business Unit
    df_mk = df_all[df_all['business_unit'] == 'M-Kitchen']
    df_mt = df_all[df_all['business_unit'] == 'MTrading']

    # 3. Sync Data to Google Sheets
    print("\n⏳ Updating Google Sheets...")
    try:
        client = get_gspread_client()
        write_to_google_sheet(client, SHEETS_CONFIG['mkitchen']['sheet_id'], SHEETS_CONFIG['mkitchen']['worksheet_name'], df_mk)
        write_to_google_sheet(client, SHEETS_CONFIG['mtrading']['sheet_id'], SHEETS_CONFIG['mtrading']['worksheet_name'], df_mt)
        write_to_google_sheet(client, SHEETS_CONFIG['summary']['sheet_id'], SHEETS_CONFIG['summary']['worksheet_name'], df_all)
    except Exception as e:
        print(f"❌ Google Sheets Authentication Failed: {str(e)}")

    # 4. Send Automated Emails (Pivot Table generated for each BU)
    print("\n⏳ Triggering Email Dispatches...")
    send_individual_email('M-Kitchen', df_mk, SMTP_CONFIG['mkitchen_email'], SMTP_CONFIG['cc_emails'])
    send_individual_email('MTrading', df_mt, SMTP_CONFIG['mtrading_email'], SMTP_CONFIG['cc_emails'])

    print("\n=== PIPELINE EXECUTED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()