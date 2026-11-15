import os
from decimal import Decimal
import pymysql
import pandas as pd
import gspread
from typing import Any, cast
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# .env ဖိုင်ရှိရာ Path ကို ညွှန်ပြ၍ Load လုပ်ခြင်း
dotenv_path = r'C:\Users\kye58\marathon-projects\clone_repo\automation_scripts_mm\.env'
load_dotenv(dotenv_path=dotenv_path)

# Database Configuration
DB_HOST = os.getenv('BI_DB_HOST')
DB_PORT = int(os.getenv('BI_DB_PORT', 25060))
DB_USER = os.getenv('BI_DB_USER')
DB_PASS = os.getenv('BI_DB_PASS')
DB_NAME = os.getenv('BI_DB_NAME')

# Google Sheets Configuration
SPREADSHEET_ID = os.getenv('RECEIVABLES_SPREADSHEET_ID')
SHEET_NAME = 'refresh_data'

# Service Account JSON Path
CREDENTIALS_FILE = r'C:\Users\kye58\marathon-projects\clone_repo\automation_scripts_mm\service_account_update.json'


def refresh_receivables_data():
    if not all([DB_HOST, DB_USER, DB_PASS, DB_NAME]):
        raise ValueError("Database environment variables (BI_DB_HOST, BI_DB_USER, BI_DB_PASS, BI_DB_NAME) are required.")
    if not SPREADSHEET_ID:
        raise ValueError("RECEIVABLES_SPREADSHEET_ID environment variable is required.")

    print("Connecting to DigitalOcean MySQL database...")
    connection = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=cast(str, DB_PASS),
        database=DB_NAME,
        ssl={'ssl': {}}
    )

    try:
        query = """
            SELECT *
            FROM bi_database.vw_receivables_aging
            ORDER BY remaining_balance DESC;
        """
        print("Executing query and fetching receivables data...")
        df = pd.read_sql(query, cast(Any, connection))
        print(f"Successfully fetched {len(df)} rows from database.")
    finally:
        connection.close()
        print("Database connection closed.")

    print("Formatting data for Google Sheets...")
    # Date / Datetime / Decimal object များကို JSON serializable ဖြစ်စေရန် ပြောင်းလဲခြင်း
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            if col in ('invoice_date', 'invoice_due_date', 'copy_invoice_date'):
                df[col] = df[col].dt.strftime('%Y-%m-%d').fillna('')
            else:
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        elif df[col].dtype == 'object':
            df[col] = df[col].apply(
                lambda x: float(x) if isinstance(x, Decimal)
                else (x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else ('' if x is None else str(x)))
            )

    df = df.fillna('')

    print("Connecting to Google Sheets...")
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=max(len(df) + 100, 1000), cols=max(len(df.columns) + 5, 35))

    print(f"Clearing existing data in '{SHEET_NAME}'...")
    sheet.clear()

    print(f"Uploading new data to '{SHEET_NAME}'...")
    data = [df.columns.tolist()] + df.values.tolist()
    sheet.update(data)
    print(f"Google Sheet ('{SHEET_NAME}') successfully updated with {len(df)} rows!")


if __name__ == "__main__":
    refresh_receivables_data()