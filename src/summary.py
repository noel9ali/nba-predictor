from sqlite3 import connect
import pandas as pd

def summarize_database(db_path, date):
    conn = connect(db_path)
    query = "SELECT * FROM games WHERE date = ?"
    df = pd.read_sql_query(query, conn, params=(date,))
    conn.close()
    return df.describe()