import sys
from app.db import session

with session() as s:
    print(s.autocommit)
    s.execute("UPDATE dim_period SET is_active=true WHERE period_id=47")
    s.commit()
