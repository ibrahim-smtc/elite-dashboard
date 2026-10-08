import os
from dotenv import load_dotenv
import psycopg

load_dotenv()
dsn = os.environ.get("DATABASE_URL")

with psycopg.connect(dsn) as cx:
    res = cx.execute("SELECT trigger_name, action_timing, event_manipulation, action_statement FROM information_schema.triggers WHERE event_object_table='booking'").fetchall()
    for r in res:
        print(r)
