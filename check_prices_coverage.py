import sqlite3
import pandas as pd
from config import PRICES_DB_PATH

def check_db():
    conn = sqlite3.connect(PRICES_DB_PATH)
    query = "SELECT ticker, MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as row_count FROM prices_daily GROUP BY ticker LIMIT 10"
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(df)

if __name__ == "__main__":
    check_db()
