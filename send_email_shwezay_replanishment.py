import io
import os
import smtplib
import time
import warnings
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

# Google Sheets Imports
import gspread
import pandas as pd
import pymysql
from dotenv import load_dotenv
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
GOOGLE_SHEET_ID = "1B9kBhu6Ebu7Yw2j2PKTFsXQ6K3e6RhAgO8fHRCFP2g4"
SERVICE_ACCOUNT_FILE = os.path.join(CURRENT_DIR, "service_account_update.json")

# Multi-Branch Mapping Configuration with Display Names
BRANCH_CONFIG = {
    "npt": {
        "b_id": "2d393763-d5c7-42be-b345-84b7be787f10",
        "display": "Shwe Zay NPT",
        "env_key": "shwezay_npt",
    },
    "ygn": {
        "b_id": "ac4dd67c-738e-4dfe-a475-fc65f2a9ca08",
        "display": "Shwe Zay YGN",
        "env_key": "shwezay_ygn",
    },
    "kpg": {
        "b_id": "1eb52cc2-7a34-43d8-b646-67cc60402916",
        "display": "Shwe Zay KPG",
        "env_key": "shwezay_kpg",
    },
}

# Email Configuration
SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD", "")

cc_receivers_raw = os.getenv("testing_cc", "")
CC_EMAILS = [
    email.strip() for email in cc_receivers_raw.split(",") if email.strip()
]

# COLOR PALETTE FOR REPLENISHMENT STATUS
COLOR_SHORTAGE = "#ef4444"  # Red
COLOR_URGENT = "#f97316"  # Orange
COLOR_IDENTIFIED = "#10b981"  # Green
COLOR_NO_NEED = "#64748b"  # Slate Gray
COLOR_PRIMARY = "#004b87"


# ==========================================
# HELPER FUNCTION: GET DYNAMIC RECEIVERS BY REGION
# ==========================================
def get_receivers_for_branch(branch_env_key: str) -> list:
    """Combines common shwezay_email with region-specific email addresses from .env"""
    common_emails_raw = os.getenv("shwezay_email", "")
    region_emails_raw = os.getenv(branch_env_key, "")

    common_emails = [
        email.strip() for email in common_emails_raw.split(",") if email.strip()
    ]
    region_emails = [
        email.strip() for email in region_emails_raw.split(",") if email.strip()
    ]

    # Combine and remove duplicates while preserving order
    combined_emails = list(dict.fromkeys(common_emails + region_emails))
    return combined_emails


# ==========================================
# HELPER FUNCTION: GET MYSQL QUERY FOR BRANCH
# ==========================================
def get_replenishment_query(business_id: str) -> str:
    """Uses Subqueries to calculate inventory replenishment, Masterdata Alerts, and Estimated Weekly Losses"""
    return f"""
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
            wh.name AS warehouse_name,
            p.sku,
            p.name AS product_name,
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
            
            -- Actual Margin Percentage (Gross Margin %)
            CASE 
                WHEN p.sales_price IS NULL OR p.sales_price = 0 OR lp.last_purchase_cost IS NULL THEN NULL
                ELSE ROUND(((p.sales_price - lp.last_purchase_cost) / p.sales_price) * 100, 2)
            END AS actual_margin_percentage

        FROM products p
        CROSS JOIN warehouses wh
        
        -- Subquery 1: Sales Summary (POS)
        LEFT JOIN (
            SELECT 
                posi.warehouse_id,
                posd.product_id,
                SUM(posd.detail_qty) AS total_sales_qty,
                SUM(posd.detail_qty) / 4.0 AS avg_weekly_sales
            FROM pos_checkout_details posd
            JOIN pos_checkout_invoice_payments posi ON posi.id = posd.pos_checkout_invoice_payment_id
            WHERE posi.business_id = '{business_id}'
              AND posi.checkout_date >= DATE_SUB(NOW(), INTERVAL 28 DAY)
              AND posi.current_status != 'Void'
            GROUP BY posi.warehouse_id, posd.product_id
        ) sls ON sls.product_id = p.id AND sls.warehouse_id = wh.id

        -- Subquery 2: Stock Summary
        LEFT JOIN (
            SELECT 
                warehouse_id,
                product_id,
                SUM(current_qty) AS total_current_stock,
                COUNT(DISTINCT batch_number) AS active_batches
            FROM stock_summaries
            WHERE business_id = '{business_id}'
            GROUP BY warehouse_id, product_id
        ) stk ON stk.product_id = p.id AND stk.warehouse_id = wh.id

        -- Subquery 3: Last Purchased Batch & Cost
        LEFT JOIN (
            SELECT 
                bd.product_id,
                b.warehouse_id,
                bd.batch_number AS last_purchased_batch,
                bd.detail_unit_rate AS last_purchase_cost,
                b.bill_date AS last_purchase_date,
                ROW_NUMBER() OVER(
                    PARTITION BY bd.product_id, b.warehouse_id 
                    ORDER BY b.bill_date DESC, b.id DESC
                ) as rn
            FROM bill_details bd
            INNER JOIN bills b ON bd.bill_id = b.id
            WHERE b.business_id = '{business_id}'
              AND b.current_status NOT IN ('Draft', 'Void')
        ) lp ON lp.product_id = p.id AND lp.warehouse_id = wh.id AND lp.rn = 1

        -- Category Joins
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        LEFT JOIN product_categories pc1 ON pc.parent_category_id = pc1.id
        LEFT JOIN product_categories pc2 ON pc1.parent_category_id = pc2.id

        WHERE p.business_id = '{business_id}'
          AND wh.business_id = '{business_id}'
          AND (COALESCE(stk.total_current_stock, 0) > 0 OR COALESCE(sls.avg_weekly_sales, 0) > 0)
    ) cm
    -- Subquery 4: Expiry Alert Check
    LEFT JOIN (
        SELECT 
            bd.product_id,
            SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) <= 0 THEN bd.detail_qty ELSE 0 END) AS red_qty,
            SUM(CASE WHEN DATEDIFF(bd.expiry_date, CURDATE()) > 0 AND DATEDIFF(bd.expiry_date, CURDATE()) <= 14 THEN bd.detail_qty ELSE 0 END) AS orange_qty
        FROM bill_details AS bd
        INNER JOIN bills AS bill ON bd.bill_id = bill.id
        WHERE bd.expiry_date IS NOT NULL
          AND bill.business_id = '{business_id}'
          AND bill.current_status != 'Void'
        GROUP BY bd.product_id
    ) AS exp ON exp.product_id IN (
        SELECT id FROM products WHERE sku = cm.sku AND business_id = '{business_id}'
    )
    ORDER BY weekly_revenue_loss DESC;
    """


# ==========================================
# HELPER FUNCTION: GET ALERT STYLING
# ==========================================
def get_alert_style(alert_status: str) -> tuple:
    """Returns background and text color matching the table alert column badges."""
    if alert_status == "OK":
        return "#e6f4ea", "#137333"  # Green
    elif "Orange" in alert_status or "Near Expiry" in alert_status:
        return "#feefe3", "#b06000"  # Orange
    else:
        return "#fce8e6", "#c5221f"  # Red


# ==========================================
# HELPER FUNCTION: UPLOAD TO GOOGLE SHEETS
# ==========================================
def update_google_sheet(df: pd.DataFrame, store_display_name: str):
    """Updates Google Sheet with 1 sheet per store, excluding cost/margin columns and converting dates to string"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"⚠️ Service account file not found at {SERVICE_ACCOUNT_FILE}. Skipping Google Sheet update."
        )
        return

    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=scope
        )
        client = gspread.authorize(creds)  # type: ignore

        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

        # Columns to exclude as per request
        excluded_cols = [
            "last_purchase_cost",
            "actual_margin_amount",
            "actual_margin_percentage",
            "weekly_margin_loss",
        ]
        sheet_df = df.drop(
            columns=[col for col in excluded_cols if col in df.columns],
            errors="ignore",
        ).copy()

        # Convert datetime/date objects to string
        for col in sheet_df.select_dtypes(
            include=["object", "datetime64", "datetimetz"]
        ).columns:
            sheet_df[col] = (
                sheet_df[col].astype(str).replace(["NaT", "None", "nan"], "")
            )

        # Select worksheet or create if not exists
        try:
            worksheet = spreadsheet.worksheet(store_display_name)
            worksheet.clear()
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=store_display_name, rows=1000, cols=30
            )

        data_to_upload = [
            sheet_df.columns.tolist()
        ] + sheet_df.fillna("").values.tolist()
        worksheet.update(data_to_upload)
        print(
            f"✅ Google Sheet updated successfully for [{store_display_name}]!"
        )

    except Exception as e:
        print(
            f"❌ Failed to update Google Sheet for [{store_display_name}]: {str(e)}"
        )


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
    cc_receivers: Optional[list] = None,
):
    if df.empty:
        print(
            f"⚠️ Replenishment DataFrame for {store_display_name} is empty. Skipping email."
        )
        return

    cc_list = cc_receivers if cc_receivers is not None else []

    # Filter out "No need"
    needed_df = df[
        df["stock_status"].str.contains(
            "1. Shortage|2. Urgent need|3. Identified need",
            case=False,
            regex=True,
        )
    ].copy()

    # Sort explicitly by weekly_revenue_loss descending
    needed_df = needed_df.sort_values(
        by="weekly_revenue_loss", ascending=False
    )

    # ---------------------------------------------------------
    # SECTION 1: CALCULATIONS & SUMMARIES
    # ---------------------------------------------------------
    shortage_count = len(
        df[df["stock_status"].str.contains("Shortage", case=False)]
    )
    urgent_count = len(
        df[df["stock_status"].str.contains("Urgent need", case=False)]
    )
    identified_count = len(
        df[df["stock_status"].str.contains("Identified need", case=False)]
    )
    total_propositions = len(needed_df)

    # Masterdata Alert Status Counts
    alerts_df = df[df["MasterdataAlert"] != "OK"]
    alert_counts = alerts_df["MasterdataAlert"].value_counts()

    if not alert_counts.empty:
        alert_summary_items = []
        for alert_name, count in alert_counts.items():
            bg_col, text_col = get_alert_style(str(alert_name))
            badge_html = (
                f"<span style='background-color: {bg_col}; color: {text_col}; "
                f"padding: 3px 6px; border-radius: 4px; font-weight: bold; font-size: 11px;'>"
                f"{alert_name}</span>"
            )
            alert_summary_items.append(
                f"<li style='margin-bottom: 6px;'>{badge_html} : <b>{count} SKUs</b></li>"
            )
        alert_summary_html = "".join(alert_summary_items)
    else:
        ok_bg, ok_text = get_alert_style("OK")
        alert_summary_html = (
            f"<li style='margin-bottom: 6px;'>"
            f"<span style='background-color: {ok_bg}; color: {ok_text}; "
            f"padding: 3px 6px; border-radius: 4px; font-weight: bold; font-size: 11px;'>OK</span> "
            f": <b>All Masterdata OK (0 Alerts)</b></li>"
        )

    # Total Weekly Revenue Loss & Loss Margin % Calculation
    loss_skus_df = needed_df[needed_df["weekly_revenue_loss"] > 0]
    total_loss_skus = len(loss_skus_df)
    total_loss_amount = needed_df["weekly_revenue_loss"].sum()
    total_margin_loss_amount = needed_df["weekly_margin_loss"].sum()

    # Calculate Total Loss Margin % (Safeguard against division by zero)
    if total_loss_amount > 0:
        total_loss_margin_pct = (total_margin_loss_amount / total_loss_amount) * 100
        margin_pct_str = f"{total_loss_margin_pct:.1f}%"
    else:
        margin_pct_str = "0.0%"

    # ---------------------------------------------------------
    # SECTION 2: TABLE ROWS GENERATION
    # ---------------------------------------------------------
    table_rows_html = ""
    for idx, row in needed_df.iterrows():
        status_text = row["stock_status"]
        if "Shortage" in status_text:
            badge_color = COLOR_SHORTAGE
            clean_status = "Shortage"
        elif "Urgent" in status_text:
            badge_color = COLOR_URGENT
            clean_status = "Urgent need"
        else:
            badge_color = COLOR_IDENTIFIED
            clean_status = "Identified need"

        alert_status = row.get("MasterdataAlert", "OK")
        alert_bg, alert_color = get_alert_style(alert_status)

        last_cost = (
            f"{row['last_purchase_cost']:,.0f}"
            if pd.notnull(row["last_purchase_cost"])
            else "N/A"
        )
        margin_amt = (
            f"{row['actual_margin_amount']:,.0f}"
            if pd.notnull(row["actual_margin_amount"])
            else "N/A"
        )
        margin_pct = (
            f"{row['actual_margin_percentage']:.1f}%"
            if pd.notnull(row["actual_margin_percentage"])
            else "N/A"
        )
        rev_loss = (
            f"{row['weekly_revenue_loss']:,.0f}"
            if pd.notnull(row["weekly_revenue_loss"])
            else "0"
        )
        mgn_loss = (
            f"{row['weekly_margin_loss']:,.0f}"
            if pd.notnull(row["weekly_margin_loss"])
            else "0"
        )

        table_rows_html += f"""
        <tr>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; white-space: nowrap;">
                <span style="background-color: {badge_color}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">
                    {clean_status}
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
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; white-space: nowrap;">
                <span style="background-color: {alert_bg}; color: {alert_color}; padding: 3px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;">
                    {alert_status}
                </span>
            </td>
            <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600; color: #16a34a;">{margin_pct}</td>
        </tr>
        """

    # Email Subject
    email_subject = (
        f"Shwe Zay {store_code.upper()} report - Replenishment - {date_str}"
    )

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
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
          }}
          .summary-box {{
            flex: 1;
            min-width: 240px;
          }}
          .summary-box-bordered {{
            flex: 1;
            min-width: 240px;
            border-left: 2px solid #e2e8f0;
            padding-left: 20px;
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
            
            <!-- Stock Status Breakdown -->
            <div class="summary-box">
              <b style="color: #004b87; font-size: 13.5px;">📦 Stock Status Overview</b>
              <ul style="margin: 8px 0 0 0; padding-left: 18px; font-size: 13px; list-style-type: square;">
                <li style="color: {COLOR_SHORTAGE}; margin-bottom: 4px;">
                  🚨 <b>Shortage:</b> <span style="color: #1e293b; font-weight: 600;">{shortage_count} SKUs</span>
                </li>
                <li style="color: {COLOR_URGENT}; margin-bottom: 4px;">
                  ⚠️ <b>Urgent need:</b> <span style="color: #1e293b; font-weight: 600;">{urgent_count} SKUs</span>
                </li>
                <li style="color: {COLOR_IDENTIFIED};">
                  ✅ <b>Identified need:</b> <span style="color: #1e293b; font-weight: 600;">{identified_count} SKUs</span>
                </li>
              </ul>
            </div>

            <!-- Total Revenue Loss Summary (With Total Margin Loss % Added) -->
            <div class="summary-box-bordered">
              <b style="color: #004b87; font-size: 13.5px;">💰 Total Weekly Revenue Loss</b>
              <div style="margin-top: 8px;">
                <p style="margin: 0; color: #dc2626; font-weight: 800; font-size: 18px;">
                  MMK {total_loss_amount:,.0f}
                </p>
                <p style="margin: 4px 0 0 0; color: #d97706; font-weight: 700; font-size: 13px;">
                  Weekly Margin Loss: MMK {total_margin_loss_amount:,.0f} ({margin_pct_str})
                </p>
                <p style="margin: 4px 0 0 0; color: #64748b; font-size: 12px; font-weight: 600;">
                  Impacts <b>{total_loss_skus} SKUs</b> needing action
                </p>
              </div>
            </div>

            <!-- Alert Status Summary -->
            <div class="summary-box-bordered">
              <b style="color: #004b87; font-size: 13.5px;">🚨 Alert Status Summary</b>
              <ul style="margin: 8px 0 0 0; padding-left: 0; font-size: 12.5px; list-style: none;">
                {alert_summary_html}
              </ul>
            </div>

          </div>

          <!-- SECTION 2: DETAILED REPLENISHMENT PROPOSITIONS -->
          <div class="section-title">2. Detailed Replenishment Propositions ({total_propositions} SKUs - Sorted by Weekly Revenue Loss)</div>
          <div class="table-responsive">
            <table class="styled-table">
              <thead>
                <tr>
                  <th>Status</th>
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
                  <th>Alert Status</th>
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
            4. <b>Estimated Weekly Losses:</b> <code>Weekly Revenue Loss = Avg Sales/Wk × Selling Price</code> | <code>Weekly Margin Loss = Avg Sales/Wk × Margin Amount</code><br/>
            5. <b>Gross Margin %:</b> <code>((Selling Price - Last Cost) / Selling Price) × 100</code><br/><br/>
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

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg["Subject"] = email_subject
    msg.attach(MIMEText(html_body, "html"))

    # Attach CSV Backup
    csv_file_name = f"replenishment_{store_code}_{date_str}.csv"
    csv_path = os.path.join(CURRENT_DIR, csv_file_name)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    if os.path.exists(csv_path):
        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", f"attachment; filename={csv_file_name}"
        )
        msg.attach(part)

    all_recipients = receivers + cc_list

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
    print(f"📧 Replenishment Email sent successfully for [{store_display_name}] to {receivers}!")


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
if __name__ == "__main__":
    print("🔄 Starting ShweZay Multi-Store Replenishment Email Pipeline...")

    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset="utf8mb4",
        )

        current_date_str = datetime.now().strftime("%Y-%m-%d")

        # Iterate through each store (NPT, YGN, KPG)
        for store_code, store_info in BRANCH_CONFIG.items():
            b_id = store_info["b_id"]
            display_name = store_info["display"]
            env_key = store_info["env_key"]

            # Dynamic Email Receivers Mapping
            branch_receivers = get_receivers_for_branch(env_key)

            print(f"\n🚀 Running Replenishment Pipeline for [{display_name}]...")

            sql_query = get_replenishment_query(b_id)
            store_df = pd.read_sql(sql_query, connection)  # type: ignore

            if store_df.empty:
                print(f"⚠️ No inventory/sales data found for [{display_name}].")
                continue

            # 1. Send Email with regional receivers
            send_replenishment_email(
                df=store_df,
                store_display_name=display_name,
                store_code=store_code,
                date_str=current_date_str,
                sender=SENDER_EMAIL,
                password=SENDER_PASSWORD,
                receivers=branch_receivers,
                cc_receivers=CC_EMAILS,
            )

            # 2. Update Google Sheet
            update_google_sheet(store_df, display_name)

        connection.close()
        print(
            "\n🏁 All Store Replenishment Emails & Google Sheet Updates Processed Successfully!"
        )

    except Exception as e:
        print(f"❌ Critical Pipeline Failure: {repr(e)}")