import os
import pymysql
import pandas as pd
import gspread
from typing import Any, cast
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# .env ဖိုင်ရှိရာ သတ်မှတ်ထားသော Path ကို ညွှန်ပြ၍ Load လုပ်ခြင်း
dotenv_path = r'C:\Users\kye58\marathon-projects\clone_repo\automation_scripts_mm\.env'
load_dotenv(dotenv_path=dotenv_path)

# Environment Variables များမှ Database Configuration များကို ဆွဲယူခြင်း
DB_HOST = os.getenv('BI_DB_HOST')
DB_PORT = int(os.getenv('BI_DB_PORT', 25060))
DB_USER = os.getenv('BI_DB_USER')
DB_PASS = os.getenv('BI_DB_PASS')
DB_NAME = os.getenv('BI_DB_NAME')

# Google Sheets Configuration
SPREADSHEET_ID = os.getenv('DAILY_SALES_SPREADSHEET_ID')
SHEET_NAME = 'daily_sales'

# Service Account JSON Path
CREDENTIALS_FILE = r'C:\Users\kye58\marathon-projects\clone_repo\automation_scripts_mm\service_account_update.json'

# Filter လုပ်မည့် Business IDs များ
TARGET_BUSINESS_IDS = (
    '1eb52cc2-7a34-43d8-b646-67cc60402916',
    '2d393763-d5c7-42be-b345-84b7be787f10',
    'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08',
    '7ef7c6c0-b59d-4be9-960c-7fa573038642',
    '84093770-29ad-4e8e-9da1-babe583c0d69'
)

def refresh_daily_sales_data():
    print("Connecting to DigitalOcean MySQL database...")

    if DB_PASS is None:
        raise ValueError("BI_DB_PASS environment variable is required.")
    if SPREADSHEET_ID is None:
        raise ValueError("DAILY_SALES_SPREADSHEET_ID environment variable is required.")
    
    # DigitalOcean MySQL သို့ SSL ဖြင့် ချိတ်ဆက်ခြင်း
    connection = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        ssl={'ssl': {}}
    )
    
    try:
        placeholders = ', '.join(['%s'] * len(TARGET_BUSINESS_IDS))
        query = f"""
            SELECT * 
            FROM bi_database.vw_daily_sales_summary
            WHERE business_id IN ({placeholders})
            ORDER BY sale_date DESC, business_name, branch_name;
        """
        print("Executing query and fetching data...")
        df = pd.read_sql(query, cast(Any, connection), params=TARGET_BUSINESS_IDS)
        print(f"Successfully fetched {len(df)} rows from database.")
    finally:
        connection.close()
        print("Database connection closed.")

    print("Formatting data for Google Sheets...")
    # ဒေတာထဲတွင် ပါလာနိုင်သော datetime / date object များကို JSON serializable ဖြစ်စေရန် string သို့ ပြောင်းခြင်း
    for col in df.select_dtypes(include=['datetime64[ns]', 'object']):
        try:
            df[col] = pd.to_datetime(df[col], errors=cast(Any, 'ignore'))
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                if col == 'sale_date':
                    df[col] = df[col].dt.strftime('%Y-%m-%d').fillna('')
                else:
                    df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        except Exception:
            df[col] = df[col].astype(str)

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
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=10000, cols=30)

    print("Clearing existing sheet data...")
    sheet.clear()

    print("Uploading new data to Google Sheet...")
    # Header နှင့် Data များကို တစ်ခါတည်း Update လုပ်ခြင်း
    data = [df.columns.tolist()] + df.values.tolist()
    sheet.update(data)
    print("Google Sheet successfully updated!")

if __name__ == "__main__":
    refresh_daily_sales_data()