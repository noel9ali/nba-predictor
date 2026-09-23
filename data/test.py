import sqlite3
import pandas as pd

conn = sqlite3.connect(r'C:\Users\noel9\Desktop\nba-predictor\data\nba.db')

tables = ['games', 'elo', 'predictions', 'features', 'bankroll']

with pd.ExcelWriter(r'C:\Users\noel9\Desktop\nba_dashboard.xlsx', engine='openpyxl') as writer:
    for table in tables:
        df = pd.read_sql(f'SELECT * FROM {table}', conn)
        df.to_excel(writer, sheet_name=table, index=False)
        print(f'{table}: {df.shape[0]} rows, {df.shape[1]} columns')
        print(df.head(2))
        print()

conn.close()
print('Done! File saved to Desktop.')