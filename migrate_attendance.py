import sqlite3
import mysql.connector
import os
try:
    from db_config import host, user, password, database
except ImportError:
    host = user = password = database = None

def get_db_connection():
    if os.environ.get('RENDER') or not host:
        conn = sqlite3.connect('database.db')
        return conn
    return mysql.connector.connect(
        host=host, user=user, password=password, database=database
    )

def setup_attendance_system():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    is_sqlite = isinstance(conn, sqlite3.Connection)
    
    # --- TABLE AUDITORIUMS ---
    if is_sqlite:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auditoriums (
                code TEXT PRIMARY KEY,
                nom TEXT,
                latitude REAL,
                longitude REAL,
                radius_m REAL DEFAULT 20,
                floor INTEGER DEFAULT 0,
                tolerance_m REAL DEFAULT 5,
                version INTEGER DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auditoriums (
                code VARCHAR(50) PRIMARY KEY,
                nom VARCHAR(100),
                latitude DOUBLE,
                longitude DOUBLE,
                radius_m DOUBLE DEFAULT 20,
                floor INT DEFAULT 0,
                tolerance_m DOUBLE DEFAULT 5,
                version INT DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        ''')

    # --- TABLE ATTENDANCE ATTEMPTS ---
    if is_sqlite:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_external_id TEXT,
                auditorium_code TEXT,
                latitude REAL,
                longitude REAL,
                accuracy_meters REAL,
                timestamp DATETIME,
                device_id TEXT,
                ip TEXT,
                device_info TEXT,
                distance REAL,
                result TEXT,
                reason TEXT,
                auditorium_version INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_attempts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                student_external_id VARCHAR(50),
                auditorium_code VARCHAR(50),
                latitude DOUBLE,
                longitude DOUBLE,
                accuracy_meters DOUBLE,
                timestamp DATETIME,
                device_id VARCHAR(100),
                ip VARCHAR(45),
                device_info TEXT,
                distance DOUBLE,
                result VARCHAR(50),
                reason TEXT,
                auditorium_version INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    # --- TABLE ATTENDANCE CHECKS (Random Verification) ---
    if is_sqlite:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER,
                check_type TEXT, -- 'PIN', 'BIOMETRIC'
                expected_value TEXT,
                received_value TEXT,
                status TEXT, -- 'PENDING', 'SUCCESS', 'FAILED', 'EXPIRED'
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP NULL,
                FOREIGN KEY(attempt_id) REFERENCES attendance_attempts(id)
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_checks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                attempt_id INT,
                check_type VARCHAR(20),
                expected_value VARCHAR(100),
                received_value VARCHAR(100),
                status VARCHAR(20),
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP NULL,
                FOREIGN KEY(attempt_id) REFERENCES attendance_attempts(id)
            )
        ''')

    # --- SEED DATA ---
    auditoriums = [
        ('EC-101', 'Auditoire EC-101', -11.652, 27.482, 25.0, 1, 10.0), # COORDINATES TO BE MODIFIED LATER
        ('D-101', 'Auditoire D-101', -11.653, 27.483, 25.0, 0, 10.0),  # COORDINATES TO BE MODIFIED LATER
        ('B-101', 'Auditoire B-101', -11.654, 27.484, 25.0, 0, 10.0),  # COORDINATES TO BE MODIFIED LATER
        ('IF-301', 'Auditoire IF-301', -11.655, 27.485, 20.0, 3, 5.0), # COORDINATES TO BE MODIFIED LATER
        ('IF-101', 'Auditoire IF-101', -11.656, 27.486, 20.0, 1, 5.0), # COORDINATES TO BE MODIFIED LATER
        ('IF-302', 'Auditoire IF-302', -11.657, 27.487, 20.0, 3, 5.0), # COORDINATES TO BE MODIFIED LATER
        ('IF-102', 'Auditoire IF-102', -11.673, 27.489, 20.0, 1, 40.0), # COORDINATES UPDATED TO MATCH APP.PY
        ('IF-304', 'Auditoire IF-304', -11.659, 27.489, 20.0, 3, 5.0)  # COORDINATES TO BE MODIFIED LATER
    ]
    
    for code, nom, lat, lon, rad, floor, tol in auditoriums:
        if is_sqlite:
            cursor.execute('INSERT OR IGNORE INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m) VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (code, nom, lat, lon, rad, floor, tol))
        else:
            cursor.execute('INSERT IGNORE INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                         (code, nom, lat, lon, rad, floor, tol))
    
    conn.commit()
    conn.close()
    print("Migration and seeding completed successfully.")

if __name__ == "__main__":
    setup_attendance_system()
