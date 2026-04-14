import os
import sqlite3
import mysql.connector
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# --- MODIFICATION SUPABASE : Script de migration ---
# Ce script transfère vos données locales vers le cloud Supabase.

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Erreur : Veuillez configurer SUPABASE_URL et SUPABASE_KEY dans le fichier .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_local_connection():
    # On tente MySQL d'abord car c'est le serveur principal de XAMPP pour ce projet
    try:
        from db_config import host, user, password, database
        if host and database:
            print(f"Connexion à MySQL ({host}, base: {database})...")
            conn = mysql.connector.connect(
                host=host,
                user=user,
                password=password,
                database=database
            )
            return conn
    except (ImportError, mysql.connector.Error):
        pass

    # Sinon on tente SQLite
    if os.path.exists('database.db'):
        print("Connexion à SQLite (database.db)...")
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        return conn
    
    return None

def migrate_students():
    print("Migration des étudiants...")
    conn = get_local_connection()
    if not conn:
        print("Impossible de se connecter à la base de données locale.")
        return

    cursor = conn.cursor(dictionary=True) if hasattr(mysql.connector, 'connect') and not isinstance(conn, sqlite3.Connection) else conn.cursor()
    
    student_tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]

    all_students = []
    
    for table in student_tables:
        try:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            # Récupération des noms de colonnes
            if hasattr(cursor, 'column_names'):
                columns = cursor.column_names
            elif hasattr(cursor, 'description'):
                columns = [desc[0] for desc in cursor.description]
            else:
                columns = []

            for row in rows:
                if isinstance(row, dict):
                    d = row
                else:
                    d = dict(zip(columns, row))
                
                # Conversion des dates en string pour le JSON
                for key, value in d.items():
                    if isinstance(value, (datetime,)):
                        d[key] = value.isoformat()

                # On s'assure que les colonnes correspondent au nouveau schéma unifié
                student_data = {
                    "matricule": d.get('matricule'),
                    "nom": d.get('nom'),
                    "postnom": d.get('postnom'),
                    "prenom": d.get('prenom'),
                    "sexe": d.get('sexe'),
                    "parcours": d.get('parcours'),
                    "promotion": d.get('promotion'),
                    "filiere": d.get('filiere'),
                    "faculte": d.get('faculte'),
                    "device_signature": d.get('device_signature'),
                    "latitude": d.get('latitude'),
                    "longitude": d.get('longitude')
                }
                all_students.append(student_data)
        except Exception as e:
            print(f"Table {table} ignorée : {e}")

    if all_students:
        print(f"Envoi de {len(all_students)} étudiants vers Supabase...")
        # On insère par lots pour éviter de saturer l'API
        batch_size = 50
        for i in range(0, len(all_students), batch_size):
            batch = all_students[i:i + batch_size]
            supabase.table("students").upsert(batch).execute()
            print(f"Batch {i//batch_size + 1} envoyé.")

    conn.close()

def migrate_presences():
    print("Migration des présences...")
    conn = get_local_connection()
    if not conn: return

    cursor = conn.cursor(dictionary=True) if hasattr(mysql.connector, 'connect') and not isinstance(conn, sqlite3.Connection) else conn.cursor()
    
    all_presences = []
    try:
        # On migre la table globale 'presences' qui contient déjà tout normalement
        cursor.execute("SELECT * FROM presences")
        rows = cursor.fetchall()
        
        if hasattr(cursor, 'column_names'):
            columns = cursor.column_names
        elif hasattr(cursor, 'description'):
            columns = [desc[0] for desc in cursor.description]
        else: columns = []

        for row in rows:
            if isinstance(row, dict): d = row
            else: d = dict(zip(columns, row))
            
            # Nettoyage des dates
            for key, value in d.items():
                if isinstance(value, (datetime,)):
                    d[key] = value.isoformat()
            
            presence_data = {
                "matricule": d.get('matricule'),
                "nom": d.get('nom'),
                "postnom": d.get('postnom'),
                "prenom": d.get('prenom'),
                "sexe": d.get('sexe'),
                "parcours": d.get('parcours'),
                "promotion": d.get('promotion'),
                "filiere": d.get('filiere'),
                "faculte": d.get('faculte'),
                "type_presence": d.get('type_presence'),
                "device_signature": d.get('device_signature'),
                "latitude": d.get('latitude'),
                "longitude": d.get('longitude'),
                "status_geoloc": d.get('status_geoloc'),
                "date_inscription": d.get('date_inscription')
            }
            all_presences.append(presence_data)
        
        if all_presences:
            print(f"Envoi de {len(all_presences)} présences vers Supabase...")
            batch_size = 50
            for i in range(0, len(all_presences), batch_size):
                batch = all_presences[i:i + batch_size]
                supabase.table("presences").insert(batch).execute()
    except Exception as e:
        print(f"Erreur migration présences : {e}")

    conn.close()

if __name__ == "__main__":
    print("--- DEBUT DE LA MIGRATION ---")
    migrate_students()
    migrate_presences()
    print("--- MIGRATION TERMINEE ---")
    print("Note : N'oubliez pas de copier/coller le contenu de 'supabase_schema.sql' dans votre SQL Editor Supabase avant de lancer ce script.")
