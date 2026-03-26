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

# --- CONFIGURATION DE L'URL PUBLIQUE (NGROK) ---
# Si vous utilisez Ngrok, modifiez cette variable avec votre lien https://...
# Sinon, laissez vide pour utiliser l'adresse locale.
PUBLIC_URL = os.environ.get('PUBLIC_URL', '') 
if PUBLIC_URL and not PUBLIC_URL.startswith(('http://', 'https://')):
    PUBLIC_URL = f"https://{PUBLIC_URL}"

# --- CONFIGURATION DE LA CONNEXION À LA BASE DE DONNÉES ---
def get_db_connection():
    # Détection de l'environnement : Si on est sur Render, on utilise SQLite
    if os.environ.get('RENDER') or not host:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row  # Pour avoir des résultats sous forme de dictionnaire comme avec MySQL
        return conn
    
    # Sinon on utilise MySQL (XAMPP local)
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
    CETTE FONCTION EST LE COEUR DU SYSTÈME DE PRÉSENCE.
    Elle prend le matricule saisi par l'étudiant, le cherche dans toutes les tables 
    de promotions (Bac1 IAGE, Bac2 IAGE, etc.), et si l'étudiant existe, 
    elle enregistre sa présence avec l'heure exacte et le type (Entrée/Sortie).
    """
    # 1. On récupère le matricule depuis le formulaire HTML (et on le nettoie)
    matricule = request.form['matricule'].strip()
    
    # 2. On récupère aussi le type de pointage : 'Entrée' ou 'Sortie'
    type_presence = request.form.get('type_presence', 'Entrée')
    
    # Récupération de la signature de l'appareil
    device_signature = request.form.get('device_signature', 'Unknown-Device')
    
    # 3. Liste de toutes les tables où un étudiant pourrait être inscrit
    tables = [
        'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
        'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
        'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
        'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
        'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
    ]
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 4. On boucle à travers chaque table de promotion
        found = False
        for table in tables:
            query = f"SELECT nom, postnom, prenom, filiere, promotion, sexe, faculte, parcours FROM {table} WHERE matricule = %s"
            execute_sql(cursor, query, (matricule,))
            result = cursor.fetchone()
            
            if result:
                found = True
                # On extrait ses informations (Tuple unpacking sécurisé)
                nom, postnom, prenom, filiere, promotion, sexe, faculte, parcours = result
                
                # Conversion GPS sécurisée
                try:
                    lat = float(request.form.get('latitude')) if request.form.get('latitude') else None
                    lon = float(request.form.get('longitude')) if request.form.get('longitude') else None
                except:
                    lat, lon = None, None
                
                # 4.5 Gestion du temps (Lubumbashi UTC+2)
                # On calcule l'heure actuelle avec un décalage de +2 heures par rapport à UTC
                now_lubumbashi = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
                today_date = now_lubumbashi.strftime('%Y-%m-%d')
                
                # --- NOUVELLES RESTRICTIONS (Demandées par l'utilisateur) ---
                
                # 1. Protection contre les doublons d'appareils
                # On vérifie si ce matricule a déjà été utilisé aujourd'hui par un autre appareil
                check_device_query = "SELECT device_signature FROM presences WHERE matricule = %s AND date(date_inscription) = %s LIMIT 1"
                execute_sql(cursor, check_device_query, (matricule, today_date))
                device_res = cursor.fetchone()
                
                if device_res:
                    # Pour SQLite (Row object) et MySQL (dict ou tuple)
                    existing_sig = device_res['device_signature'] if isinstance(device_res, (dict, sqlite3.Row)) else device_res[0]
                    if existing_sig != device_signature:
                        cursor.close()
                        conn.close()
                        return jsonify({"status": "error", "message": "Ce matricule est déjà utilisé sur un autre appareil (Used)"}), 403

                # 2. Logique de séquence (Entrée -> Sortie) et Limite 2x par jour
                # On récupère l'historique d'aujourd'hui pour ce matricule
                check_sequence_query = "SELECT type_presence FROM presences WHERE matricule = %s AND date(date_inscription) = %s ORDER BY date_inscription DESC"
                execute_sql(cursor, check_sequence_query, (matricule, today_date))
                history = cursor.fetchall()
                
                # Conversion en liste de types (Compatible MySQL dict et SQLite Row)
                today_types = [row['type_presence'] if isinstance(row, (dict, sqlite3.Row)) else row[0] for row in history]
                last_type = today_types[0] if today_types else None
                count_type = today_types.count(type_presence)

                # Règle A : Limite de 2 scans par type
                if count_type >= 2:
                    cursor.close()
                    conn.close()
                    return jsonify({"status": "error", "message": f"Limite de 2 {type_presence}s atteint pour aujourd'hui"}), 403

                # Règle B : Ordre strict (On ne peut pas faire 2 Entrées de suite, ni 2 Sorties)
                if type_presence == 'Entrée':
                    if last_type == 'Entrée':
                        cursor.close()
                        conn.close()
                        return jsonify({"status": "error", "message": "Vous avez déjà une Entrée active. Signalez votre Sortie d'abord"}), 403
                else: # type_presence == 'Sortie'
                    if last_type != 'Entrée':
                        cursor.close()
                        conn.close()
                        return jsonify({"status": "error", "message": "Aucune Entrée correspondante trouvée. Signalez d'abord votre Entrée"}), 403

                # 5. SYSTÈME ANTI-FRAUDE : Géolocalisation UPL
                UPL_LAT = -11.65238
                UPL_LON = 27.48261
                ALLOWED_RADIUS = 500  # 500 mètres pour plus de tolérance GPS et taille campus
                
                distance = calculate_distance(lat, lon, UPL_LAT, UPL_LON)
                
                if lat is None or lon is None:
                    status_geoloc = "Inconnu (Pas de GPS)"
                elif distance <= ALLOWED_RADIUS:
                    status_geoloc = "Validé"
                else:
                    status_geoloc = "Fraude Hors-Campus"

                # Enregistrement dans la table globale
                insert_query = """
                    INSERT INTO presences 
                    (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, latitude, longitude, status_geoloc, date_inscription) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                execute_sql(cursor, insert_query, (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, lat, lon, status_geoloc, now_lubumbashi))
                
                # On enregistre AUSSI dans la table de présence spécifique pour la promotion
                specific_presence_table = f"presence_{table}"
                execute_sql(cursor, f"""
                    INSERT INTO {specific_presence_table}
                    (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, latitude, longitude, status_geoloc, date_inscription)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (matricule, nom, postnom, prenom, sexe, parcours, promotion, filiere, faculte, type_presence, device_signature, lat, lon, status_geoloc, now_lubumbashi))
                
                conn.commit()
                break
        
        cursor.close()
        conn.close()

        if found:
            return jsonify({"status": "success", "message": "Présence enregistrée"})
        else:
            return jsonify({"status": "error", "message": "Matricule non trouvé dans nos listes"}), 404
        
    except Exception as e:
        if 'conn' in locals() and conn: conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/student/<matricule>')
def get_student_info(matricule):
    """
    Recherche un étudiant par son matricule dans toutes les tables de promotions.
    Retourne les informations au format JSON (Objet avec clés nom, prenom, etc.)
    """
    matricule = matricule.strip()
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
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        
        for table in tables:
            query = f"SELECT * FROM {table} WHERE matricule = %s"
            execute_sql(cursor, query, (matricule,))
            result = cursor.fetchone()
            
            if result:
                # Conversion en dictionnaire
                student_dict = dict(result) if isinstance(conn, sqlite3.Connection) else result
                
                # Récupération du statut actuel des présences d'aujourd'hui
                now_lubumbashi = datetime.now(timezone(timedelta(hours=2))).replace(tzinfo=None)
                today_date = now_lubumbashi.strftime('%Y-%m-%d')
                
                query_status = "SELECT type_presence FROM presences WHERE matricule = %s AND date(date_inscription) = %s ORDER BY date_inscription DESC"
                execute_sql(cursor, query_status, (matricule, today_date))
                history = cursor.fetchall()
                
                today_types = [row['type_presence'] if isinstance(row, (dict, sqlite3.Row)) else row[0] for row in history]
                
                student_dict['last_type'] = today_types[0] if today_types else None
                student_dict['count_today'] = len(today_types)
                
                cursor.close()
                conn.close()
                return jsonify(student_dict)
        
        cursor.close()
        conn.close()
        return jsonify({"error": "Étudiant non trouvé"}), 404
        
    except (mysql.connector.Error, sqlite3.Error, Exception) as err:
        return jsonify({"error": str(err)}), 500

@app.route('/generate_qr')
def generate_qr():
    """
    Génère un QR code pointant vers la page de présence.
    """
    # On utilise l'URL publique si elle est définie, sinon l'URL locale
    if PUBLIC_URL:
        # Nettoyage de l'URL pour éviter les doubles slashes
        base_url = PUBLIC_URL.rstrip('/')
        target_url = f"{base_url}{url_for('attendance')}"
    else:
        target_url = url_for('attendance', _external=True)
    
    print("-" * 50)
    print(f"!!! QR CODE GÉNÉRÉ POUR : {target_url} !!!")
    print("Vérifiez que ce lien commence par https:// et non par http://127.0.0.1")
    print("-" * 50)

    
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
    
    return send_file(img_io, mimetype='image/png', as_attachment=True, download_name='qr_presence_upl.png')


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
    app.run(host='0.0.0.0', port=5000, debug=True)


