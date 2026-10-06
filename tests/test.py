import sqlite3
import pandas as pd
import time
import datetime

# read database
def read_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Example query to fetch all data from a table named 'example_table'
    cursor.execute("SELECT * FROM itin")
    rows = cursor.fetchall()
    
    data = pd.DataFrame(rows, columns=[col[0] for col in cursor.description])

    conn.close()
    return data

def itineraries_list(offsets):
    """
    Returns a list of itineraries from the database for the target dates

    """
    db_path = "flights.db"  # Replace with your database path
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    today = datetime.date.today()
    target_dates = [(today + datetime.timedelta(days=o)).isoformat() for o in offsets]

    # Now use these dates in your SQL query:
    placeholders = ','.join('?' for _ in target_dates)
    query = f"""
        SELECT itinerary_id, departure_date
        FROM itin
        WHERE departure_date IN ({placeholders})
    """
    cursor.execute(query, target_dates)
    rows = cursor.fetchall()

    itineraries = pd.DataFrame(rows, columns=[col[0] for col in cursor.description])
    conn.close()
    return itineraries




# Example usage
if __name__ == "__main__":
    db_path = "flights.db"  # Replace with your database path
    data = read_database(db_path)
    
    offsets = (
        list(range(1, 8, 1)) +
        list(range(8, 31, 2)) +
        list(range(31, 90, 4))
    )

    itineraries = itineraries_list(offsets)