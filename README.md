# Automated Sale Database Update & Reporting (M-BI)

This repository contains automated data engineering and database synchronization scripts designed for daily execution via **GitHub Actions**. It handles automated database updates, SQL sync procedures, and stakeholder email reporting.

---

## 🚀 Project Overview & Architecture

* **Database Update**: Automatically synchronizes and updates product/sales metrics in the production MySQL database.
* **SQL Automation**: Executes daily staging and synchronization scripts (`daily_fs_sync.sql`) prior to running core Python pipelines.
* **Email Distribution**: Automatically dispatches reports and operational notifications to respective demand of each business unit based on scope configuration.
* **Scheduler**: Runs automatically every day via GitHub Actions workflow (`cron`).

---

## 📁 Repository Structure

```text
automation_scripts_mm/
├── .github/
│   └── workflows/
│       └── daily_db_update.yml   # GitHub Actions scheduled workflow
├── queries/
│   └── daily_fs_sync.sql         # Daily SQL staging and sync script
├── update_products_in_db.py      # Main Python script for data processing & emails
├── requirements.txt.txt          # Python package dependencies
└── README.md                     # Project documentation