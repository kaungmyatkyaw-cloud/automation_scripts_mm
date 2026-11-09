#!/bin/bash

# ==========================================
# WEEKLY AUTOMATED EMAILS & REPORTS SCRIPT
# ==========================================

# 1. Project Directory သို့ ဝင်ရောက်ခြင်း
cd /root/k_workspace/projects/automation_scripts_mm || { echo "❌ Directory not found!"; exit 1; }

# 2. Virtual Environment Python Path သတ်မှတ်ခြင်း
PYTHON="/root/k_workspace/projects/automation_scripts_mm/venv/bin/python"

# Python binary ရှိမရှိ စစ်ဆေးခြင်း
if [ ! -f "$PYTHON" ]; then
    echo "❌ Python executable not found at $PYTHON"
    exit 1
fi

echo "🚀 Starting Weekly Automated Scripts Pipeline at $(date)..."

# 3. Python ဖိုင်များကို အစဉ်လိုက် လုပ်ဆောင်ခြင်း
scripts=(
    "send_catalog_mkitchen.py"
    "send_catalog_mtrading.py"
    "send_email_mkitchen.py"
    "send_email_mkitchen_replanishment.py"
    "send_email_mkitchen_weight.py"
    "send_email_mtrading.py"
    "send_email_mtrading_replanishment.py"
    "send_email_shwezay.py"
    "send_email_shwezay_replanishment.py"
    "send_pricing_report.py"
    "send_recepay_email.py"
)

for script in "${scripts[@]}"; do
    if [ -f "$script" ]; then
        echo "----------------------------------------"
        echo "▶️ Running $script..."
        $PYTHON "$script"
        if [ $? -eq 0 ]; then
            echo "✅ Successfully executed: $script"
        else
            echo "❌ Error occurred while running: $script"
        fi
    else
        echo "⚠️ Warning: $script not found, skipping..."
    fi
done

echo "----------------------------------------"
echo "🏁 All Weekly Email Scripts Completed at $(date)."