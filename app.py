import mysql.connector
import sqlite3
import qrcode
import io
import traceback
from flask import Flask, request, render_template, redirect, url_for, jsonify, send_file
from datetime import datetime, timedelta, timezone
try:
    from db_config import host, user, password, database
except ImportError:
    # Paramètres par défaut si db_config.py est absent (cas de Render)
    host = user = password = database = None

import os
import math

# Aide pour la compatibilité MySQL/SQLite
def execute_sql(cursor, query, params=None):
    if params is None:
        # On remplace %s par ? même sans paramètres car SQLite est strict
        query = query.replace('%s', '?')
        return cursor.execute(query)
    # Si on utilise SQLite, on remplace %s par ?
    if 'sqlite' in str(type(cursor)).lower():
        query = query.replace('%s', '?')
    return cursor.execute(query, params)

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

# --- CONFIGURATION DU SYSTÈME DE VALIDATION ---
# Ces valeurs peuvent être ajustées selon les besoins
ACCURACY_MAX = 50.0      # Précision GPS maximale acceptée (mètres)
TIME_MAX_SECONDS = 300   # Fenêtre de temps maximale (secondes)
DEFAULT_TOLERANCE = 10.0 # Tolérance par défaut (mètres)

# --- CONFIGURATION DE L'URL PUBLIQUE (NGROK) ---
# Si vous utilisez Ngrok, modifiez cette variable avec votre lien https://...
# Sinon, laissez vide pour utiliser l'adresse locale.
PUBLIC_URL = os.environ.get('PUBLIC_URL', '') 
if PUBLIC_URL and not PUBLIC_URL.startswith(('http://', 'https://')):
    PUBLIC_URL = f"https://{PUBLIC_URL}"

# --- CONFIGURATION DE LA CONNEXION À LA BASE DE DONNÉES ---
def get_db_connection():
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
        
        # Liste des tables à créer
        student_tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        
        for table in student_tables:
            # Table des étudiants par promotion
            execute_sql(cursor, f'''
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    matricule TEXT UNIQUE,
                    nom TEXT,
                    postnom TEXT,
                    prenom TEXT,
                    sexe TEXT,
                    parcours TEXT,
                    promotion TEXT,
                    filiere TEXT,
                    faculte TEXT,
                    date_inscription DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table de présence spécifique par promotion
            execute_sql(cursor, f'''
                CREATE TABLE IF NOT EXISTS presence_{table} (
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
        
        conn.commit()
        conn.close()
            
# Initialisation et Migration de la base de données
def upgrade_db():
    """
    S'assure que toutes les colonnes nécessaires existent dans la base (MySQL ou SQLite).
    Ajoute dynamiquement latitude, longitude et device_signature si absents.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 0. Création de 'presences' si elle n'existe pas (Sécurité pour Render)
        if not isinstance(conn, sqlite3.Connection):
             # MySQL version
             execute_sql(cursor, '''
                CREATE TABLE IF NOT EXISTS presences (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    matricule VARCHAR(50),
                    nom VARCHAR(100),
                    postnom VARCHAR(100),
                    prenom VARCHAR(100),
                    sexe VARCHAR(10),
                    parcours VARCHAR(100),
                    promotion VARCHAR(100),
                    filiere VARCHAR(100),
                    faculte VARCHAR(100),
                    type_presence VARCHAR(20),
                    device_signature VARCHAR(100),
                    latitude DOUBLE,
                    longitude DOUBLE,
                    date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        # 1. Vérification des colonnes pour la table 'presences'
        columns_to_add = [
            ('device_signature', 'TEXT' if isinstance(conn, sqlite3.Connection) else 'VARCHAR(100)'),
            ('latitude', 'REAL' if isinstance(conn, sqlite3.Connection) else 'DOUBLE'),
            ('longitude', 'REAL' if isinstance(conn, sqlite3.Connection) else 'DOUBLE')
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                if isinstance(conn, sqlite3.Connection):
                    execute_sql(cursor, f"ALTER TABLE presences ADD COLUMN {col_name} {col_type}")
                else:
                    execute_sql(cursor, f"ALTER TABLE presences ADD {col_name} {col_type}")
            except:
                pass

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erreur lors de la migration : {e}")

# Initialisation automatique au démarrage
init_sqlite_db()
upgrade_db()

# --- ROUTES DE NAVIGATION ---

# Route d'accueil : Affiche le formulaire d'inscription par défaut
@app.route('/register_student')
def index():
    return render_template('register.html')

# Nouveau formulaire d'inscription (Premium)
@app.route('/add_student')
def add_student_form():
    """
    Cette route affiche le nouveau formulaire d'inscription premium.
    """
    return render_template('add_student.html')

# Route pour la page de présence
@app.route('/attendance')
def attendance():
    return render_template('attendance.html')

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
        query_aud = "SELECT * FROM auditoriums WHERE code = %s"
        execute_sql(cursor, query_aud, (auditorium_code,))
        aud_res = cursor.fetchone()
        
        if not aud_res:
            return jsonify({"status": "error", "message": "Auditoire invalide"}), 404
        
        # Adaptateur pour SQLite/MySQL
        aud = dict(aud_res) if not isinstance(aud_res, tuple) else {
            'code': aud_res[0], 'nom': aud_res[1], 'latitude': aud_res[2], 
            'longitude': aud_res[3], 'radius_m': aud_res[4], 'floor': aud_res[5], 
            'tolerance_m': aud_res[6], 'version': aud_res[7]
        }

        # 3. Calcul de la distance et validation GPS
        distance = calculate_distance(lat, lon, aud['latitude'], aud['longitude'])
        max_allowed_distance = aud['radius_m'] + aud['tolerance_m']
        
        result = "Rejeté"
        reason = ""
        
        if lat is None or lon is None:
            reason = "GPS manquant"
        elif accuracy > ACCURACY_MAX:
            reason = f"Précision GPS insuffisante ({accuracy}m > {ACCURACY_MAX}m)"
        elif distance > max_allowed_distance:
            reason = f"Hors zone ({int(distance)}m de l'auditoire)"
        else:
            result = "Accepté"

        # 4. Vérification de l'étudiant dans les listes
        found = False
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        
        student_data = None
        for table in tables:
            query = f"SELECT nom, postnom, prenom, filiere, promotion, sexe, faculte, parcours FROM {table} WHERE matricule = %s"
            execute_sql(cursor, query, (matricule,))
            res = cursor.fetchone()
            if res:
                student_data = res
                found = True
                break
        
        if not found:
            reason = "Matricule inconnu"
            result = "Rejeté"
        elif result == "Accepté":
            # Vérifications additionnelles (doublons, séquence)
            # Protection contre les doublons d'appareils
            check_device_query = "SELECT device_signature FROM presences WHERE matricule = %s AND date(date_inscription) = %s LIMIT 1"
            execute_sql(cursor, check_device_query, (matricule, today_date))
            device_res = cursor.fetchone()
            
            if device_res:
                existing_sig = device_res['device_signature'] if not isinstance(device_res, tuple) else device_res[0]
                if existing_sig != device_signature:
                    reason = "Appareil différent utilisé"
                    result = "Rejeté"

            if result == "Accepté":
                # Logique de séquence (Entrée -> Sortie)
                check_sequence_query = "SELECT type_presence FROM presences WHERE matricule = %s AND date(date_inscription) = %s ORDER BY date_inscription DESC"
                execute_sql(cursor, check_sequence_query, (matricule, today_date))
                history = cursor.fetchall()
                
                today_types = [row['type_presence'] if not isinstance(row, tuple) else row[0] for row in history]
                last_type = today_types[0] if today_types else None
                
                if type_presence == 'Entrée' and last_type == 'Entrée':
                    reason = "Déjà une entrée active"
                    result = "Rejeté"
                elif type_presence == 'Sortie' and last_type != 'Entrée':
                    reason = "Pas d'entrée correspondante"
                    result = "Rejeté"

        # 5. JOURNALISATION IMMUABLE (attendance_attempts)
        insert_attempt = """
            INSERT INTO attendance_attempts 
            (student_external_id, auditorium_code, latitude, longitude, accuracy_meters, timestamp, device_id, ip, device_info, distance, result, reason, auditorium_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_sql(cursor, insert_attempt, (matricule, auditorium_code, lat, lon, accuracy, now_lubumbashi, device_signature, user_ip, device_info, distance, result, reason, aud['version']))
        
        # 6. Si validé, enregistrement final
        if result == "Accepté":
            nom, postnom, prenom, filiere, promotion, sexe, faculte, parcours = student_data
            status_geoloc = f"Validé ({auditorium_code})"
            
            # Table globale
            insert_query = """
                INSERT INTO presences 
                (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, latitude, longitude, status_geoloc, date_inscription) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            execute_sql(cursor, insert_query, (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, lat, lon, status_geoloc, now_lubumbashi))
            
            # Table spécifique
            specific_table = f"presence_{promotion.lower().replace(' ', '_')}" # A adapter si besoin
            # Note: ici j'utilise la logique existante simplifiée
            
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Présence enregistrée avec succès", "auditorium": aud['nom']})
        else:
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": reason or "Validation échouée"}), 403

    except Exception as e:
        traceback.print_exc()
        if 'conn' in locals() and conn: conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/student/<matricule>')
def get_student_info(matricule):
    print(f"DEBUG: get_student_info called for {matricule}")
    """
    Recherche un étudiant par son matricule dans toutes les promotions.
    """
    matricule = matricule.strip()
    # On utilise des noms de tables en minuscules pour la compatibilité MySQL
    tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]
    
    conn = None
    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        found_data = None
        for table in tables:
            query = f"SELECT * FROM {table} WHERE matricule = %s"
            execute_sql(cursor, query, (matricule,))
            result = cursor.fetchone()
            if result:
                found_data = dict(result) if not isinstance(result, dict) else result
                break
        
        if found_data:
            # Stats de présence pour aujourd'hui
            now_lub = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
            today = now_lub.strftime('%Y-%m-%d')
            
            query_stats = "SELECT type_presence FROM presences WHERE matricule = %s AND date(date_inscription) = %s ORDER BY date_inscription DESC"
            execute_sql(cursor, query_stats, (matricule, today))
            history = cursor.fetchall()
            
            types = [row['type_presence'] if isinstance(row, dict) else row[0] for row in history]
            found_data['last_type'] = types[0] if types else None
            found_data['count_today'] = len(types)
            
            # Vérification de contrôle aléatoire en attente
            q_check = """
                SELECT c.id, c.check_type 
                FROM attendance_checks c
                JOIN attendance_attempts a ON c.attempt_id = a.id
                WHERE a.student_external_id = %s AND c.status = 'PENDING'
                ORDER BY c.sent_at DESC LIMIT 1
            """
            execute_sql(cursor, q_check, (matricule,))
            check_res = cursor.fetchone()
            if check_res:
                found_data['pending_check'] = dict(check_res) if not isinstance(check_res, dict) else check_res
            else:
                found_data['pending_check'] = None

            cursor.close()
            conn.close()
            return jsonify(found_data)
        
        cursor.close()
        conn.close()
        return jsonify({"error": "Étudiant non trouvé"}), 404
        
    except Exception as e:
        traceback.print_exc()
        if conn: conn.close()
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
        # Nettoyage de l'URL pour éviter les doubles slashes
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
        
    return render_template('qr_poster.html', target_url=target_url)

@app.route('/register', methods=['POST'])
def register():
    """
    Cette fonction sert à RÉCUPÉRER les données envoyées par le formulaire d'inscription.
    Elle identifie ensuite la table correcte en fonction du parcours et de la promotion,
    puis ENREGISTRE les données dans la base de données.
    """
    try:
        # Récupération des données du formulaire via request.form
        matricule = request.form['matricule']
        nom = request.form['nom']
        postnom = request.form['postnom']
        prenom = request.form['prenom']
        sexe = request.form['sexe']
        parcours = request.form['parcours']
        promotion = request.form.get('promotion', '')
        filiere = request.form.get('filiere', '')
        faculte = request.form['faculte']

        # Determination de la table cible
        if parcours == 'IAGE':
            table = f"{promotion.lower()}_IAGE"
        elif parcours == 'TECHNOLOGIE':
            table = f"{promotion.lower()}_tech_{filiere.upper()}"
        else:
            return "Parcours invalide"

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ce code sert à INSÉRER les données récupérées dans la table appropriée
        query = f"INSERT INTO {table} (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        execute_sql(cursor, query, (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte))
        
        conn.commit()
        cursor.close()
        conn.close()
        # Message de succès après enregistrement : redirection vers la liste spécifique
        return redirect(url_for('view_students', promo=table))
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur lors de l'inscription : {err}"
    except Exception as e:
        return f"Une erreur est survenue : {e}"

# --- ROUTES D'AFFICHAGE DES DONNÉES ---

@app.route('/presences')
def view_presences():
    """
    CETTE ROUTE AFFICHE LA TABLE DES PRÉSENCES.
    Elle rassemble les présences de toutes les promotions pour un affichage global.
    """
    try:
        # 1. On définit toutes les promotions existantes
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        # On lit la table centrale 'presences'

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
    API endpoint qui retourne les présences au format JSON.
    Permet de filtrer par promotion via le paramètre ?promotion=bac1_IAGE.
    Utilisé par le frontend presences.html pour le filtrage par onglets
    sans rechargement complet de la page.
    """
    promo = request.args.get('promotion')

    # Liste de toutes les tables autorisées (sécurité : on n'accepte que les tables connues)
    allowed_tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]

    # Si une promotion spécifique est demandée, on ne lit qu'une table
    if promo:
        if promo not in allowed_tables:
            return jsonify({"error": "Promotion invalide"}), 400
        tables = [promo]
    else:
        # Sinon, on lit toutes les tables de présence
        tables = allowed_tables

    all_presences = []

    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)

        for table in tables:
            presence_table = f"presence_{table}"
            try:
                execute_sql(cursor, f"SELECT * FROM {presence_table} ORDER BY date_inscription DESC")
                rows_raw = cursor.fetchall()
                for row_raw in rows_raw:
                    # On convertit en dictionnaire pour permettre l'assignation (SQLite)
                    row = dict(row_raw) if isinstance(row_raw, sqlite3.Row) else row_raw
                    # Formatage de la date pour l'affichage (Gère MySQL et SQLite)
                    dt = row['date_inscription']
                    if dt:
                        if isinstance(dt, str):
                            try: dt = datetime.strptime(dt.split('.')[0], '%Y-%m-%d %H:%M:%S')
                            except: pass
                        
                        if hasattr(dt, 'strftime'):
                            row['formatted_date'] = dt.strftime('%d/%m/%Y')
                            row['formatted_time'] = dt.strftime('%H:%M:%S')
                            row['date_inscription_sort'] = dt.isoformat()
                        else:
                            row['formatted_date'] = str(dt)
                            row['formatted_time'] = ""
                            row['date_inscription_sort'] = str(dt)
                    else:
                        row['formatted_date'] = "N/A"
                        row['formatted_time'] = "N/A"
                        row['date_inscription_sort'] = ""
                    all_presences.append(row)
            except:
                continue

        cursor.close()
        conn.close()

        # Sort by date descending
        all_presences.sort(key=lambda x: x.get('date_inscription_sort', ''), reverse=True)

        return jsonify(all_presences)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/attendance/check/respond', methods=['POST'])
def respond_to_check():
    """
    Endpoint pour répondre à un contrôle aléatoire (PIN).
    """
    check_id = request.json.get('check_id')
    value = request.json.get('value')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = "SELECT expected_value FROM attendance_checks WHERE id = %s AND status = 'PENDING'"
        execute_sql(cursor, query, (check_id,))
        res = cursor.fetchone()
        
        if not res:
            return jsonify({"status": "error", "message": "Contrôle non trouvé ou déjà expiré"}), 404
        
        expected = res['expected_value'] if not isinstance(res, tuple) else res[0]
        
        status = 'SUCCESS' if value == expected else 'FAILED'
        now = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
        
        update_query = "UPDATE attendance_checks SET received_value = %s, status = %s, responded_at = %s WHERE id = %s"
        execute_sql(cursor, update_query, (value, status, now, check_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({"status": "success", "result": status})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/trigger_check', methods=['POST'])
def trigger_check():
    """
    Simule le déclenchement d'un contrôle aléatoire pour un étudiant.
    (Normalement fait par un worker en arrière-plan).
    """
    matricule = request.json.get('matricule')
    pin = "1234" # Code par défaut pour le test
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # On trouve la dernière tentative acceptée aujourd'hui
        query = "SELECT id FROM attendance_attempts WHERE student_external_id = %s AND result = 'Accepté' ORDER BY timestamp DESC LIMIT 1"
        execute_sql(cursor, query, (matricule,))
        res = cursor.fetchone()
        
        if not res:
            return jsonify({"status": "error", "message": "Aucune présence valide trouvée pour cet étudiant aujourd'hui"}), 404
            
        attempt_id = res['id'] if not isinstance(res, tuple) else res[0]
        
        insert_check = "INSERT INTO attendance_checks (attempt_id, check_type, expected_value, status) VALUES (%s, 'PIN', %s, 'PENDING')"
        execute_sql(cursor, insert_check, (attempt_id, pin))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({"status": "success", "message": "Contrôle déclenché (PIN attendu: 1234)"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/presence_stats')
def api_presence_stats():
    """
    API endpoint qui retourne des statistiques sur les présences.
    Retourne le nombre total, d'entrées et de sorties.
    Filtrable par promotion via ?promotion=bac1_IAGE.
    """
    promo = request.args.get('promotion')

    allowed_tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]

    if promo:
        if promo not in allowed_tables:
            return jsonify({"error": "Promotion invalide"}), 400
        tables = [promo]
    else:
        tables = allowed_tables

    total = 0
    entrees = 0
    sorties = 0

    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)

        for table in tables:
            presence_table = f"presence_{table}"
            try:
                # Compte le total et répartit par type_presence
                execute_sql(cursor, f"SELECT type_presence FROM {presence_table}")
                rows = cursor.fetchall()
                for row in rows:
                    total += 1
                    if row['type_presence'] == 'Entrée':
                        entrees += 1
                    elif row['type_presence'] == 'Sortie':
                        sorties += 1
            except (mysql.connector.Error, sqlite3.Error, Exception):
                continue

        cursor.close()
        conn.close()

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
    Supports filtering by promotion (table name).
    """
    promo = request.args.get('promotion')
    
    if promo:
        # Restriction de sécurité : on ne permet que les tables connues
        allowed_tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        if promo not in allowed_tables:
            return jsonify({"error": "Promotion invalide"}), 400
        tables = [promo]
    else:
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
    
    all_students = []

    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)

        for table in tables:
            try:
                execute_sql(cursor, f"SELECT * FROM {table}")
                rows_raw = cursor.fetchall()
                for row_raw in rows_raw:
                    # On convertit en dictionnaire pour permettre l'assignation (SQLite)
                    row = dict(row_raw) if isinstance(row_raw, sqlite3.Row) else row_raw
                    dt = row['date_inscription']
                    if dt:
                        if isinstance(dt, str):
                            try: dt = datetime.strptime(dt.split('.')[0], '%Y-%m-%d %H:%M:%S')
                            except: pass
                        
                        if hasattr(dt, 'strftime'):
                            row['formatted_date'] = dt.strftime('%d/%m/%Y %H:%M')
                            row['date_inscription_sort'] = dt.isoformat()
                        else:
                            row['formatted_date'] = str(dt)
                            row['date_inscription_sort'] = str(dt)
                    else:
                        row['formatted_date'] = "N/A"
                        row['date_inscription_sort'] = ""
                    all_students.append(row)
            except (mysql.connector.Error, sqlite3.Error, Exception):
                continue

        cursor.close()
        conn.close()

        # Sort by date descending
        all_students.sort(key=lambda x: x['date_inscription_sort'] if 'date_inscription_sort' in x else '', reverse=True)

        return jsonify(all_students)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats')
def api_stats():
    """
    API endpoint that returns student statistics.
    Supports filtering by promotion.
    """
    promo = request.args.get('promotion')
    
    if promo:
        allowed_tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        if promo not in allowed_tables:
            return jsonify({"error": "Promotion invalide"}), 400
        tables = [promo]
    else:
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
    
    male_count = 0
    female_count = 0
    total_count = 0

    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)

        for table in tables:
            try:
                execute_sql(cursor, f"SELECT sexe FROM {table}")
                rows = cursor.fetchall()
                for row in rows:
                    total_count += 1
                    if row['sexe'] == 'M':
                        male_count += 1
                    elif row['sexe'] == 'F':
                        female_count += 1
            except (mysql.connector.Error, sqlite3.Error, Exception):
                continue

        cursor.close()
        conn.close()

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
def admin_dashboard():
    """
    Tableau de bord pour l'administrateur montrant quelques statistiques.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Compte des étudiants en Bac1 IAGE
        execute_sql(cursor, "SELECT COUNT(*) FROM bac1_IAGE")
        bac1_count = cursor.fetchone()[0]
        
        # Compte total des présences (somme de toutes les tables)
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        
        presence_count = 0
        for table in tables:
            try:
                execute_sql(cursor, f"SELECT COUNT(*) FROM presence_{table}")
                presence_count += cursor.fetchone()[0]
            except:
                continue
        
        cursor.close()
        conn.close()
        return render_template('students_list.html', bac1_count=bac1_count, presence_count=presence_count)
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur : {err}"

@app.route('/admin/bac1_iage')
def admin_bac1_iage():
    """
    Affichage détaillé des étudiants inscrits en Bac1 IAGE.
    """
    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        # Récupération du total

        execute_sql(cursor, "SELECT COUNT(*) as total FROM bac1_IAGE")
        count_res = cursor.fetchone()
        count = count_res['total']
        
        # Récupération de la liste complète
        execute_sql(cursor, "SELECT * FROM bac1_IAGE ORDER BY date_inscription DESC")
        rows_raw = cursor.fetchall()
        students = [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows_raw]
        
        # Pré-formatage des données pour le template
        for student in students:
            dt = student['date_inscription']
            if dt:
                if isinstance(dt, str):
                    try: dt = datetime.strptime(dt.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except: pass
                
                if hasattr(dt, 'strftime'):
                    student['formatted_date'] = dt.strftime('%d/%m/%Y %H:%M')
                else:
                    student['formatted_date'] = str(dt)
            else:
                student['formatted_date'] = "N/A"
            
            # Logique de style pour le genre
            if student['sexe'] == 'F':
                student['sexe_bg'] = '#fdf2f8'
                student['sexe_color'] = '#db2777'
            else:
                student['sexe_bg'] = '#eff6ff'
                student['sexe_color'] = '#2563eb'
        
        cursor.close()
        conn.close()
        return render_template('admin_bac1_iage.html', students=students, count=count)
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur : {err}"

@app.route('/admin/attendance')
def admin_attendance():
    """
    Suivi détaillé des présences (Administration).
    """
    tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]
    
    try:
        conn = get_db_connection()
        if isinstance(conn, sqlite3.Connection):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        all_presences = []

        for table in tables:
            try:
                execute_sql(cursor, f"SELECT * FROM presence_{table}")
                rows_raw = cursor.fetchall()
                all_presences.extend([dict(r) if isinstance(r, sqlite3.Row) else r for r in rows_raw])
            except:
                continue
        
        for p in all_presences:
            dt = p['date_inscription']
            if dt:
                if isinstance(dt, str):
                    try: dt = datetime.strptime(dt.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except: pass
                
                if hasattr(dt, 'strftime'):
                    # Formatage complet pour l'admin
                    p['formatted_time'] = dt.strftime('%H:%M:%S')
                    p['formatted_date'] = dt.strftime('%d/%m/%Y')
                else:
                    p['formatted_time'] = "N/A"
                    p['formatted_date'] = str(dt)
                p['initials'] = f"{p['nom'][0]}{p['prenom'][0]}" if p['nom'] and p['prenom'] else "??"
            else:
                p['formatted_time'] = "N/A"
                p['formatted_date'] = "N/A"
                p['initials'] = "??"

        # Tri par date décroissante
        all_presences.sort(key=lambda x: x['date_inscription'] if x['date_inscription'] else '', reverse=True)

        cursor.close()
        conn.close()
        return render_template('admin_attendance.html', presences=all_presences)
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur : {err}"

@app.route('/admin/reset_table', methods=['POST'])
def reset_table():
    """
    Cette route sert à réinitialiser (vider) une table de données.
    """
    table_name = request.form.get('table_name')
    
    # Liste de toutes les tables autorisées pour la réinitialisation
    student_tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]
    
    allowed_tables = student_tables + [f"presence_{t}" for t in student_tables] + ['presence']
    
    if table_name not in allowed_tables:
        return "Table non autorisée ou invalide."
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # On vide la table (Action irréversible)
        if isinstance(conn, sqlite3.Connection):
            execute_sql(cursor, f"DELETE FROM {table_name}")
            execute_sql(cursor, "DELETE FROM sqlite_sequence WHERE name=?", (table_name,))
        else:
            execute_sql(cursor, f"TRUNCATE TABLE {table_name}")
        conn.commit()
        cursor.close()
        conn.close()
        
        # Redirection intelligente
        if table_name.startswith('presence'):
            return redirect(url_for('view_presences'))
        else:
            return redirect(url_for('view_students', promo=table_name))
            
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return f"Erreur lors de la réinitialisation : {err}"

# Lancement du serveur
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)

#deuxième système antifraude avec GPS pour chaque zone deja definit. 
