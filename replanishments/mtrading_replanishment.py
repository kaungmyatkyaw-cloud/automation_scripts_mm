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
SPREADSHEET_ID = os.getenv('MTRADING_REPLANISHMENT_SPREADSHEET_ID')
SHEET_NAME = 'refresh_data'

# Service Account JSON Path
CREDENTIALS_FILE = r'C:\Users\kye58\marathon-projects\clone_repo\automation_scripts_mm\service_account_update.json'

def refresh_inventory_data():
    print("Connecting to DigitalOcean MySQL database...")

    if DB_PASS is None:
        raise ValueError("BI_DB_PASS environment variable is required.")
    if SPREADSHEET_ID is None:
        raise ValueError("MTRADING_REPLANISHMENT_SPREADSHEET_ID environment variable is required.")
    
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
        query = "SELECT * FROM bi_database.vw_mtrading_store_inventory;"
        print("Executing query and fetching data...")
        df = pd.read_sql(query, cast(Any, connection))
        print(f"Successfully fetched {len(df)} rows from database.")
    finally:
        connection.close()
        print("Database connection closed.")

    print("Formatting data for Google Sheets...")
    # ဒေတာထဲတွင် ပါလာနိုင်သော datetime / date object များကို JSON serializable ဖြစ်စေရန် string သို့ ပြောင်းခြင်း
    for col in df.select_dtypes(include=['datetime64[ns]', 'object']):
        # pandas ရဲ့ datetime သို့မဟုတ် python date/datetime ပါသော columns များကို string ပုံစံသို့ ပြောင်းသည်
        try:
            df[col] = pd.to_datetime(df[col], errors=cast(Any, 'ignore'))
            if pd.api.types.is_datetime64_any_dtype(df[col]):
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
    refresh_inventory_data()