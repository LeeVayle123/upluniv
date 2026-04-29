import sqlite3
import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

def update_database():
    print("Starting database update...")
    
    # 1. Update SQLite
    if os.path.exists('database.db'):
        try:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE auditoriums 
                SET radius_m = 20, tolerance_m = 40, latitude = -11.673, longitude = 27.489
                WHERE code = 'IF-102'
            """)
            if cursor.rowcount > 0:
                print(f"SQLite: Successfully updated IF-102 ({cursor.rowcount} row affected).")
            else:
                print("SQLite: IF-102 not found in auditoriums table.")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"SQLite Error: {e}")
    else:
        print("SQLite: database.db not found.")

    # 2. Update MySQL
    try:
        from db_config import host, user, password, database as mysql_db
        import mysql.connector
        
        if host:
            conn = mysql.connector.connect(
                host=host, user=user, password=password, database=mysql_db
            )
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE auditoriums 
                SET radius_m = 20, tolerance_m = 40, latitude = -11.673, longitude = 27.489
                WHERE code = 'IF-102'
            """)
            if cursor.rowcount > 0:
                print(f"MySQL: Successfully updated IF-102 ({cursor.rowcount} row affected).")
            else:
                print("MySQL: IF-102 not found in auditoriums table.")
            conn.commit()
            conn.close()
    except ImportError:
        print("MySQL: db_config.py not found.")
    except Exception as e:
        print(f"MySQL Error: {e}")

    # 3. Update Supabase
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if url and key:
        try:
            supabase: Client = create_client(url, key)
            res = supabase.table("auditoriums").update({
                "radius_m": 20, 
                "tolerance_m": 40,
                "latitude": -11.673,
                "longitude": 27.489
            }).eq("code", "IF-102").execute()
            
            if res.data:
                print("Supabase: Successfully updated IF-102.")
            else:
                print("Supabase: IF-102 not found or no update performed.")
        except Exception as e:
            print(f"Supabase Error: {e}")
    else:
        print("Supabase: Credentials missing in .env.")

if __name__ == "__main__":
    update_database()
