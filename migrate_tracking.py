import sqlite3
import os

def migrate():
    db_path = 'c:\\xamppI\\htdocs\\UplUniv\\database.db'
    if not os.path.exists(db_path):
        print(f"Base de données non trouvée à {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Création de la table auditoriums_versions...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auditoriums_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auditorium_code TEXT,
            latitude REAL,
            longitude REAL,
            radius_m REAL,
            tolerance_m REAL,
            version INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    print("Création de la table random_checks...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS random_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matricule TEXT,
            auditorium_code TEXT,
            type TEXT, -- 'SCHEDULED', 'PIN'
            scheduled_time TEXT, -- HH:MM
            status TEXT DEFAULT 'PENDING', -- 'PENDING', 'COMPLETED', 'MISSED'
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    print("Création de la table random_check_responses...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS random_check_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id INTEGER,
            matricule TEXT,
            auditorium_code TEXT,
            auditorium_version_id INTEGER,
            latitude REAL,
            longitude REAL,
            accuracy_meters REAL,
            distance REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT,
            ip TEXT,
            device_info TEXT,
            result TEXT, -- 'confirmé', 'hors zone', 'breaktime', 'fraude', 'non vérifié'
            reason TEXT,
            FOREIGN KEY (check_id) REFERENCES random_checks(id)
        )
    ''')
    
    # Insertion des versions actuelles des auditoires
    cursor.execute("SELECT code, latitude, longitude, radius_m, tolerance_m, version FROM auditoriums")
    auds = cursor.fetchall()
    for aud in auds:
        # Vérifier si déjà présent
        cursor.execute("SELECT id FROM auditoriums_versions WHERE auditorium_code = ? AND version = ?", (aud[0], aud[5]))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO auditoriums_versions (auditorium_code, latitude, longitude, radius_m, tolerance_m, version)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', aud)

    conn.commit()
    conn.close()
    print("Migration terminée avec succès.")

if __name__ == "__main__":
    migrate()
