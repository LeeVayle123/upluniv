import sqlite3
import os

def check_db():
    db_path = 'database.db'
    print(f"Checking {db_path}...")
    if not os.path.exists(db_path):
        print("File does not exist.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    print("Tables found:", tables)
    
    for table in tables:
        if table.lower().startswith('bac'):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"Table {table}: {count} rows")
            if count > 0:
                cursor.execute(f"SELECT matricule, nom FROM {table} LIMIT 1")
                print("  Sample:", cursor.fetchone())
    
    conn.close()

if __name__ == "__main__":
    check_db()
