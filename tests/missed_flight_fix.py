import sqlite3
import datetime
from datetime import timedelta
import pandas as pd

def read_database(db_path, table_name='itin'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(f'SELECT * FROM {table_name}')
    rows = cursor.fetchall()
    
    data = pd.DataFrame(rows, columns=[col[0] for col in cursor.description])

    conn.close()
    return data

def read_parquet(parquet_path):
    return pd.read_parquet(parquet_path)



# Check missed flights
missed_itineraries = pd.read_csv('missing_itineraries.csv')



for missed in missed_itineraries['itinerary_id']:
    