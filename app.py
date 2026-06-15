import mysql.connector
import sqlite3
import qrcode
import io
import traceback
from flask import Flask, request, render_template, redirect, url_for, jsonify, send_file, session
from datetime import datetime, timedelta, timezone
try: 
    from db_config import host, user, password, database
except ImportError:
    # definition d'une paramettre par defaut, si db_confing est absent cas de render qui n'a pas une base de données 
    host = user = password = database = None

import os
import math
import time

# --- MODIFICATION SUPABASE : Importations nécessaires ---
from dotenv import load_dotenv
from supabase import create_client, Client

# Chargement des variables d'environnement depuis le fichier .env
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Initialisation du client Supabase
# --- MODIFICATION SUPABASE : Création du client global ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Aide pour la compatibilité MySQL/SQLite
def execute_sql(cursor, query, params=None):
    # On remplace par ? si on détecte SQLite ou si on n'est pas sûr
    cursor_type = str(type(cursor)).lower()
    is_mysql = 'mysql' in cursor_type
    
    actual_query = query
    if not is_mysql:   
        actual_query = query.replace('%s', '?')
        
    if params is None:
        return cursor.execute(actual_query)
    return cursor.execute(actual_query, params)


def safe_supabase_delete(table_name):
    """Supprime les lignes d'une table Supabase si elle existe."""
    try:
        supabase.table(table_name).delete().neq("id", 0).execute()
    except Exception as err:
        err_msg = str(err)
        if "Could not find the table" in err_msg or "PGRST205" in err_msg:
            return
        raise

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en mètres entre deux points (Haversine formula).
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float('inf')
        
    R = 6371000  # Rayon de la Terre en mètres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

# Choix intelligent du dossier de ressources (Compatible PC local et Render)
basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(basedir, 'templates')
static_dir = os.path.join(basedir, 'static')

# Si les dossiers n'existent pas (cas particulier de certains déploiements), on revient à la racine
if not os.path.isdir(template_dir):
    template_dir = basedir
if not os.path.isdir(static_dir):
    static_dir = basedir

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'admin_secret_key_2024'

# --- CONFIGURATION DU SYSTÈME DE VALIDATION ---
# Ces valeurs peuvent être ajustées selon les besoins
ACCURACY_MAX = 150.0     # Précision GPS maximale acceptée (mètres)
TIME_MAX_SECONDS = 300   # Fenêtre de temps maximale (secondes pour que le formulaire puisse réouvrir à nouveau)
DEFAULT_TOLERANCE = 10.0 # Tolérance par défaut (mètres)

# --- CONFIGURATION DE L'URL PUBLIQUE (NGROK) ---
# Si vous utilisez Ngrok, modifiez cette variable avec votre lien https://...
# Sinon, laissez vide pour utiliser l'adresse locale.
PUBLIC_URL = os.environ.get('PUBLIC_URL', '') 
if PUBLIC_URL and not PUBLIC_URL.startswith(('http://', 'https://')):
    PUBLIC_URL = f"https://{PUBLIC_URL}"

# --- CONFIGURATION DES HORAIRES DE SUIVI (PRODUCTION) ---
# NOTE: Ces horaires sont utilisés pour le suivi standard.
# Pour les ESSAIS actuels, un suivi progressif (15s, 60s...) est actif côté client.
# Heures de vérification pour la session du MATIN (Entrée possible dès 07:00)
MORNING_CHECK_TIMES = ["09:00", "10:00", "10:30", "10:40", "11:00", "11:30", "11:55"]

# Heures de vérification pour la session de l'APRÈS-MIDI (Entrée possible dès 12:36)
AFTERNOON_CHECK_TIMES = ["14:00", "14:55", "15:00", "15:45", "16:30", "16:50"]

# Heure d'ouverture globale du formulaire de sortie (le matin et l'après-midi)
MORNING_EXIT_OPEN_TIME = "11:50"
AFTERNOON_EXIT_OPEN_TIME = "16:50"

# Délai de désactivation temporaire du formulaire après une sortie (en secondes)
# Mis à 30 secondes de l'activaton du formulaire après l'inssertion
EXIT_COOLDOWN_SECONDS = 30 

# --- sécurité admin pour empecher à n'import qui d'accèder sur l'interface admin---
ADMIN_USERNAME = 'Lee-vayle'
ADMIN_PASSWORD = 'Lee123#'

def login_required(f):
    def wrapper(*args, **kwargs):
        if 'admin_logged_in' not in session:
            # For API routes, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            # For web routes, redirect to login
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if 'admin_logged_in' in session:
        return redirect(url_for('admin_general_dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_general_dashboard'))
        else:
            return render_template('admin_login.html', error='Identifiants incorrects')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# --- CONFIGURATION DE LA CONNEXION À LA BASE DE DONNÉES ---
def get_db_connection():
    # --- MODIFICATION SUPABASE : La connexion passe désormais par le client Supabase ---
    # Cette fonction est conservée pour la compatibilité, mais nous privilégierons 
    # l'utilisation de l'objet 'supabase' directement pour les nouvelles opérations cloud.
    
    # Détection de l'environnement : Si on est sur Render, on utilise SQLite par défaut
    if os.environ.get('RENDER') or not host:
        print("BD: Utilisation de SQLite")
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        return conn
    
    # Sinon on utilise MySQL
    print(f"BD: Connexion à MySQL ({host})")
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database
    )

def init_sqlite_db():
    if os.environ.get('RENDER') or not host:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # --- 9. Tables étudiants supprimées ---
        # --- 10. Tables présences supprimées ---

        # Table centrale globale des présences
        execute_sql(cursor, '''
            CREATE TABLE IF NOT EXISTS presences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                latitude REAL,
                longitude REAL,
                status_geoloc TEXT DEFAULT 'Inconnu',
                date_inscription DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Table des auditoriums
        execute_sql(cursor, '''
            CREATE TABLE IF NOT EXISTS auditoriums (
                code TEXT PRIMARY KEY,
                nom TEXT,
                latitude REAL,
                longitude REAL,
                radius_m REAL DEFAULT 30,
                floor INTEGER DEFAULT 0,
                tolerance_m REAL DEFAULT 10,
                version INTEGER DEFAULT 1
            )
        ''')

        # Table des tentatives de présence (Immuable)
        execute_sql(cursor, '''
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
                auditorium_version INTEGER
            )
        ''')

        # Table des contrôles aléatoires (PIN)
        execute_sql(cursor, '''
            CREATE TABLE IF NOT EXISTS attendance_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER,
                check_type TEXT DEFAULT 'PIN',
                pin TEXT,
                status TEXT DEFAULT 'PENDING',
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                responded_at DATETIME,
                FOREIGN KEY (attempt_id) REFERENCES attendance_attempts(id)
            )
        ''')

        # Table auditoriums_versions
        execute_sql(cursor, '''
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

        # Table random_checks (Vérifications programmées)
        execute_sql(cursor, '''
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

        # Table random_check_responses (Rapports de suivi)
        execute_sql(cursor, '''
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
        
        # Insertion des données de base pour les auditoires si vide
        execute_sql(cursor, "SELECT COUNT(*) FROM auditoriums")
        if cursor.fetchone()[0] == 0:
            auds = [
                ('EC-101', 'Eco-A', -11.667, 27.483, 30, 1, 10, 1),
                ('D-101', 'Droit-1', -11.668, 27.484, 25, 0, 10, 1),
                ('B-101', 'Biblio', -11.669, 27.485, 40, 0, 15, 1),
                ('IF-301', 'Info-301', -11.670, 27.486, 30, 3, 10, 1),
                ('IF-101', 'Info-101', -11.671, 27.487, 30, 1, 10, 1),
                ('IF-302', 'Info-302', -11.672, 27.488, 30, 3, 10, 1),
                ('IF-102', 'Info-102', -11.6529086, 27.48359, 22, 1, 400, 1),
                ('IF-304', 'Info-304', -11.674, 27.490, 30, 3, 10, 1)
            ]
            for aud in auds:
                execute_sql(cursor, "INSERT INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", aud)
        
        conn.commit()
        conn.close()
            
# =============================================================================
# INITIALISATION MYSQL : Création automatique des tables et colonnes manquantes
# =============================================================================
def init_mysql_db():
    """
    Crée automatiquement toutes les tables MySQL nécessaires si elles n'existent pas.
    Ne bloque jamais : chaque table est créée dans un try/except indépendant.
    """
    if os.environ.get('RENDER') or not host:
        return  # SQLite géré par init_sqlite_db()

    try:
        conn = mysql.connector.connect(host=host, user=user, password=password, database=database)
        cursor = conn.cursor()
        print("MySQL: Vérification et création automatique des tables...")

        # --- 1. Table centrale des étudiants (Supabase fallback local) ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    matricule VARCHAR(50) UNIQUE,
                    nom VARCHAR(100),
                    postnom VARCHAR(100),
                    prenom VARCHAR(100),
                    sexe VARCHAR(10),
                    parcours VARCHAR(150),
                    promotion VARCHAR(100),
                    filiere VARCHAR(150),
                    faculte VARCHAR(200),
                    date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'students' OK")
        except Exception as e:
            print(f"MySQL: students -> {e}")

        # --- 2. Table centrale des présences ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS presences (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    matricule VARCHAR(50),
                    nom VARCHAR(100),
                    postnom VARCHAR(100),
                    prenom VARCHAR(100),
                    sexe VARCHAR(10),
                    parcours VARCHAR(150),
                    promotion VARCHAR(100),
                    filiere VARCHAR(150),
                    faculte VARCHAR(200),
                    type_presence VARCHAR(20),
                    device_signature VARCHAR(100),
                    latitude DOUBLE,
                    longitude DOUBLE,
                    status_geoloc VARCHAR(150) DEFAULT 'Inconnu',
                    date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'presences' OK")
        except Exception as e:
            print(f"MySQL: presences -> {e}")

        # --- 3. Table des auditoires ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS auditoriums (
                    code VARCHAR(50) PRIMARY KEY,
                    nom VARCHAR(100),
                    latitude DOUBLE,
                    longitude DOUBLE,
                    radius_m DOUBLE DEFAULT 30,
                    floor INT DEFAULT 0,
                    tolerance_m DOUBLE DEFAULT 10,
                    version INT DEFAULT 1
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            # Insertion des auditoires par défaut si vide
            cursor.execute("SELECT COUNT(*) FROM auditoriums")
            if cursor.fetchone()[0] == 0:
                auds = [
                    ('EC-101', 'Eco-A', -11.667, 27.483, 30, 1, 10, 1),
                    ('D-101', 'Droit-1', -11.668, 27.484, 25, 0, 10, 1),
                    ('B-101', 'Biblio', -11.669, 27.485, 40, 0, 15, 1),
                    ('IF-301', 'Info-301', -11.670, 27.486, 30, 3, 10, 1),
                    ('IF-101', 'Info-101', -11.671, 27.487, 30, 1, 10, 1),
                    ('IF-302', 'Info-302', -11.672, 27.488, 30, 3, 10, 1),
                    ('IF-102', 'Info-102', -11.6529086, 27.48359, 22, 1, 400, 1),
                    ('IF-304', 'Info-304', -11.674, 27.490, 30, 3, 10, 1)
                ]
                for aud in auds:
                    cursor.execute("INSERT IGNORE INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m, version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", aud)
                conn.commit()
            print("MySQL: Table 'auditoriums' OK")
        except Exception as e:
            print(f"MySQL: auditoriums -> {e}")

        # --- 4. Table des tentatives de présence ---
        try:
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
                    auditorium_version INT
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'attendance_attempts' OK")
        except Exception as e:
            print(f"MySQL: attendance_attempts -> {e}")

        # --- 5. Table des contrôles aléatoires (PIN) ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance_checks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    attempt_id INT,
                    check_type VARCHAR(20) DEFAULT 'PIN',
                    pin VARCHAR(10),
                    expected_value VARCHAR(50),
                    received_value VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'PENDING',
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    responded_at DATETIME
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'attendance_checks' OK")
        except Exception as e:
            print(f"MySQL: attendance_checks -> {e}")

        # --- 6. Table des versions d'auditoires ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS auditoriums_versions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    auditorium_code VARCHAR(50),
                    latitude DOUBLE,
                    longitude DOUBLE,
                    radius_m DOUBLE,
                    tolerance_m DOUBLE,
                    version INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'auditoriums_versions' OK")
        except Exception as e:
            print(f"MySQL: auditoriums_versions -> {e}")

        # --- 7. Table des vérifications programmées ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS random_checks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    matricule VARCHAR(50),
                    auditorium_code VARCHAR(50),
                    type VARCHAR(20),
                    scheduled_time VARCHAR(10),
                    status VARCHAR(20) DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'random_checks' OK")
        except Exception as e:
            print(f"MySQL: random_checks -> {e}")

        # --- 8. Table des rapports de suivi ---
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS random_check_responses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    check_id INT,
                    matricule VARCHAR(50),
                    auditorium_code VARCHAR(50),
                    auditorium_version_id INT,
                    latitude DOUBLE,
                    longitude DOUBLE,
                    accuracy_meters DOUBLE,
                    distance DOUBLE,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    device_id VARCHAR(100),
                    ip VARCHAR(45),
                    device_info TEXT,
                    result VARCHAR(50),
                    reason TEXT
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            ''')
            conn.commit()
            print("MySQL: Table 'random_check_responses' OK")
        except Exception as e:
            print(f"MySQL: random_check_responses -> {e}")

        # --- 9. Tables locales supprimées (on utilise la table globale students et presences) ---

        print("MySQL: Toutes les tables vérifiées.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"MySQL init_mysql_db() erreur globale (non bloquant) : {e}")


def ensure_columns():
    """
    Vérifie et ajoute automatiquement les colonnes manquantes dans les tables existantes.
    Compatible MySQL et SQLite. Ne bloque jamais.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        is_sqlite = isinstance(conn, sqlite3.Connection)

        # Dictionnaire : table -> liste de (colonne, type_sqlite, type_mysql)
        schema = {
            'presences': [
                ('device_signature', 'TEXT', 'VARCHAR(100)'),
                ('latitude',         'REAL', 'DOUBLE'),
                ('longitude',        'REAL', 'DOUBLE'),
                ('status_geoloc',    'TEXT', 'VARCHAR(150)'),
                ('faculte',          'TEXT', 'VARCHAR(200)'),
                ('parcours',         'TEXT', 'VARCHAR(150)'),
                ('filiere',          'TEXT', 'VARCHAR(150)'),
            ],
            'students': [
                ('faculte',  'TEXT', 'VARCHAR(200)'),
                ('parcours', 'TEXT', 'VARCHAR(150)'),
                ('filiere',  'TEXT', 'VARCHAR(150)'),
            ],
            'attendance_checks': [
                ('expected_value', 'TEXT', 'VARCHAR(50)'),
                ('received_value', 'TEXT', 'VARCHAR(50)'),
            ],
        }

        for table, columns in schema.items():
            for col_name, sqlite_type, mysql_type in columns:
                try:
                    if is_sqlite:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {sqlite_type}")
                        conn.commit()
                    else:
                        # MySQL : vérifie d'abord si la colonne existe
                        cursor.execute(
                            "SELECT COUNT(*) FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                            (database, table, col_name)
                        )
                        if cursor.fetchone()[0] == 0:
                            cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {mysql_type}")
                            conn.commit()
                            print(f"MySQL: Colonne '{col_name}' ajoutée à '{table}'")
                except Exception:
                    pass  # Colonne déjà existante ou table absente -> ignoré silencieusement

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"ensure_columns() erreur (non bloquant) : {e}")


# Initialisation automatique au démarrage
init_sqlite_db()
init_mysql_db()
ensure_columns()

# --- ROUTES DE NAVIGATION ---

# Route d'accueil : Affiche le formulaire d'inscription par défaut
@app.route('/register_student')
def index():
    return render_template('register.html')

# Route pour la page de présence
@app.route('/attendance')
def attendance():
    return render_template('attendance.html')

# Route de redirection courte pour "masquer" le lien du code QR
@app.route('/s')
def short_presence_redirect():
    return redirect(url_for('attendance'))

# --- LOGIQUE DE RÉCUPÉRATION ET TRAITEMENT DES DONNÉES ---
@app.route('/check_attendance', methods=['POST'])
def check_attendance():
    """
    SYSTÈME DE VALIDATION DE PRÉSENCE EN AUDITOIRE.
    Vérifie la position GPS par rapport à la zone de l'auditoire choisi.
    """
    # 1. Récupération des données du formulaire
    matricule = request.form.get('matricule', '').strip()
    type_presence = request.form.get('type_presence', 'Entrée')
    device_signature = request.form.get('device_signature', 'Unknown-Device')
    auditorium_code = request.form.get('auditorium_code')
    
    # Données GPS et métatonnées
    try:
        lat = float(request.form.get('latitude')) if request.form.get('latitude') else None
        lon = float(request.form.get('longitude')) if request.form.get('longitude') else None
        accuracy = float(request.form.get('accuracy_meters', 0))
    except (ValueError, TypeError):
        lat, lon, accuracy = None, None, 0

    # Infos supplémentaires pour le journal (immuable)
    user_ip = request.remote_addr
    device_info = request.headers.get('User-Agent', '')
    now_lubumbashi = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
    today_date = now_lubumbashi.strftime('%Y-%m-%d')

    if not auditorium_code:
        return jsonify({"status": "error", "message": "Veuillez choisir un auditoire"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 2. Récupération des infos de l'auditoire
        if supabase:
            res_aud = supabase.table("auditoriums").select("*").eq("code", auditorium_code).execute()
            if res_aud.data:
                aud = res_aud.data[0]
            else:
                return jsonify({"status": "error", "message": "Auditoire invalide"}), 404
        else:
            query_aud = "SELECT * FROM auditoriums WHERE code = %s"
            execute_sql(cursor, query_aud, (auditorium_code,))
            aud_res = cursor.fetchone()
            if not aud_res:
                return jsonify({"status": "error", "message": "Auditoire invalide"}), 404
            aud = dict(aud_res) if not isinstance(aud_res, tuple) else {
                'code': aud_res[0], 'nom': aud_res[1], 'latitude': aud_res[2], 
                'longitude': aud_res[3], 'radius_m': aud_res[4], 'floor': aud_res[5], 
                'tolerance_m': aud_res[6], 'version': aud_res[7]
            }

        # 3. Calcul de la distance et validation GPS
        distance = calculate_distance(lat, lon, aud['latitude'], aud['longitude'])
        max_allowed_distance = aud['radius_m'] + aud['tolerance_m']
        
        if lat is None or lon is None:
            reason = "GPS manquant"
            result = "Rejeté"
        elif accuracy > ACCURACY_MAX:
            reason = f"Précision GPS insuffisante ({accuracy}m > {ACCURACY_MAX}m)"
            result = "Rejeté"
        else:
            result = "Accepté"
            if distance > max_allowed_distance:
                reason = f"Hors zone ({int(distance)}m)"

        # 4. Vérification de l'étudiant
        # --- MODIFICATION SUPABASE : Recherche globale sur le Cloud ---
        if supabase:
            student_res = supabase.table("students").select("*").eq("matricule", matricule).execute()
            if student_res.data:
                student_data_dict = student_res.data[0]
                found = True
            else:
                found = False
        else:
            # Fallback table locale (nouvelle table globale)
            found = False
            try:
                query = "SELECT nom, postnom, prenom, filiere, promotion, sexe, faculte, parcours FROM students WHERE matricule = %s"
                execute_sql(cursor, query, (matricule,))
                res = cursor.fetchone()
                if res:
                    # Convertir res en dictionnaire pour compatibilité
                    student_data_dict = {
                        "nom": res[0], "postnom": res[1], "prenom": res[2], 
                        "filiere": res[3], "promotion": res[4], "sexe": res[5], 
                        "faculte": res[6], "parcours": res[7]
                    }
                    found = True
            except Exception as e:
                print(f"Erreur vérification étudiant local: {e}")
        
        if not found:
            reason = "Matricule inconnu"
            result = "Rejeté"
        elif result == "Accepté":
            # 4.1 Limite de 4 pointages par jour (2 entrées / 2 sorties)
            if supabase:
                res_count = supabase.table("presences").select("id", count="exact").eq("matricule", matricule).gte("date_inscription", today_date).execute()
                already_count = res_count.count
            else:
                check_limit_query = "SELECT COUNT(*) FROM presences WHERE matricule = %s AND date(date_inscription) = %s"
                execute_sql(cursor, check_limit_query, (matricule, today_date))
                count_res = cursor.fetchone()
                already_count = count_res[0] if isinstance(count_res, (list, tuple)) else (count_res['COUNT(*)'] if 'COUNT(*)' in count_res else 0)
            
            if already_count >= 4:
                reason = "Limite de 4 pointages par jour atteinte (2 Entrées / 2 Sorties)"
                result = "Rejeté"

            if result == "Accepté":
                # Logique de séquence (Entrée -> Sortie)
                if supabase:
                    res_seq = supabase.table("presences").select("type_presence").eq("matricule", matricule).gte("date_inscription", today_date).order("date_inscription", desc=True).execute()
                    today_types = [r['type_presence'] for r in res_seq.data]
                else:
                    check_sequence_query = "SELECT type_presence FROM presences WHERE matricule = %s AND date(date_inscription) = %s ORDER BY date_inscription DESC"
                    execute_sql(cursor, check_sequence_query, (matricule, today_date))
                    history = cursor.fetchall()
                    today_types = [row['type_presence'] if not isinstance(row, dict) else row.get('type_presence') for row in history]
                    today_types = [t if t else (row[0] if isinstance(row, (list, tuple)) else None) for t, row in zip(today_types, history)]
                
                last_type = today_types[0] if today_types else None
                
                if type_presence == 'Entrée' and last_type == 'Entrée':
                    reason = "Déjà une entrée active"
                    result = "Rejeté"
                elif type_presence == 'Sortie':
                    if last_type != 'Entrée':
                        reason = "Pas d'entrée correspondante"
                        result = "Rejeté"
                    else:
                        # 4.3 Si c'est une sortie, vérifier qu'elle se fait dans le même auditoire que l'entrée
                        if supabase:
                            res_aud = supabase.table("attendance_attempts").select("auditorium_code").eq("student_external_id", matricule).eq("result", "Accepté").gte("timestamp", today_date).order("timestamp", desc=True).limit(1).execute()
                            if res_aud.data:
                                last_aud_code = res_aud.data[0]['auditorium_code']
                            else:
                                last_aud_code = None
                        else:
                            get_last_aud_query = "SELECT auditorium_code FROM attendance_attempts WHERE student_external_id = %s AND date(timestamp) = %s AND result = 'Accepté' ORDER BY timestamp DESC LIMIT 1"
                            execute_sql(cursor, get_last_aud_query, (matricule, today_date))
                            last_aud_res = cursor.fetchone()
                            if last_aud_res:
                                last_aud_code = last_aud_res[0] if isinstance(last_aud_res, (list, tuple)) else (last_aud_res['auditorium_code'] if 'auditorium_code' in last_aud_res else last_aud_res[0])
                            else:
                                last_aud_code = None
                        
                        if last_aud_code and last_aud_code != auditorium_code:
                            # On accepte la requête (pour ne pas alerter l'étudiant) mais on marque en Fraude
                            reason = f"L'entrée s'est faite dans '{last_aud_code}', pas '{auditorium_code}'"
                            auditorium_fraud = True

        # 5. JOURNALISATION (attendance_attempts)
        # --- MODIFICATION SUPABASE : Journalisation Cloud ---
        attempt_data = {
            "student_external_id": matricule,
            "auditorium_code": auditorium_code,
            "latitude": lat,
            "longitude": lon,
            "accuracy_meters": accuracy,
            "device_id": device_signature,
            "ip": user_ip,
            "device_info": device_info,
            "distance": distance,
            "result": result,
            "reason": reason if result == "Rejeté" else locals().get('reason', None),
            "auditorium_version": aud['version'],
            "timestamp": now_lubumbashi.isoformat()
        }
        
        if supabase:
            supabase.table("attendance_attempts").insert(attempt_data).execute()
        else:
            insert_attempt = """
                INSERT INTO attendance_attempts 
                (student_external_id, auditorium_code, latitude, longitude, accuracy_meters, timestamp, device_id, ip, device_info, distance, result, reason, auditorium_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            execute_sql(cursor, insert_attempt, (matricule, auditorium_code, lat, lon, accuracy, now_lubumbashi, device_signature, user_ip, device_info, distance, result, attempt_data["reason"], aud['version']))
        
        # 6. Si validé, enregistrement final
        if result == "Accepté":
            # Status personnalisé pour l'admin
            if locals().get('auditorium_fraud', False):
                status_geoloc = f"Fraude ({reason})"
            else:
                status_geoloc = f"Validé ({auditorium_code})"
                if distance > max_allowed_distance:
                    status_geoloc = f"Fraude (Hors Zone : {int(distance)}m)"
            
            # --- MODIFICATION SUPABASE : Enregistrement de la présence sur le Cloud ---
            presence_data = {
                "matricule": matricule,
                "nom": student_data_dict.get('nom'),
                "postnom": student_data_dict.get('postnom'),
                "prenom": student_data_dict.get('prenom'),
                "sexe": student_data_dict.get('sexe'),
                "parcours": student_data_dict.get('parcours'),
                "promotion": student_data_dict.get('promotion'),
                "filiere": student_data_dict.get('filiere'),
                "faculte": student_data_dict.get('faculte'),
                "type_presence": type_presence,
                "device_signature": device_signature,
                "latitude": lat,
                "longitude": lon,
                "status_geoloc": status_geoloc,
                "date_inscription": now_lubumbashi.isoformat()
            }
            if supabase:
                supabase.table("presences").insert(presence_data).execute()
            else:
                # Table globale locale
                insert_query = """
                    INSERT INTO presences 
                    (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, latitude, longitude, status_geoloc, date_inscription) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                execute_sql(cursor, insert_query, (matricule, presence_data['nom'], presence_data['postnom'], presence_data['prenom'], presence_data['sexe'], presence_data['parcours'], presence_data['promotion'], presence_data['filiere'], presence_data['faculte'], type_presence, device_signature, lat, lon, status_geoloc, now_lubumbashi))
            
            if not supabase:
                conn.commit()
                cursor.close()
                conn.close()
            # Retour enrichi pour le client: nom de l'auditoire, étiquette de géolocalisation et distance
            return jsonify({
                "status": "success",
                "message": "Présence enregistrée avec succès",
                "auditorium": aud.get('nom'),
                "status_geoloc": status_geoloc,
                "distance_m": int(distance) if isinstance(distance, (int, float)) and distance != float('inf') else None
            })
        else:
            if not supabase:
                conn.commit()
                cursor.close()
                conn.close()
            return jsonify({"status": "error", "message": reason if "reason" in locals() else "Validation échouée"}), 403

    except Exception as e:
        traceback.print_exc()
        if 'conn' in locals() and conn: 
            try: conn.close()
            except: pass
        return jsonify({"error": f"Erreur Interne: {str(e)}"}), 500


@app.route('/api/tracking/config')
def get_tracking_config():
    """
    Renvoie les horaires et paramètres de suivi pour le client.
    """
    return jsonify({
        "morning_checks": MORNING_CHECK_TIMES,
        "afternoon_checks": AFTERNOON_CHECK_TIMES,
        "exit_cooldown": EXIT_COOLDOWN_SECONDS,
        "morning_exit_open": MORNING_EXIT_OPEN_TIME,
        "afternoon_exit_open": AFTERNOON_EXIT_OPEN_TIME
    })

@app.route('/attendance/check/report', methods=['POST'])
def check_report():
    """
    Point de terminaison pour recevoir les rapports de position programmés.
    """
    data = request.json
    matricule = data.get('matricule')
    auditorium_code = data.get('auditorium_code')
    lat = data.get('latitude')
    lon = data.get('longitude')
    accuracy = data.get('accuracy_meters', 0)
    scheduled_time = data.get('scheduled_time')
    device_signature = data.get('device_signature')
    
    user_ip = request.remote_addr
    device_info = request.headers.get('User-Agent', '')
    now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
    
    # Log pour débogage (essai)
    print(f"DEBUG: Rapport reçu pour {matricule} ({scheduled_time}) à {now_lub}")

    if not all([matricule, auditorium_code, lat, lon]):
        return jsonify({"status": "error", "message": "Données incomplètes"}), 400

    try:
        # --- MODIFICATION SUPABASE : Validation et Persistance Cloud ---
        if supabase:
            # 1. Infos auditoire via Supabase
            res_aud = supabase.table("auditoriums").select("*").eq("code", auditorium_code).execute()
            if not res_aud.data:
                return jsonify({"status": "error", "message": "Auditoire invalide"}), 404
            
            aud = res_aud.data[0]

            # 2. Calcul distance
            distance = calculate_distance(lat, lon, aud['latitude'], aud['longitude'])
            max_allowed = aud['radius_m'] + aud['tolerance_m']
            
            # 3. Logique de statut
            result = "confirmé"
            reason = ""
            
            if distance > max_allowed:
                if scheduled_time == "15S_CHECK" or scheduled_time.startswith("TEST_SUIVI"):
                    result = "fraude"
                    reason = f"Signal fraude : le matricule {matricule} est toujours hors zone"
                elif scheduled_time == "10:30":
                    result = "breaktime"
                    reason = "Hors zone pendant le break"
                elif scheduled_time == "10:40":
                    result = "fraude"
                    reason = "Signal fraude : toujours hors zone après le break"
                elif scheduled_time == "15:00":
                    result = "pause"
                    reason = "Signal hors zone pendant la pause"
                else:
                    result = "hors zone"
                    reason = f"Distance excessive: {int(distance)}m"
            elif accuracy > ACCURACY_MAX:
                 result = "non vérifié"
                 reason = f"Précision GPS insuffisante ({int(accuracy)}m)"

            # 4. Enregistrement de la vérification des auditoire entrant et sortant
            check_data = {
                "matricule": matricule,
                "auditorium_code": auditorium_code,
                "type": 'SCHEDULED',
                "scheduled_time": scheduled_time,
                "status": 'COMPLETED'
            }
            res_check = supabase.table("random_checks").insert(check_data).execute()
            check_id = res_check.data[0]['id']
            
            # 5. Enregistrement du rapport détaillé
            resp_data = {
                "check_id": check_id,
                "matricule": matricule,
                "auditorium_code": auditorium_code,
                "auditorium_version_id": aud['version'],
                "latitude": lat,
                "longitude": lon,
                "accuracy_meters": accuracy,
                "distance": distance,
                "timestamp": now_lub.isoformat(),
                "device_id": device_signature,
                "ip": user_ip,
                "device_info": device_info,
                "result": result,
                "reason": reason
            }
            supabase.table("random_check_responses").insert(resp_data).execute()
            
            return jsonify({"status": "success", "result": result, "reason": reason})
        else:
            return jsonify({"status": "error", "message": "Supabase non configuré"}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/student/<path:matricule>')
def get_student_info(matricule):
    """
    Recherche un étudiant par son matricule.
    --- MODIFICATION SUPABASE : Recherche Cloud unifiée ---
    """
    matricule = matricule.strip()
    try:
        if supabase:
            # Recherche de l'étudiant
            res = supabase.table("students").select("*").eq("matricule", matricule).execute()
            if not res.data:
                return jsonify({"error": "Étudiant non trouvé"}), 404
            
            found_data = res.data[0]
            
            # Stats de présence pour aujourd'hui
            now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            today = now_lub.strftime('%Y-%m-%d')
            
            # Récupération des présences du jour sur Supabase
            pres_res = supabase.table("presences").select("type_presence").eq("matricule", matricule).gte("date_inscription", today).order("date_inscription", desc=True).execute()
            types = [p['type_presence'] for p in pres_res.data]
            
            found_data['last_type'] = types[0] if types else None
            found_data['count_today'] = len(types)
            
            # Si le dernier pointage est une Entrée, on récupère l'auditoire
            if found_data['last_type'] == 'Entrée':
                res_aud = supabase.table("attendance_attempts").select("auditorium_code").eq("student_external_id", matricule).eq("result", "Accepté").gte("timestamp", today).order("timestamp", desc=True).limit(1).execute()
                if res_aud.data:
                    found_data['last_auditorium_code'] = res_aud.data[0]['auditorium_code']

            # Vérification de contrôle aléatoire en attente
            found_data['pending_check'] = None
            try:
                check_res = supabase.table("random_checks").select("id, type").eq("matricule", matricule).eq("status", "PENDING").order("created_at", desc=True).limit(1).execute()
                if check_res.data:
                    found_data['pending_check'] = check_res.data[0]
            except Exception:
                found_data['pending_check'] = None
            
            return jsonify(found_data)
        else:
            # Fallback local...
            return jsonify({"error": "Supabase non configuré"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/historique/<path:matricule>')
def get_historique(matricule):
    """
    Retourne les présences d'un étudiant pour une semaine donnée.
    Paramètres GET : from=YYYY-MM-DD, to=YYYY-MM-DD
    """
    matricule = matricule.strip()
    date_from = request.args.get('from')
    date_to   = request.args.get('to')

    try:
        if supabase:
            query = supabase.table("presences").select(
                "matricule, type_presence, date_inscription, filiere, faculte"
            ).eq("matricule", matricule).order("date_inscription", desc=True)

            if date_from:
                query = query.gte("date_inscription", date_from)
            if date_to:
                query = query.lte("date_inscription", date_to + "T23:59:59")

            res = query.execute()
            presences = res.data if res.data else []

            # Récupérer l'auditoire depuis attendance_attempts
            att_query = supabase.table("attendance_attempts").select(
                "auditorium_code, timestamp"
            ).eq("student_external_id", matricule).eq("result", "Accepté").order("timestamp", desc=True)

            if date_from:
                att_query = att_query.gte("timestamp", date_from)
            if date_to:
                att_query = att_query.lte("timestamp", date_to + "T23:59:59")

            att_res = att_query.execute()
            att_map = {}
            for a in (att_res.data or []):
                ts = (a.get('timestamp') or '')[:16]
                att_map[ts] = a.get('auditorium_code', '')

            for p in presences:
                ts = (p.get('date_inscription') or '')[:16]
                p['auditorium_code'] = att_map.get(ts, '')

            return jsonify({"presences": presences})
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            q = "SELECT matricule, type_presence, date_inscription, filiere, faculte FROM presences WHERE matricule = %s"
            params = [matricule]
            if date_from:
                q += " AND date(date_inscription) >= %s"
                params.append(date_from)
            if date_to:
                q += " AND date(date_inscription) <= %s"
                params.append(date_to)
            q += " ORDER BY date_inscription DESC"
            execute_sql(cursor, q, tuple(params))
            rows = cursor.fetchall()
            presences = []
            for row in rows:
                if isinstance(row, dict):
                    presences.append(dict(row))
                else:
                    presences.append({
                        "matricule": row[0], "type_presence": row[1],
                        "date_inscription": str(row[2]), "filiere": row[3],
                        "faculte": row[4], "auditorium_code": ""
                    })
            conn.close()
            return jsonify({"presences": presences})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate_qr')
def generate_qr():
    """
    Génère un QR code pointant vers la page de présence.
    Supporte l'option de téléchargement via le paramètre ?download=1
    """
    download = request.args.get('download', '0') == '1'
    # On utilise l'URL publique si elle est définie, sinon l'URL locale
    if PUBLIC_URL:
        base_url = PUBLIC_URL.rstrip('/')
        target_url = f"{base_url}{url_for('attendance')}"
    else:
        target_url = url_for('attendance', _external=True)
    

    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="navy", back_color="white")
    
    # Sauvegarde de l'image dans un flux mémoire
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/png', as_attachment=download, download_name='qr_presence_upl.png')


@app.route('/')
@app.route('/official_qr')
def official_qr():
    """
    Affiche le poster officiel avec le QR code prêt à être imprimé.
    """
    if PUBLIC_URL:
        base_url = PUBLIC_URL.rstrip('/')
        target_url = f"{base_url}{url_for('attendance')}"
    else:
        target_url = url_for('attendance', _external=True)
        
    return render_template('qr_poster.html', target_url=target_url, now_timestamp=int(time.time()))

@app.route('/register', methods=['POST'])
def register():
    """
    Cette fonction sert à RÉCUPÉRER les données envoyées par le formulaire d'inscription.
    Elle enregistre désormais les données sur Supabase Cloud.
    """
    # --- MODIFICATION SUPABASE : Migration vers la base de données Cloud ---
    try:
        # Récupération des données du formulaire
        matricule = request.form['matricule']
        nom = request.form['nom']
        postnom = request.form['postnom']
        prenom = request.form['prenom']
        sexe = request.form['sexe']
        parcours = request.form['parcours']
        promotion = request.form.get('promotion', '')
        filiere = request.form.get('filiere', '')
        faculte = request.form['faculte']

        # Préparation des données pour Supabase
        student_data = {
            "matricule": matricule,
            "nom": nom,
            "postnom": postnom,
            "prenom": prenom,
            "sexe": sexe,
            "parcours": parcours,
            "promotion": promotion,
            "filiere": filiere,
            "faculte": faculte
        }

        # --- Vérification : le matricule existe-t-il déjà ? ---
        already_exists = False
        if supabase:
            try:
                check_res = supabase.table("students").select("matricule").eq("matricule", matricule).execute()
                if check_res.data:
                    already_exists = True
            except Exception:
                pass  # Supabase inaccessible, on vérifiera en local

        if not already_exists:
            # Vérification en local aussi
            try:
                conn_check = get_db_connection()
                cursor_check = conn_check.cursor()
                execute_sql(cursor_check, "SELECT matricule FROM students WHERE matricule = %s", (matricule,))
                if cursor_check.fetchone():
                    already_exists = True
                cursor_check.close()
                conn_check.close()
            except Exception:
                pass

        if already_exists:
            return render_template(
                'register.html',
                error='Ce matricule est déjà utilisé.,
                matricule=matricule,
                nom=nom,
                postnom=postnom,
                prenom=prenom,
                sexe=sexe,
                parcours=parcours,
                promotion=promotion,
                filiere=filiere,
                faculte=faculte
            )

        # --- Insertion : Supabase avec fallback local ---
        saved_to_cloud = False
        if supabase:
            try:
                result = supabase.table("students").insert(student_data).execute()
                saved_to_cloud = True
                print(f"INFO: Étudiant {matricule} enregistré sur Supabase Cloud.")
            except Exception as e_supa:
                err_msg = str(e_supa).lower()
                # Détecter les erreurs de contrainte UNIQUE (duplicate key)
                if 'duplicate' in err_msg or 'unique' in err_msg or '23505' in err_msg or 'already exists' in err_msg:
                    return render_template(
                        'register.html',
                        error='Ce matricule est déjà utilisé. Impossible d\'avoir deux matricules identiques dans la base de données.',
                        matricule=matricule,
                        nom=nom,
                        postnom=postnom,
                        prenom=prenom,
                        sexe=sexe,
                        parcours=parcours,
                        promotion=promotion,
                        filiere=filiere,
                        faculte=faculte
                    )
                print(f"AVERTISSEMENT: Supabase inaccessible ({e_supa}). Fallback vers la base locale.")
                saved_to_cloud = False

        if not saved_to_cloud:
            # Fallback local (SQLite ou MySQL)
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                query = "INSERT INTO students (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                execute_sql(cursor, query, (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte))
                conn.commit()
                conn.close()
                print(f"INFO: Étudiant {matricule} enregistré en local dans la table students.")
            except Exception as e_local:
                err_local = str(e_local).lower()
                if 'unique' in err_local or 'duplicate' in err_local:
                    return render_template(
                        'register.html',
                        error='Ce matricule est déjà utilisé. Impossible d\'avoir deux matricules identiques dans la base de données.',
                        matricule=matricule,
                        nom=nom,
                        postnom=postnom,
                        prenom=prenom,
                        sexe=sexe,
                        parcours=parcours,
                        promotion=promotion,
                        filiere=filiere,
                        faculte=faculte
                    )
                raise  # Re-lever l'erreur si ce n'est pas un doublon

        # Rester sur la page d'inscription et afficher le message de confirmation
        return render_template(
            'register.html',
            success='Saved succes!'
        )
    except Exception as err:
        return f"Erreur lors de l'inscription : {err}"

# --- ROUTES D'AFFICHAGE DES DONNÉES ---

@app.route('/presences')
def view_presences():
    """
    CETTE ROUTE AFFICHE LA TABLE DES PRÉSENCES.
    Elle rassemble les présences de toutes les promotions pour un affichage global.
    """
    try:
        # Suppression de la liste des tables (non nécessaire avec la table globale)
        
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        # la lecture de la table centrale 'presences'

        try:
            execute_sql(cursor, "SELECT * FROM presences ORDER BY date_inscription DESC")
            rows = cursor.fetchall()
            # On convertit en ddictionnaire car sqlite3.Row est immuable
            all_presences = [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]
        except (mysql.connector.Error, sqlite3.Error, Exception):
            all_presences = []

        cursor.close()
        conn.close()

        # 3. FORMATAGE DES DATES pour un affichage propre à l'écran
        for presence in all_presences:
            dt = presence['date_inscription']
            if dt:
                if isinstance(dt, str):
                    try: dt = datetime.strptime(dt.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except: pass
                
                if hasattr(dt, 'strftime'):
                    presence['formatted_date'] = dt.strftime('%d/%m/%Y à %H:%M:%S')
                else:
                    presence['formatted_date'] = str(dt)
            else:
                presence['formatted_date'] = "Inconnue"
        
        # 4. TRI des présences par ordre chronologique décroissant (la plus récente en haut)
        # C'est ici qu'on gère l'ordre demandé par l'utilisateur.
        all_presences.sort(key=lambda x: x['date_inscription'] if x['date_inscription'] else '', reverse=True)
        
        # 5. On envoie les données au template HTML pour l'affichage final
        return render_template('presences.html', presences=all_presences)
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur lors de la récupération des présences : {err}"

@app.route('/admin/timeline')
@login_required
def admin_timeline():
    """
    Affiche l'interface du tableau de bord temps réel (Timeline).
    """
    return render_template('admin_timeline.html')

@app.route('/api/admin/timeline')
@login_required
def api_admin_timeline():
    """
    Renvoie les données consolidées pour la timeline via Supabase.
    --- MODIFICATION SUPABASE : Consolidation Cloud en temps réel ---
    """
    try:
        if supabase:
            now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            today = now_lub.strftime('%Y-%m-%d')
            promo = request.args.get('promotion')

            # 1. Récupération des présences
            query_pres = supabase.table("presences").select("*").gte("date_inscription", today)
            
            if promo:
                # Filtrage intelligent par promotion
                if "_IAGE" in promo:
                    query_pres = query_pres.eq("promotion", promo.replace("_IAGE", "").capitalize())
                else:
                    query_pres = query_pres.ilike("promotion", f"%{promo.replace('_', ' ')}%")
            
            try:
                res_pres = query_pres.order("date_inscription", desc=True).execute()
                presences_list = res_pres.data or []
            except Exception:
                presences_list = []

            reports_list = []
            try:
                res_reports = supabase.table("random_check_responses") \
                    .select("*, random_checks(scheduled_time, type)") \
                    .gte("timestamp", today) \
                    .order("timestamp", desc=True) \
                    .execute()
                reports_list = res_reports.data or []
            except Exception:
                reports_list = []

            # Filtrage par matricule si une promotion est sélectionnée
            if promo:
                valid_mats = [p['matricule'] for p in presences_list]
                reports_list = [r for r in reports_list if r['matricule'] in valid_mats]

            return jsonify({
                "presences": presences_list,
                "reports": reports_list
            })
        else:
            return jsonify({"presences": [], "reports": []})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/export_sql')
def export_sql():
    """
    Génère un fichier .sql compatible MySQL pour importer les présences 
    depuis Render vers XAMPP.
    """
    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
            
        # On récupère toutes les présences
        execute_sql(cursor, "SELECT * FROM presences ORDER BY date_inscription ASC")
        rows = cursor.fetchall()
        
        # Construction du script SQL
        sql_content = "/* EXPORT DES PRÉSENCES UPL - DEPUIS RENDER VERS XAMPP */\n"
        sql_content += "/* Importez ce fichier dans l'onglet 'Importer' de phpMyAdmin */\n\n"
        
        # On s'assure que la table existe côté MySQL (au cas où)
        # Mais l'utilisateur l'a déjà normalement.
        
        for row in rows:
            # Formattage des valeurs pour SQL
            # On échappe les guillemets simples pour éviter les erreurs SQL
            def escape(val):
                if val is None: return "NULL"
                if isinstance(val, (int, float)): return str(val)
                # Conversion date
                if hasattr(val, 'strftime'):
                    return f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'"
                # String simple
                safe_val = str(val).replace("'", "''")
                return f"'{safe_val}'"

            vals = [
                escape(row['matricule']),
                escape(row['nom']),
                escape(row['postnom']),
                escape(row['prenom']),
                escape(row['sexe']),
                escape(row['parcours']),
                escape(row['promotion']),
                escape(row['filiere']),
                escape(row['faculte']),
                escape(row['type_presence']),
                escape(row['device_signature']),
                escape(row['date_inscription'])
            ]
            
            sql_content += f"INSERT INTO presences (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, date_inscription) VALUES ({', '.join(vals)});\n"
        
        cursor.close()
        conn.close()
        
        # Envoi du fichier au navigateur
        output = io.BytesIO(sql_content.encode('utf-8'))
        return send_file(
            output,
            mimetype='text/sql',
            as_attachment=True,
            download_name=f"export_presences_upl_{datetime.now().strftime('%d_%m_%Y')}.sql"
        )
        
    except Exception as e:
        return f"Erreur lors de l'exportation : {e}"

@app.route('/students')
@app.route('/students_list')
@app.route('/students/<promo>')
def view_students(promo=None):
    """
    Rend simplement la page de la liste des étudiants.
    Si promo est fourni, l'interface se concentrera sur cette promotion.
    """
    return render_template('students_list.html', promo=promo)

# --- API ENDPOINTS ---

@app.route('/api/presences')
def api_presences():
    """
    API endpoint qui retourne les présences depuis Supabase Cloud.
    """
    promo = request.args.get('promotion')
    faculte = request.args.get('faculte')
    filiere = request.args.get('filiere')
    parcours = request.args.get('parcours')
    promotion_label = request.args.get('promotion_label')

    try:
        if supabase:
            query = supabase.table("presences").select("*")
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    query = query.eq("parcours", "IAGE").eq("promotion", p_name)
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        query = query.eq("parcours", "TECHNOLOGIE").eq("promotion", promo_name).eq("filiere", filiere_name)
                else:
                    query = query.eq("promotion", promo)
            else:
                if faculte: query = query.eq("faculte", faculte)
                if filiere: query = query.eq("filiere", filiere)
                if parcours: query = query.eq("parcours", parcours)
                if promotion_label: query = query.eq("promotion", promotion_label)

            result = query.order("date_inscription", desc=True).execute()
            all_presences = result.data
        else:
            # Fallback local
            conn = get_db_connection()
            if isinstance(conn, sqlite3.Connection):
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(dictionary=True)

            sql = "SELECT * FROM presences WHERE 1=1"
            params = []

            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    sql += " AND parcours = %s AND promotion = %s"
                    params.extend(["IAGE", p_name])
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        sql += " AND parcours = %s AND promotion = %s AND filiere = %s"
                        params.extend(["TECHNOLOGIE", promo_name, filiere_name])
                else:
                    sql += " AND promotion = %s"
                    params.append(promo)
            else:
                if faculte:
                    sql += " AND faculte = %s"
                    params.append(faculte)
                if filiere:
                    sql += " AND filiere = %s"
                    params.append(filiere)
            sql += " ORDER BY date_inscription DESC"
            
            if isinstance(conn, sqlite3.Connection):
                sql = sql.replace("%s", "?")
                cursor.execute(sql, params)
                all_presences = [dict(row) for row in cursor.fetchall()]
            else:
                cursor.execute(sql, params)
                all_presences = cursor.fetchall()
                
            cursor.close()
            conn.close()

        # Formatage des données pour le frontend
        for row in all_presences:
            dt_str = row.get('date_inscription')
            if isinstance(dt_str, datetime):
                dt_str = dt_str.isoformat()
            elif hasattr(dt_str, 'strftime'):
                dt_str = dt_str.strftime('%Y-%m-%dT%H:%M:%S')
                
            if dt_str and 'T' in dt_str:
                row['formatted_date'] = dt_str.split('T')[0]
                row['formatted_time'] = dt_str.split('T')[1].split('+')[0]
            else:
                row['formatted_date'] = "N/A"
                row['formatted_time'] = "N/A"

        return jsonify(all_presences)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/attendance/check/respond', methods=['POST'])
def respond_to_check():
    """
    Endpoint pour répondre à un contrôle aléatoire (PIN) via Supabase.
    --- MODIFICATION SUPABASE : Validation Cloud ---
    """
    check_id = request.json.get('check_id')
    value = request.json.get('value')
    
    try:
        if supabase:
            # 1. Récupération du check
            res = supabase.table("attendance_checks").select("expected_value").eq("id", check_id).eq("status", "PENDING").execute()
            if not res.data:
                return jsonify({"status": "error", "message": "Contrôle non trouvé ou déjà expiré"}), 404
            
            expected = res.data[0]['expected_value']
            status = 'SUCCESS' if str(value) == str(expected) else 'FAILED'
            now = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            
            # 2. Mise à jour du statut
            supabase.table("attendance_checks").update({
                "received_value": value,
                "status": status,
                "responded_at": now.isoformat()
            }).eq("id", check_id).execute()
            
            return jsonify({"status": "success", "result": status})
        else:
            return jsonify({"status": "error", "message": "Supabase non configuré"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/trigger_check', methods=['POST'])
@login_required
def trigger_check():
    """
    Simule le déclenchement d'un contrôle aléatoire pour un étudiant via Supabase.
    """
    matricule = request.json.get('matricule')
    pin = "1234" 
    
    try:
        if supabase:
            # 1. On trouve la dernière tentative acceptée aujourd'hui sur Supabase
            now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            today = now_lub.strftime('%Y-%m-%d')
            
            res_att = supabase.table("attendance_attempts") \
                .select("id") \
                .eq("student_external_id", matricule) \
                .eq("result", "Accepté") \
                .gte("timestamp", today) \
                .order("timestamp", desc=True) \
                .limit(1).execute()
            
            if not res_att.data:
                return jsonify({"status": "error", "message": "Aucune présence valide trouvée pour cet étudiant aujourd'hui sur le cloud"}), 404
                
            attempt_id = res_att.data[0]['id']
            
            # 2. Insertion du check
            supabase.table("attendance_checks").insert({
                "attempt_id": attempt_id,
                "check_type": 'PIN',
                "expected_value": pin,
                "status": 'PENDING'
            }).execute()
            
            return jsonify({"status": "success", "message": "Contrôle déclenché (PIN attendu: 1234)"})
        else:
            return jsonify({"status": "error", "message": "Supabase non configuré"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/presence_stats')
def api_presence_stats():
    """
    API endpoint qui retourne des statistiques sur les présences via Supabase.
    """
    promo = request.args.get('promotion')
    faculte = request.args.get('faculte')
    filiere = request.args.get('filiere')
    parcours = request.args.get('parcours')
    promotion_label = request.args.get('promotion_label')
    
    try:
        if supabase:
            query = supabase.table("presences").select("type_presence")
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    query = query.eq("parcours", "IAGE").eq("promotion", p_name)
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        query = query.eq("parcours", "TECHNOLOGIE").eq("promotion", promo_name).eq("filiere", filiere_name)
                else:
                    query = query.ilike("promotion", f"%{promo.replace('_', ' ')}%")
            else:
                if faculte: query = query.eq("faculte", faculte)
                if filiere: query = query.eq("filiere", filiere)
                if parcours: query = query.eq("parcours", parcours)
                if promotion_label: query = query.eq("promotion", promotion_label)
            
            res = query.execute()
            rows = res.data
            
            total = len(rows)
            entrees = len([r for r in rows if r['type_presence'] == 'Entrée'])
            sorties = len([r for r in rows if r['type_presence'] == 'Sortie'])
            
            return jsonify({
                "total": total,
                "entrees": entrees,
                "sorties": sorties
            })
        else:
            # Fallback local
            conn = get_db_connection()
            if isinstance(conn, sqlite3.Connection):
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(dictionary=True)
                
            sql = "SELECT type_presence FROM presences WHERE 1=1"
            params = []
            
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    sql += " AND parcours = %s AND promotion = %s"
                    params.extend(["IAGE", p_name])
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        sql += " AND parcours = %s AND promotion = %s AND filiere = %s"
                        params.extend(["TECHNOLOGIE", promo_name, filiere_name])
                else:
                    sql += " AND promotion LIKE %s"
                    params.append(f"%{promo.replace('_', ' ')}%")
            else:
                if faculte:
                    sql += " AND faculte = %s"
                    params.append(faculte)
                if filiere:
                    sql += " AND filiere = %s"
                    params.append(filiere)
                if parcours:
                    sql += " AND parcours = %s"
                    params.append(parcours)
                if promotion_label:
                    sql += " AND promotion = %s"
                    params.append(promotion_label)
            
            if isinstance(conn, sqlite3.Connection):
                sql = sql.replace("%s", "?")
                cursor.execute(sql, params)
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                
            cursor.close()
            conn.close()

            total = len(rows)
            entrees = len([r for r in rows if r.get('type_presence') == 'Entrée'])
            sorties = len([r for r in rows if r.get('type_presence') == 'Sortie'])
            
            return jsonify({
                "total": total,
                "entrees": entrees,
                "sorties": sorties
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/students')
def api_students():
    """
    API endpoint that returns students in JSON format.
    """
    promo = request.args.get('promotion')
    faculte = request.args.get('faculte')
    parcours = request.args.get('parcours')
    promotion_label = request.args.get('promotion_label')
    
    try:
        if supabase:
            query = supabase.table("students").select("*")
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    query = query.eq("parcours", "IAGE").eq("promotion", p_name)
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        query = query.eq("parcours", "TECHNOLOGIE").eq("promotion", promo_name).eq("filiere", filiere_name)
                else:
                    query = query.eq("promotion", promo)
            else:
                if faculte: query = query.eq("faculte", faculte)
                if parcours: query = query.eq("parcours", parcours)
                if promotion_label: query = query.eq("promotion", promotion_label)
            
            result = query.order("date_inscription", desc=True).execute()
            all_students = result.data
        else:
            # Fallback local
            conn = get_db_connection()
            if isinstance(conn, sqlite3.Connection):
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(dictionary=True)
                
            sql = "SELECT * FROM students WHERE 1=1"
            params = []
            
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    sql += " AND parcours = %s AND promotion = %s"
                    params.extend(["IAGE", p_name])
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        sql += " AND parcours = %s AND promotion = %s AND filiere = %s"
                        params.extend(["TECHNOLOGIE", promo_name, filiere_name])
                else:
                    sql += " AND promotion = %s"
                    params.append(promo)
            else:
                if faculte:
                    sql += " AND faculte = %s"
                    params.append(faculte)
                if parcours:
                    sql += " AND parcours = %s"
                    params.append(parcours)
                if promotion_label:
                    sql += " AND promotion = %s"
                    params.append(promotion_label)
                    
            sql += " ORDER BY date_inscription DESC"
            
            if isinstance(conn, sqlite3.Connection):
                sql = sql.replace("%s", "?")
                cursor.execute(sql, params)
                all_students = [dict(row) for row in cursor.fetchall()]
            else:
                cursor.execute(sql, params)
                all_students = cursor.fetchall()
                
            cursor.close()
            conn.close()
        
        # Formatage des dates pour l'affichage
        for student in all_students:
            dt_str = student.get('date_inscription')
            if isinstance(dt_str, datetime):
                dt_str = dt_str.isoformat()
            elif hasattr(dt_str, 'strftime'):
                dt_str = dt_str.strftime('%Y-%m-%dT%H:%M:%S')
                
            if dt_str:
                student['formatted_date'] = dt_str.replace('T', ' ').split('.')[0]
            else:
                student['formatted_date'] = "N/A"
                
        return jsonify(all_students)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats')
def api_stats():
    """
    API endpoint that returns student statistics via Supabase.
    """
    promo = request.args.get('promotion')
    faculte = request.args.get('faculte')
    parcours = request.args.get('parcours')
    promotion_label = request.args.get('promotion_label')

    try:
        if supabase:
            query = supabase.table("students").select("sexe")
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    query = query.eq("parcours", "IAGE").eq("promotion", p_name)
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        query = query.eq("parcours", "TECHNOLOGIE").eq("promotion", promo_name).eq("filiere", filiere_name)
                else:
                    query = query.ilike("promotion", f"%{promo.replace('_', ' ')}%")
            else:
                if faculte: query = query.eq("faculte", faculte)
                if parcours: query = query.eq("parcours", parcours)
                if promotion_label: query = query.eq("promotion", promotion_label)
            
            res = query.execute()
            rows = res.data
            
            male_count = len([r for r in rows if r['sexe'] == 'M'])
            female_count = len([r for r in rows if r['sexe'] == 'F'])
            total_count = len(rows)
            
            return jsonify({
                "total_students": total_count,
                "male_count": male_count,
                "female_count": female_count
            })
        else:
            # Fallback local
            conn = get_db_connection()
            if isinstance(conn, sqlite3.Connection):
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(dictionary=True)
                
            sql = "SELECT sexe FROM students WHERE 1=1"
            params = []
            
            if promo:
                if "_IAGE" in promo:
                    p_name = promo.split("_")[0].capitalize()
                    sql += " AND parcours = %s AND promotion = %s"
                    params.extend(["IAGE", p_name])
                elif "_tech_" in promo:
                    parts = promo.split("_tech_")
                    if len(parts) == 2:
                        promo_name = parts[0].capitalize()
                        filiere_name = parts[1].upper()
                        sql += " AND parcours = %s AND promotion = %s AND filiere = %s"
                        params.extend(["TECHNOLOGIE", promo_name, filiere_name])
                else:
                    sql += " AND promotion LIKE %s"
                    params.append(f"%{promo.replace('_', ' ')}%")
            else:
                if faculte:
                    sql += " AND faculte = %s"
                    params.append(faculte)
                if parcours:
                    sql += " AND parcours = %s"
                    params.append(parcours)
                if promotion_label:
                    sql += " AND promotion = %s"
                    params.append(promotion_label)
            
            if isinstance(conn, sqlite3.Connection):
                sql = sql.replace("%s", "?")
                cursor.execute(sql, params)
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                
            cursor.close()
            conn.close()
            
            male_count = len([r for r in rows if r.get('sexe') == 'M'])
            female_count = len([r for r in rows if r.get('sexe') == 'F'])
            total_count = len(rows)
            
            return jsonify({
                "total_students": total_count,
                "male_count": male_count,
                "female_count": female_count
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- DEBOGAGE ---

@app.route('/debug_db')
def debug_db():
    """
    Route de secours pour voir si la base contient des données.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Récupération de toutes les tables
        if isinstance(conn, sqlite3.Connection):
            execute_sql(cursor, "SELECT name FROM sqlite_master WHERE type='table'")
        else:
            execute_sql(cursor, "SHOW TABLES")
        
        tables = [row[0] for row in cursor.fetchall()]
        
        db_info = {}
        for table in tables:
            try:
                execute_sql(cursor, f"SELECT COUNT(*) FROM {table}")
                db_info[table] = cursor.fetchone()[0]
            except:
                db_info[table] = "Error"
        
        cursor.close()
        conn.close()
        return jsonify({
            "environment": "SQLite (Render/Fallback)" if isinstance(conn, sqlite3.Connection) else "MySQL (Local)",
            "tables": db_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- ADMINISTRATION ---

@app.route('/admin')
@login_required
def admin_dashboard():
    """
    Tableau de bord pour l'administrateur montrant quelques statistiques.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Compte total des étudiants (fallback local)
        try:
            execute_sql(cursor, "SELECT COUNT(*) FROM students")
            bac1_count = cursor.fetchone()[0]
        except:
            bac1_count = 0
        
        # Compte total des présences (fallback local)
        try:
            execute_sql(cursor, "SELECT COUNT(*) FROM presences")
            presence_count = cursor.fetchone()[0]
        except:
            presence_count = 0
        
        cursor.close()
        conn.close()
        return render_template('students_list.html', bac1_count=bac1_count, presence_count=presence_count)
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur : {err}"

@app.route('/admin/students')
@login_required
def admin_students():
    """Redirection vers la nouvelle interface unifiée Supabase."""
    return redirect(url_for('view_students'))

@app.route('/admin/bac1_iage')
@login_required
def admin_bac1_iage():
    """Redirection vers la vue filtrée Supabase pour Bac1 IAGE."""
    return redirect(url_for('view_students', promo='bac1_IAGE'))

@app.route('/admin/attendance')
def admin_attendance():
    """Redirection vers la vue globale des présences."""
    return redirect(url_for('view_presences'))

@app.route('/admin/reset_table', methods=['POST'])
@login_required
def reset_table():
    """
    Cette route sert à réinitialiser (vider) une table de données.
    """
    table_name = request.form.get('table_name')
    
    allowed_tables = ['students', 'presences']
    
    if table_name not in allowed_tables and table_name != 'presence': # 'presence' is old UI param
        return "Table non autorisée ou invalide."
        
    try:
        if supabase:
            # Pour Supabase, la table s'appelle "students" ou "presences"
            if table_name == 'presence':
                # Vider toute la table presences
                supabase.table("presences").delete().neq('id', 0).execute()
            elif table_name.startswith('presence_'):
                # Exemple: presence_bac1_IAGE
                parts = table_name.replace('presence_', '').split('_')
                if 'tech' in table_name:
                    promo = parts[0].capitalize()  # Bac1
                    filiere = parts[2].upper()     # IA
                    supabase.table("presences").delete().eq("parcours", "TECHNOLOGIE").eq("promotion", promo).eq("filiere", filiere).execute()
                else:
                    promo = parts[0].capitalize()
                    supabase.table("presences").delete().eq("parcours", "IAGE").eq("promotion", promo).execute()
            else:
                # C'est une table d'étudiants (ex: bac1_IAGE)
                parts = table_name.split('_')
                if 'tech' in table_name:
                    promo = parts[0].capitalize()
                    filiere = parts[2].upper()
                    # La suppression en cascade effacera aussi les présences associées
                    supabase.table("students").delete().eq("parcours", "TECHNOLOGIE").eq("promotion", promo).eq("filiere", filiere).execute()
                else:
                    promo = parts[0].capitalize()
                    supabase.table("students").delete().eq("parcours", "IAGE").eq("promotion", promo).execute()
        
        # Fallback local (XAMPP / SQLite)
        conn = get_db_connection()
        cursor = conn.cursor()
        if isinstance(conn, sqlite3.Connection):
            execute_sql(cursor, f"DELETE FROM {table_name}")
            execute_sql(cursor, "DELETE FROM sqlite_sequence WHERE name=?", (table_name,))
        else:
            execute_sql(cursor, f"TRUNCATE TABLE {table_name}")
        conn.commit()
        cursor.close()
        conn.close()
        
        if table_name.startswith('presence'):
            return redirect(url_for('view_presences'))
        else:
            return redirect(url_for('view_students', promo=table_name))
            
    except Exception as err:
        return f"Erreur lors de la réinitialisation : {err}"

@app.route('/admin/delete_student', methods=['POST'])
@login_required
def delete_student():
    """
    Supprime un étudiant spécifique (et ses présences en cascade).
    """
    matricule = request.form.get('matricule')
    if not matricule:
        return "Matricule manquant."
        
    try:
        if supabase:
            supabase.table("students").delete().eq("matricule", matricule).execute()
            # Si jamais certaines présences n'ont pas la contrainte CASCADE, on force :
            supabase.table("presences").delete().eq("matricule", matricule).execute()
            
        # Fallback local
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            execute_sql(cursor, "DELETE FROM students WHERE matricule = %s", (matricule,))
            execute_sql(cursor, "DELETE FROM presences WHERE matricule = %s", (matricule,))
        except Exception as e:
            print(f"Erreur suppression locale: {e}")
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('view_students'))
    except Exception as err:
        return f"Erreur lors de la suppression de l'étudiant : {err}"

@app.route('/admin/reset_all', methods=['POST'])
@login_required
def reset_all():
    """
    Supprime de manière irréversible toutes les données du système (Étudiants et Présences).
    """
    try:
        if supabase:
            # Ne supprime pas l'historique RLS mais vide les données
            safe_supabase_delete("presences")
            safe_supabase_delete("students")
            safe_supabase_delete("attendance_attempts")
            safe_supabase_delete("attendance_checks")
            safe_supabase_delete("random_check_responses")
            
        # Fallback local
        conn = get_db_connection()
        cursor = conn.cursor()
        
        all_tables = ['students', 'presences', 'attendance_attempts', 'attendance_checks', 'random_check_responses']
        
        for t in all_tables:
            try:
                if isinstance(conn, sqlite3.Connection):
                    execute_sql(cursor, f"DELETE FROM {t}")
                    execute_sql(cursor, "DELETE FROM sqlite_sequence WHERE name=?", (t,))
                else:
                    execute_sql(cursor, f"TRUNCATE TABLE {t}")
            except: pass
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('view_students'))
    except Exception as err:
        return f"Erreur critique lors de la réinitialisation globale : {err}"

@app.route('/general-dashboard')
@app.route('/admin/general_dashboard')
@login_required
def admin_general_dashboard():
    """
    Rends le nouveau tableau de bord de rapport général.
    """
    return render_template('general_dashboard.html')

@app.route('/api/admin/stats_summary')
@login_required
def api_admin_stats_summary():
    """
    Retourne un résumé des statistiques pour le dashboard via Supabase.
    --- MODIFICATION SUPABASE : Agrégation Cloud complète ---
    """
    try:
        if supabase:
            now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            today = now_lub.strftime('%Y-%m-%d')

            # 1. Étudiants Totaux
            res_total = supabase.table("students").select("id", count="exact").execute()
            total_students = res_total.count or 0

            # 1b. Genre des étudiants
            male_count = 0
            female_count = 0
            try:
                res_gender = supabase.table("students").select("sexe").execute()
                for row in res_gender.data or []:
                    sexe = (row.get('sexe') or '').strip().upper()
                    if sexe == 'M':
                        male_count += 1
                    elif sexe == 'F':
                        female_count += 1
            except Exception:
                pass

            # 2. Présences du jour
            today_presences = []
            try:
                res_pres = supabase.table("presences").select("type_presence, status_geoloc").gte("date_inscription", today).execute()
                today_presences = res_pres.data or []
            except Exception:
                today_presences = []
            
            entrees_today = len([p for p in today_presences if p.get('type_presence') == 'Entrée'])
            sorties_today = len([p for p in today_presences if p.get('type_presence') == 'Sortie'])
            hors_zone_today = len([p for p in today_presences if p.get('status_geoloc') and 'Hors Zone' in p['status_geoloc']])
            
            # 3. Fraudes du jour
            fraudes_pres = len([p for p in today_presences if p.get('status_geoloc') and 'Fraude' in p['status_geoloc']])
            report_rows = []
            try:
                res_reports = supabase.table("random_check_responses").select("result").gte("timestamp", today).execute()
                report_rows = res_reports.data or []
            except Exception:
                report_rows = []
            fraudes_reports = len([r for r in report_rows if (r.get('result') or '').lower() == 'fraude'])
            suivis_ok_today = len([r for r in report_rows if (r.get('result') or '').lower() == 'confirmé'])
            
            fraudes_today = fraudes_pres + fraudes_reports

            # 4. Historique des 7 derniers jours
            history_points = []
            for i in range(6, -1, -1):
                day_dt = now_lub - timedelta(days=i)
                day_start = day_dt.strftime('%Y-%m-%d')
                day_end = (day_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                day_label = day_dt.strftime('%d/%m')
                
                try:
                    res_day = supabase.table("presences").select("id", count="exact").gte("date_inscription", day_start).lt("date_inscription", day_end).execute()
                    count_day = res_day.count or 0
                except Exception:
                    count_day = 0
                try:
                    res_fraude = supabase.table("random_check_responses").select("id", count="exact").eq("result", "fraude").gte("timestamp", day_start).lt("timestamp", day_end).execute()
                    fraude_count = res_fraude.count or 0
                except Exception:
                    fraude_count = 0
                history_points.append({"label": day_label, "count": count_day, "fraudes": fraude_count})

            return jsonify({
                "total_students": total_students,
                "male_count": male_count,
                "female_count": female_count,
                "entrees_today": entrees_today,
                "sorties_today": sorties_today,
                "hors_zone_today": hors_zone_today,
                "fraudes_today": fraudes_today,
                "suivis_ok_today": suivis_ok_today,
                "history": history_points
            })
        else:
            return jsonify({"error": "Supabase non configuré"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# Lancement du serveur
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)