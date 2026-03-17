import sqlite3
import mysql.connector
import os
from db_config import host, user, password, database

def get_db_connection():
    if os.environ.get('RENDER'):
        return sqlite3.connect('database.db')
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database
    )

def migrate():
    print("Début de la migration pour la géolocalisation...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    is_sqlite = isinstance(conn, sqlite3.Connection)
    
    tables_to_update = [
        'presences',
        'presence_bac1_IAGE', 'presence_bac2_IAGE', 'presence_bac3_IAGE',
        'presence_bac1_tech_IA', 'presence_bac1_tech_GL', 'presence_bac1_tech_SI',
        'presence_bac2_tech_IA', 'presence_bac2_tech_GL', 'presence_bac2_tech_SI',
        'presence_bac3_tech_IA', 'presence_bac3_tech_GL', 'presence_bac3_tech_SI',
        'presence_bac4_tech_IA', 'presence_bac4_tech_GL', 'presence_bac4_tech_SI'
    ]
    
    for table in tables_to_update:
        try:
            print(f"Mise à jour de la table {table}...")
            if is_sqlite:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN status_geoloc TEXT DEFAULT 'Inconnu'")
            else:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN status_geoloc VARCHAR(50) DEFAULT 'Inconnu'")
            print(f"Colonne status_geoloc ajoutée à {table}")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print(f"La colonne status_geoloc existe déjà dans {table}")
            else:
                print(f"Erreur sur {table}: {e}")
                
    conn.commit()
    cursor.close()
    conn.close()
    print("Migration terminée.")

if __name__ == "__main__":
    migrate()
