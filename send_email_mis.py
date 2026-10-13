import io
import os
import smtplib
import urllib.parse
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine

# ---------------------------------------------------------
# 1. Load Environment Variables & Type Guard Validation
# ---------------------------------------------------------
load_dotenv()

SMTP_SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL")
SMTP_SENDER_PASSWORD = os.getenv("SMTP_SENDER_PASSWORD")
MIS_EMAILS = os.getenv("MIS_EMAILS")
MIS_CC = os.getenv("MIS_CC")

if not SMTP_SENDER_EMAIL or not SMTP_SENDER_PASSWORD or not MIS_EMAILS:
    raise ValueError(
        "CRITICAL ERROR: Environment variables (SMTP_SENDER_EMAIL, SMTP_SENDER_PASSWORD, MIS_EMAILS) must be set."
    )

# ---------------------------------------------------------
# 2. Database Connection Setup
# ---------------------------------------------------------
DB_HOST = "db-distribution-accounting-do-user-2718740-0.h.db.ondigitalocean.com"
DB_PORT = 25060
DB_USER = "kmkyaw"
DB_PASS = urllib.parse.quote_plus("BOs5hA+bMo6UfmgYweaPJqrmD")
DB_NAME = "bi_database"

db_url = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(db_url)

# ---------------------------------------------------------
# 3. Data Extraction Query
# ---------------------------------------------------------
SQL_QUERY = """
WITH base_sales AS (
    SELECT 
        fs.sale_datetime,
        fs.net_amount,
        YEARWEEK(fs.sale_datetime, 1) AS yw,
        DATE_FORMAT(fs.sale_datetime, '%%b') AS month_name,
        MONTH(fs.sale_datetime) AS month_num,
        CASE 
            WHEN fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND fs.branch_id = 34 THEN 'M-Kitchen'
            WHEN (fs.business_id = '84093770-29ad-4e8e-9da1-babe583c0d69' AND (TRIM(CAST(fs.branch_id AS CHAR)) != '34' OR fs.branch_id IS NULL))
                 OR (fs.business_id = '7ef7c6c0-b59d-4be9-960c-7fa573038642') THEN 'M-Trading'
            WHEN fs.business_id = 'ac4dd67c-738e-4dfe-a475-fc65f2a9ca08' THEN 'ShweZay (YGN)'
            WHEN fs.business_id = '2d393763-d5c7-42be-b345-84b7be787f10' THEN 'ShweZay (NPT)'
            WHEN fs.business_id = '1eb52cc2-7a34-43d8-b646-67cc60402916' THEN 'ShweZay (KPG)'
            ELSE NULL
        END AS business_unit_branch
    FROM fact_saless fs
    WHERE fs.sale_datetime >= '2026-01-01 00:00:00' 
      AND fs.sale_datetime <= '2026-12-31 23:59:59'
)
SELECT 
    CONCAT('W-', LPAD(MOD(yw, 100), 2, '0')) AS week_name,
    yw AS year_week_code,
    month_name,
    month_num,
    MIN(DATE(sale_datetime)) AS week_start_date,
    MAX(DATE(sale_datetime)) AS week_end_date,
    business_unit_branch,
    SUM(net_amount) AS total_sales_amount
FROM base_sales
WHERE business_unit_branch IS NOT NULL
GROUP BY 
    yw,
    month_name,
    month_num,
    business_unit_branch
ORDER BY year_week_code ASC, business_unit_branch ASC;
"""

# ---------------------------------------------------------
# 4. Helper Function: Read Text Reports & Format with Roboto Font
# ---------------------------------------------------------
def format_compact(amount):
    if amount is None or pd.isna(amount):
        return "0"
    val = float(amount)
    if abs(val) >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    elif abs(val) >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    elif abs(val) >= 1_000:
        return f"{val / 1_000:.2f}K"
    return f"{val:.2f}"


def get_text_reports_html():
    report_files = [
        ("M-Kitchen Text Report", "text_report_mkitchen.txt"),
        ("ShweZay Text Report", "text_report_shwezay.txt"),
        ("M-Trading Text Report", "text_report_mtrading.txt"),
    ]

    combined_html = """
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
    <div style="margin-top: 40px; border-top: 3px double #004085; padding-top: 20px;">
        <h2 style="color: #004085; font-size: 20px; margin-bottom: 20px; font-family: 'Roboto', sans-serif;">📝 Business Unit Operational Reports & Updates</h2>
    """

    for title, filename in report_files:
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                formatted_content = content.replace("\n", "<br>")
            except Exception as e:
                formatted_content = f"<i>Error reading file {filename}: {e}</i>"
        else:
            formatted_content = f"<i>File standard template '{filename}' not found in current directory.</i>"

        combined_html += f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 5px solid #004085; border-radius: 6px; padding: 18px; margin-bottom: 20px;">
            <h3 style="margin-top: 0; color: #1e293b; font-size: 16px; border-bottom: 1px solid #cbd5e1; padding-bottom: 8px; font-family: 'Roboto', sans-serif;">
                📌 {title}
            </h3>
            <div style="font-family: 'Roboto', sans-serif; font-size: 13.5px; color: #334155; line-height: 1.6;">
                {formatted_content}
            </div>
        </div>
        """

    combined_html += "</div>"
    return combined_html


# ---------------------------------------------------------
# 5. Extract Data & Compute Metrics
# ---------------------------------------------------------
df = pd.read_sql(SQL_QUERY, engine)

df["year_week_code"] = df["year_week_code"].astype(int)
df = df.sort_values(by=["year_week_code", "business_unit_branch"], ascending=True)

# Dynamic KPI Cards Data
total_sales_val = df["total_sales_amount"].sum()
formatted_total_sales = format_compact(total_sales_val)

df_total_weekly = (
    df.groupby(["year_week_code", "week_name"])["total_sales_amount"]
    .sum()
    .reset_index()
)
avg_weekly_sales_val = (
    df_total_weekly["total_sales_amount"].mean() if not df_total_weekly.empty else 0
)
formatted_avg_weekly = format_compact(avg_weekly_sales_val)

best_week_row = (
    df_total_weekly.sort_values(
        by="total_sales_amount", ascending=False
    ).iloc[0]
    if not df_total_weekly.empty
    else None
)
best_week_name = best_week_row["week_name"] if best_week_row is not None else "N/A"
best_week_val = (
    format_compact(best_week_row["total_sales_amount"])
    if best_week_row is not None
    else "0"
)

bu_count = df["business_unit_branch"].nunique()
top_bu_row = (
    df.groupby("business_unit_branch")["total_sales_amount"]
    .sum()
    .reset_index()
    .sort_values(by="total_sales_amount", ascending=False)
    .iloc[0]
    if not df.empty
    else None
)
top_bu_name = top_bu_row["business_unit_branch"] if top_bu_row is not None else "N/A"

# WOW Growth Rate
df_total_weekly["growth_rate"] = (
    df_total_weekly["total_sales_amount"].pct_change() * 100
)
df_total_weekly["growth_label"] = df_total_weekly["growth_rate"].apply(
    lambda x: f"{x:+.1f}%" if pd.notna(x) else "0.0%"
)

# ---------------------------------------------------------
# 6. Generate Summary Tables (BU Summary & ShweZay Breakdown)
# ---------------------------------------------------------
df_bu_summary = df.copy()
df_bu_summary["summary_group"] = df_bu_summary["business_unit_branch"].apply(
    lambda x: "ShweZay (All)" if "ShweZay" in str(x) else x
)

df_weekly_grp = (
    df_bu_summary.groupby(["summary_group", "year_week_code"])["total_sales_amount"]
    .sum()
    .reset_index()
)
grand_total_sales = df["total_sales_amount"].sum()

summary_rows = []
for grp, grp_df in df_weekly_grp.groupby("summary_group"):
    tot_sales = grp_df["total_sales_amount"].sum()
    share_pct = (
        (tot_sales / grand_total_sales * 100) if grand_total_sales > 0 else 0
    )
    avg_week = grp_df["total_sales_amount"].mean()
    best_week = grp_df["total_sales_amount"].max()
    worst_week = grp_df["total_sales_amount"].min()

    summary_rows.append(
        {
            "Business Unit": grp,
            "Total Sales": tot_sales,
            "Share": share_pct,
            "Avg/Week": avg_week,
            "Best Week": best_week,
            "Worst Week": worst_week,
        }
    )

summary_df = pd.DataFrame(summary_rows).sort_values(
    by="Total Sales", ascending=False
)

summary_table_html = """
<div style="overflow-x: auto; width: 100%; margin-bottom: 25px;">
    <h3 style="color: #333333; margin-top: 25px; border-left: 4px solid #004085; padding-left: 8px;">
        📋 Business Unit Performance Summary
    </h3>
    <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        <thead>
            <tr style="background-color: #1f2937; color: #ffffff; font-weight: bold; height: 38px;">
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Business Unit</th>
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Total Sales</th>
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Share</th>
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Avg/Week</th>
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Best Week</th>
                <th style="padding: 10px; border: 1px solid #374151; text-align: center;">Worst Week</th>
            </tr>
        </thead>
        <tbody>
"""

for _, row in summary_df.iterrows():
    summary_table_html += f"""
            <tr style="background-color: #f9fafb; border-bottom: 1px solid #e5e7eb; color: #111827;">
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center; font-weight: 500;">{row['Business Unit']}</td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center;">{format_compact(row['Total Sales'])}</td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center;">{row['Share']:.1f}%</td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center;">{format_compact(row['Avg/Week'])}</td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center;">{format_compact(row['Best Week'])}</td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center;">{format_compact(row['Worst Week'])}</td>
            </tr>
    """

total_avg_week = (
    df_total_weekly["total_sales_amount"].mean()
    if not df_total_weekly.empty
    else 0
)
total_best_week = (
    df_total_weekly["total_sales_amount"].max()
    if not df_total_weekly.empty
    else 0
)
total_worst_week = (
    df_total_weekly["total_sales_amount"].min()
    if not df_total_weekly.empty
    else 0
)

summary_table_html += f"""
            <tr style="background-color: #f3f4f6; font-weight: bold; color: #000000; border-top: 2px solid #1f2937;">
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">Total</td>
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">{format_compact(grand_total_sales)}</td>
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">100.0%</td>
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">{format_compact(total_avg_week)}</td>
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">{format_compact(total_best_week)}</td>
                <td style="padding: 10px; border: 1px solid #d1d5db; text-align: center;">{format_compact(total_worst_week)}</td>
            </tr>
        </tbody>
    </table>
</div>
"""

# ShweZay Regional Table
df_shwezay = df[df["business_unit_branch"].str.contains("ShweZay", na=False)].copy()

if not df_shwezay.empty:
    sz_weekly_grp = (
        df_shwezay.groupby(["business_unit_branch", "year_week_code"])[
            "total_sales_amount"
        ]
        .sum()
        .reset_index()
    )

    sz_rows = []
    for reg, reg_df in sz_weekly_grp.groupby("business_unit_branch"):
        tot_sales = reg_df["total_sales_amount"].sum()
        share_pct = (
            (tot_sales / grand_total_sales * 100) if grand_total_sales > 0 else 0
        )
        avg_week = reg_df["total_sales_amount"].mean()
        best_week = reg_df["total_sales_amount"].max()
        worst_week = reg_df["total_sales_amount"].min()

        sz_rows.append(
            {
                "ShweZay Region": reg,
                "Total Sales": tot_sales,
                "Share": share_pct,
                "Avg/Week": avg_week,
                "Best Week": best_week,
                "Worst Week": worst_week,
            }
        )

    sz_df = pd.DataFrame(sz_rows).sort_values(by="Total Sales", ascending=False)

    shwezay_table_html = """
    <div style="overflow-x: auto; width: 100%; margin-bottom: 25px;">
        <h3 style="color: #333333; margin-top: 25px; border-left: 4px solid #7c2d12; padding-left: 8px;">
            🏪 ShweZay Regional Breakdown
        </h3>
        <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            <thead>
                <tr style="background-color: #7c2d12; color: #ffffff; font-weight: bold; height: 38px;">
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">ShweZay Region</th>
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">Total Sales</th>
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">Share</th>
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">Avg/Week</th>
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">Best Week</th>
                    <th style="padding: 10px; border: 1px solid #7c2d12; text-align: center;">Worst Week</th>
                </tr>
            </thead>
            <tbody>
    """

    for _, row in sz_df.iterrows():
        shwezay_table_html += f"""
                <tr style="background-color: #fffbeb; border-bottom: 1px solid #fde68a; color: #111827;">
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center; font-weight: 500;">{row['ShweZay Region']}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(row['Total Sales'])}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{row['Share']:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(row['Avg/Week'])}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(row['Best Week'])}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(row['Worst Week'])}</td>
                </tr>
        """

    sz_tot_sales = df_shwezay["total_sales_amount"].sum()
    sz_share_pct = (
        (sz_tot_sales / grand_total_sales * 100) if grand_total_sales > 0 else 0
    )
    df_sz_total_weekly = df_shwezay.groupby("year_week_code")[
        "total_sales_amount"
    ].sum()
    sz_avg_week = (
        df_sz_total_weekly.mean() if not df_sz_total_weekly.empty else 0
    )
    sz_best_week = (
        df_sz_total_weekly.max() if not df_sz_total_weekly.empty else 0
    )
    sz_worst_week = (
        df_sz_total_weekly.min() if not df_sz_total_weekly.empty else 0
    )

    shwezay_table_html += f"""
                <tr style="background-color: #fef3c7; font-weight: bold; color: #000000; border-top: 2px solid #7c2d12;">
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">ShweZay Total</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(sz_tot_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{sz_share_pct:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(sz_avg_week)}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(sz_best_week)}</td>
                    <td style="padding: 10px; border: 1px solid #fde68a; text-align: center;">{format_compact(sz_worst_week)}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
else:
    shwezay_table_html = ""

# ---------------------------------------------------------
# 7. Generate Plotly Charts
# ---------------------------------------------------------
def fig_to_bytes(fig):
    return fig.to_image(format="png", width=1200, height=480, engine="kaleido")


color_map = {
    "M-Kitchen": "#6366F1",
    "M-Trading": "#EF4444",
    "ShweZay (KPG)": "#10B981",
    "ShweZay (NPT)": "#8B5CF6",
    "ShweZay (YGN)": "#F97316",
}

# Chart 1: Overall Weekly Sales Trend
df_total_weekly["compact_amt"] = df_total_weekly["total_sales_amount"].apply(
    format_compact
)
fig1 = px.line(
    df_total_weekly,
    x="week_name",
    y="total_sales_amount",
    text="compact_amt",
    title="Overall Weekly Sales Trend",
    markers=True,
    template="plotly_white",
)
fig1.update_traces(textposition="top center", line_color="#004085")
fig1.update_xaxes(tickangle=-90)

# Chart 2: WOW Sales Growth Rate (%)
colors = [
    "#28a745" if val >= 0 else "#dc3545"
    for val in df_total_weekly["growth_rate"].fillna(0)
]
fig2 = go.Figure()
fig2.add_trace(
    go.Bar(
        x=df_total_weekly["week_name"],
        y=df_total_weekly["growth_rate"],
        text=df_total_weekly["growth_label"],
        textposition="outside",
        textfont=dict(size=12, color="#111111", family="Roboto, Arial"),
        marker_color=colors,
        name="Growth Rate %",
    )
)
fig2.update_layout(
    title=dict(text="Week-over-Week (WOW) Sales Growth Rate (%)", font=dict(size=18)),
    template="plotly_white",
    yaxis=dict(
        title=dict(text="Growth Rate (%)", font=dict(size=14)),
        tickfont=dict(size=12),
    ),
    xaxis=dict(
        title=dict(text="Week", font=dict(size=14)),
        tickfont=dict(size=13),
        tickangle=-90,
    ),
    margin=dict(t=60, b=80, l=50, r=50),
)

# Chart 3: Monthly Sales by Business Unit
df_monthly_bu = (
    df.groupby(["month_num", "month_name", "business_unit_branch"])[
        "total_sales_amount"
    ]
    .sum()
    .reset_index()
)
df_monthly_bu = df_monthly_bu.sort_values(by="month_num")

fig3 = px.bar(
    df_monthly_bu,
    x="month_name",
    y="total_sales_amount",
    color="business_unit_branch",
    barmode="group",
    title="🗓️ Monthly Sales by Business Unit",
    template="plotly_white",
    color_discrete_map=color_map,
    labels={
        "month_name": "Month",
        "total_sales_amount": "Sales",
        "business_unit_branch": "Business Unit",
    },
)

# ---------------------------------------------------------
# Chart 4: Weekly Sales Trend By Business Unit (FIXED)
# ---------------------------------------------------------
# 1. Unique week_name များကို year_week_code အစဉ်အတိုင်း
sorted_weeks = df.sort_values(by="year_week_code")["week_name"].unique().tolist()

fig4 = px.line(
    df,
    x="week_name",
    y="total_sales_amount",
    color="business_unit_branch",
    markers=True,
    title="Weekly Sales Trend by Business Unit",
    template="plotly_white",
    color_discrete_map=color_map,
)

# 2. X-axis Category Order ကို sorted_weeks အတိုင်း Explicit သတ်မှတ်
fig4.update_xaxes(
    tickangle=-90,
    categoryorder="array",
    categoryarray=sorted_weeks
)

# Chart 5: Share of Total Sales
df_bu_total = (
    df.groupby("business_unit_branch")["total_sales_amount"].sum().reset_index()
)
fig5 = px.pie(
    df_bu_total,
    values="total_sales_amount",
    names="business_unit_branch",
    title="Share of Total Sales",
    hole=0.4,
    color="business_unit_branch",
    color_discrete_map=color_map,
)

img1_bytes = fig_to_bytes(fig1)
img2_bytes = fig_to_bytes(fig2)
img3_bytes = fig_to_bytes(fig3)
img4_bytes = fig_to_bytes(fig4)
img5_bytes = fig_to_bytes(fig5)

# Heatmap Matrix
heatmap_pivot = df.pivot_table(
    index="business_unit_branch",
    columns="week_name",
    values="total_sales_amount",
    aggfunc="sum",
    fill_value=0,
)

heatmap_html = '<div style="overflow-x: auto; width: 100%;">'
heatmap_html += '<table border="1" style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; font-size: 12px; text-align: center; border: 1px solid #dee2e6;">'
heatmap_html += (
    '<tr style="background-color: #004085; color: white;"><th>Business Unit</th>'
)
for col in heatmap_pivot.columns:
    heatmap_html += f'<th style="padding: 8px;">{col}</th>'
heatmap_html += "</tr>"

for index, row in heatmap_pivot.iterrows():
    heatmap_html += f'<tr><td style="text-align: left; font-weight: bold; padding: 8px; background-color: #f8f9fa;">{index}</td>'
    for val in row:
        formatted_val = format_compact(val)
        max_val = heatmap_pivot.max().max()
        intensity = int((val / max_val) * 80) if max_val > 0 else 0
        bg_style = (
            f"background-color: rgba(40, 167, 69, 0.{intensity:02d});"
            if val > 0
            else ""
        )
        heatmap_html += f'<td style="padding: 8px; {bg_style}">{formatted_val}</td>'
    heatmap_html += "</tr>"
heatmap_html += "</table></div>"

text_reports_html = get_text_reports_html()

# ---------------------------------------------------------
# 8. Construct Full Email Body
# ---------------------------------------------------------
html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 10px; width: 100% !important; }}
        .container {{ width: 100% !important; max-width: 100% !important; background: #ffffff; margin: 0 auto; padding: 20px; box-sizing: border-box; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        h2 {{ color: #004085; border-bottom: 2px solid #004085; padding-bottom: 8px; margin-top: 0; }}
        h3 {{ color: #333333; margin-top: 25px; border-left: 4px solid #004085; padding-left: 8px; }}
        .kpi-container {{ width: 100%; margin-bottom: 25px; border-collapse: collapse; }}
        .kpi-card {{ background: #ffffff; padding: 15px; text-align: left; vertical-align: middle; width: 25%; }}
        .kpi-title {{ font-size: 13px; color: #6c757d; font-weight: 600; margin-bottom: 6px; }}
        .kpi-value {{ font-size: 26px; font-weight: bold; color: #111111; }}
        .img-container {{ text-align: center; margin: 15px 0; width: 100%; }}
        .img-container img {{ width: 100% !important; max-width: 100% !important; height: auto !important; border: 1px solid #ddd; border-radius: 4px; display: block; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>📊 Weekly Sales Performance Executive Report</h2>

        <table class="kpi-container">
            <tr>
                <td class="kpi-card">
                    <div class="kpi-title">💰 Total Sales</div>
                    <div class="kpi-value">{formatted_total_sales}</div>
                </td>
                <td class="kpi-card">
                    <div class="kpi-title">🗓️ Avg Weekly Sales</div>
                    <div class="kpi-value">{formatted_avg_weekly}</div>
                </td>
                <td class="kpi-card">
                    <div class="kpi-title">🏆 Best Week ({best_week_name})</div>
                    <div class="kpi-value">{best_week_val}</div>
                </td>
                <td class="kpi-card">
                    <div class="kpi-title">🏢 Business Units</div>
                    <div class="kpi-value">{bu_count} | Top: {top_bu_name}</div>
                </td>
            </tr>
        </table>

        {summary_table_html}

        {shwezay_table_html}

        <h3>1. Overall Weekly Sale Trend</h3>
        <div class="img-container"><img src="cid:chart1" alt="Weekly Sales Trend"/></div>

        <h3>2. Week-over-Week (WOW) Sales Growth Rate (%)</h3>
        <div class="img-container"><img src="cid:chart2" alt="WOW Growth Rate"/></div>

        <h3>3. Monthly Sales by Business Unit</h3>
        <div class="img-container"><img src="cid:chart3" alt="Monthly Sales by Business Unit"/></div>

        <h3>4. Weekly Sales Trend By Business Unit</h3>
        <div class="img-container"><img src="cid:chart4" alt="Sales Trend By BU"/></div>

        <h3>5. Share of Total Sales</h3>
        <div class="img-container"><img src="cid:chart5" alt="Share of Total Sales"/></div>

        <h3>6. Business Unit x Week Sales Matrix Heatmap</h3>
        {heatmap_html}

        <!-- Text Reports with Roboto Font -->
        {text_reports_html}

        <p style="font-size: 11px; color: #777; margin-top: 30px; text-align: center;">
            This is an automated performance report. Complete weekly extract attached in CSV.
        </p>
    <!-- HTML Body ထဲတွင် ထည့်သွင်းရန် -->
    <div style="text-align: center; margin: 30px 0;">
        <a href="https://datastudio.google.com/reporting/6331536e-d8bf-4d31-8b5e-18fdf5e0831c/page/PFw9F" 
        target="_blank" 
        style="background-color: #004085; color: #ffffff; padding: 12px 24px; text-decoration: none; font-weight: bold; border-radius: 5px; display: inline-block; font-family: Arial, sans-serif; font-size: 14px;">
            🔗 Open Interactive Looker Studio Dashboard
        </a>
    </div>
    </div> 
</html>
"""

# ---------------------------------------------------------
# 9. Send Email via SMTP
# ---------------------------------------------------------
msg = MIMEMultipart("mixed")
msg["From"] = SMTP_SENDER_EMAIL
msg["To"] = MIS_EMAILS
if MIS_CC:
    msg["Cc"] = MIS_CC
msg["Subject"] = "📈 Weekly Sales Analysis (MIS Report)"

msg_related = MIMEMultipart("related")
msg.attach(msg_related)
msg_related.attach(MIMEText(html_body, "html"))

chart_list = [
    (img1_bytes, "chart1", "01_overall_weekly_sales_trend.png"),
    (img2_bytes, "chart2", "02_wow_sales_growth_rate.png"),
    (img3_bytes, "chart3", "03_monthly_sales_by_bu.png"),
    (img4_bytes, "chart4", "04_weekly_sales_trend_by_bu.png"),
    (img5_bytes, "chart5", "05_share_of_total_sales.png"),
]

for img_bytes, cid_name, filename in chart_list:
    inline_img = MIMEImage(img_bytes, _subtype="png")
    inline_img.add_header("Content-ID", f"<{cid_name}>")
    inline_img.add_header("Content-Disposition", "inline", filename=filename)
    msg_related.attach(inline_img)

for img_bytes, _, filename in chart_list:
    attached_img = MIMEImage(img_bytes, _subtype="png")
    attached_img.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attached_img)

csv_buffer = io.StringIO()
df.to_csv(csv_buffer, index=False)
csv_attachment = MIMEApplication(csv_buffer.getvalue(), _subtype="csv")
csv_attachment.add_header(
    "Content-Disposition",
    "attachment",
    filename="weekly_sales_report_extract.csv",
)
msg.attach(csv_attachment)

try:
    cc_recipients = (
        [addr.strip() for addr in MIS_CC.split(",") if addr.strip()]
        if MIS_CC
        else []
    )
    recipients: list[str] = [MIS_EMAILS] + cc_recipients

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(SMTP_SENDER_EMAIL, SMTP_SENDER_PASSWORD)
        server.sendmail(SMTP_SENDER_EMAIL, recipients, msg.as_string())
    print("Email sent successfully with Roboto font applied to text reports!")
except Exception as e:
    print(f"Failed to send email: {e}")