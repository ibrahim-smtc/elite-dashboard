import os
from dotenv import load_dotenv
import psycopg

load_dotenv()
dsn = os.environ.get("DATABASE_URL")

with psycopg.connect(dsn) as cx:
    res = cx.execute("SELECT routine_definition FROM information_schema.routines WHERE routine_name='touch_updated_at'").fetchone()
    print(res[0])
