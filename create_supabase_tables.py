import psycopg2
import sys

db_uri = "postgresql://postgres:oPIU2THWnnujSGI6@db.rvkkryxydgqkcmcrchjd.supabase.co:6543/postgres"

print("Connexion à Supabase PostgreSQL...")
try:
    conn = psycopg2.connect(db_uri)
    cursor = conn.cursor()
    print("Connexion réussie !")
    
    # 1. Table students
    print("Création de la table 'students'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            matricule TEXT UNIQUE NOT NULL,
            nom TEXT,
            postnom TEXT,
            prenom TEXT,
            sexe TEXT,
            parcours TEXT,
            promotion TEXT,
            filiere TEXT,
            faculte TEXT,
            date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Table presences
    print("Création de la table 'presences'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS presences (
            id SERIAL PRIMARY KEY,
            matricule TEXT,
            nom TEXT,
            postnom TEXT,
            prenom TEXT,
            sexe TEXT,
            parcours TEXT,
            promotion TEXT,
            filiere TEXT,
            faculte TEXT,
            type_presence TEXT,
            device_signature TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            status_geoloc TEXT DEFAULT 'Inconnu',
            date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Table auditoriums
    print("Création de la table 'auditoriums'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auditoriums (
            code TEXT PRIMARY KEY,
            nom TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            radius_m DOUBLE PRECISION DEFAULT 30,
            floor INTEGER DEFAULT 0,
            tolerance_m DOUBLE PRECISION DEFAULT 10,
            version INTEGER DEFAULT 1
        );
    """)

    # 4. Table attendance_attempts
    print("Création de la table 'attendance_attempts'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_attempts (
            id SERIAL PRIMARY KEY,
            student_external_id TEXT,
            auditorium_code TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            accuracy_meters DOUBLE PRECISION,
            timestamp TIMESTAMP,
            device_id TEXT,
            ip TEXT,
            device_info TEXT,
            distance DOUBLE PRECISION,
            result TEXT,
            reason TEXT,
            auditorium_version INTEGER
        );
    """)

    # 5. Table random_checks
    print("Création de la table 'random_checks'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS random_checks (
            id SERIAL PRIMARY KEY,
            matricule TEXT,
            auditorium_code TEXT,
            type TEXT,
            scheduled_time TEXT,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 6. Table random_check_responses
    print("Création de la table 'random_check_responses'...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS random_check_responses (
            id SERIAL PRIMARY KEY,
            check_id INTEGER,
            matricule TEXT,
            auditorium_code TEXT,
            auditorium_version_id INTEGER,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            accuracy_meters DOUBLE PRECISION,
            distance DOUBLE PRECISION,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT,
            ip TEXT,
            device_info TEXT,
            result TEXT,
            reason TEXT
        );
    """)

    # Insertion des auditoires de base si la table est vide
    cursor.execute("SELECT COUNT(*) FROM auditoriums;")
    if cursor.fetchone()[0] == 0:
        print("Insertion des auditoires par défaut...")
        auds = [
            ('EC-101', 'Eco-A', -11.667, 27.483, 30.0, 1, 10.0, 1),
            ('D-101', 'Droit-1', -11.668, 27.484, 25.0, 0, 10.0, 1),
            ('B-101', 'Biblio', -11.669, 27.485, 40.0, 0, 15.0, 1),
            ('IF-301', 'Info-301', -11.670, 27.486, 30.0, 3, 10.0, 1),
            ('IF-101', 'Info-101', -11.671, 27.487, 30.0, 1, 10.0, 1),
            ('IF-302', 'Info-302', -11.672, 27.488, 30.0, 3, 10.0, 1),
            ('IF-102', 'Info-102', -11.6529086, 27.48359, 22.0, 1, 400.0, 1),
            ('IF-304', 'Info-304', -11.674, 27.490, 30.0, 3, 10.0, 1)
        ]
        for aud in auds:
            cursor.execute("""
                INSERT INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m, version) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, aud)

    conn.commit()
    print("Toutes les tables ont été créées et configurées avec succès !")
    cursor.close()
    conn.close()

except Exception as e:
    print("Erreur critique pendant la création des tables :", e)
    sys.exit(1)
