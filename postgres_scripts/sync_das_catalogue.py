#!/usr/bin/env python3
"""Run the DAS -> Supabase catalogue synchronization function.

The transformation and upserts live in Supabase in public.sync_das_catalogue().
This runner is intentionally small so cron only needs Supabase credentials.

Install:
    python3 -m venv .venv
    .venv/bin/pip install psycopg2-binary python-dotenv

Run:
    .venv/bin/python sync_das_catalogue.py

Environment variables:
    SUPABASE_DB_HOST
    SUPABASE_DB_PORT       (default: 6543)
    SUPABASE_DB_USER
    SUPABASE_DB_PASSWORD
    SUPABASE_DB_NAME       (default: postgres)
    SUPABASE_DB_SSLMODE    (default: require)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("das_catalogue_sync")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    conn = None
    try:
        conn = psycopg2.connect(
            host=required("SUPABASE_DB_HOST"),
            port=int(os.getenv("SUPABASE_DB_PORT", "6543")),
            user=required("SUPABASE_DB_USER"),
            password=required("SUPABASE_DB_PASSWORD"),
            dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
            sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
            connect_timeout=int(os.getenv("SUPABASE_CONNECT_TIMEOUT", "30")),
            application_name="das-catalogue-cron",
        )
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT public.sync_das_catalogue()")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("DAS catalogue sync returned no result")
            result: Any = row[0]
        conn.commit()
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                pass
        log.info("DAS catalogue sync completed: %s", result)
        return 0
    except Exception:
        if conn is not None:
            conn.rollback()
        log.exception("DAS catalogue sync failed; transaction rolled back")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
