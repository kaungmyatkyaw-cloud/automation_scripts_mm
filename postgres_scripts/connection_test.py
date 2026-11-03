import pymysql
import psycopg2
import urllib.parse

print("Testing MySQL Connection...")
try:
    mysql_conn = pymysql.connect(
        host="db-distribution-accounting-do-user-2718740-0.h.db.ondigitalocean.com",
        port=25060,
        user="kmkyaw",
        password="BOs5hA+bMo6UfmgYweaPJqrmD",
        database="das-db",
        connect_timeout=5
    )
    print("✅ MySQL Connection Successful!")
    mysql_conn.close()
except Exception as e:
    print(f"❌ MySQL Connection Failed: {e}")

print("\nTesting Postgres Connection (via Transaction Pooler)...")
try:
    # Password ထဲပါသော special characters များကို URL-safe အဖြစ် အလိုအလျောက် ပြောင်းပေးသည်
    raw_password = "4Q*bc3JXj!EW&Rbh"
    encoded_password = urllib.parse.quote_plus(raw_password)
    
    supabase_uri = f"postgresql://postgres.avaevgvuwomcfbjtrsbb:{encoded_password}@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
    
    pg_conn = psycopg2.connect(supabase_uri)
    print("✅ Postgres Connection Successful via URI!")
    pg_conn.close()
except Exception as e:
    print(f"❌ Connection Failed: {e}")