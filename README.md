# UPL Attendance - Système de Suivi de Présence Universitaire

Ce projet est une application web de suivi de présence géolocalisée pour l'université UPL, développée avec **Flask** (Python) et intégrée à **Supabase** pour la gestion de base de données cloud (avec un fallback local SQLite/MySQL).

Le système valide la présence des étudiants dans un auditoire donné en comparant leurs coordonnées GPS (télémétrie mobile) à celles de l'auditoire ciblé.

---

## 📂 Structure du Projet

Le projet respecte désormais la structure standard recommandée pour les applications Flask :

```text
upluniv/
│
├── app.py                     # Script principal de l'application Flask (routes et logique métier)
├── database.db                # Base de données SQLite locale (générée automatiquement)
├── requirements.txt           # Liste des dépendances Python à installer
├── Procfile                   # Configuration du processus pour les déploiements cloud (ex: Render)
├── runtime.txt                # Version du runtime Python spécifiée pour le cloud
│
├── templates/                 # Fichiers HTML rendus par Flask (interface utilisateur)
│   ├── add_student.html       # Formulaire d'ajout d'étudiant
│   ├── admin_attendance.html  # Gestion des présences côté administrateur
│   ├── admin_bac1_iage.html   # Tableau de bord spécifique promo Bac 1 IAGE
│   ├── admin_dashboard.html   # Tableau de bord d'administration des présences
│   ├── admin_login.html       # Page de connexion de l'administrateur
│   ├── admin_timeline.html    # Chronologie d'activité/présences
│   ├── attendance.html        # Page principale de pointage de présence (GPS mobile)
│   ├── general_dashboard.html # Tableau de bord statistique global
│   ├── presences.html         # Page de consultation/export des présences
│   ├── qr_poster.html         # Affiche les QR codes d'accès rapide des auditoires
│   ├── register.html          # Page d'enregistrement des étudiants
│   └── students_list.html     # Liste de tous les étudiants enregistrés
│
├── static/                    # Fichiers de ressources statiques (images, manifestes)
│   ├── logo_upl.png           # Logo officiel de l'université au format PNG (utilisé dans les en-têtes)
│   ├── logo_upl.jpg           # Logo de l'université au format JPG
│   ├── Wh.jpeg                # Image/Illustration statique du projet
│   ├── hh.jpeg                # Image/Illustration statique du projet
│   └── manifest.json          # Manifeste de l'application Web Progressive (PWA) pour installation mobile
│
├── migrations/                # Scripts de migration des données et schéma SQL
├── scripts/                   # Scripts utilitaires et de configuration de base de données
├── tests/                     # Tests unitaires de l'application
```

---

## 🛠️ Installation et Démarrage

### 1. Prérequis
- **Python 3.11** ou supérieur installé sur votre système.

### 2. Configuration initiale
1. Créez un environnement virtuel Python pour isoler les dépendances :
   ```bash
   python -m venv .venv
   ```
2. Activez l'environnement virtuel :
   - Sur Windows :
     ```bash
     .venv\Scripts\activate
     ```
   - Sur macOS/Linux :
     ```bash
     source .venv/bin/activate
     ```
3. Installez les packages requis :
   ```bash
   pip install -r requirements.txt
   ```

### 3. Fichier d'environnement `.env`
1. Copiez le fichier d'exemple fourni pour créer votre propre configuration locale :
   ```bash
   copy .env.example .env
   ```
2. Ouvrez `.env` et complétez les informations requises (notamment vos identifiants de projet **Supabase** et votre URL **Ngrok** si vous en utilisez une).

### 4. Initialisation de la Base de Données locale
Si vous utilisez SQLite en mode local, initialisez la base de données avec la commande :
```bash
python scripts/setup_db.py
```

### 5. Démarrage du serveur de développement
Lancez l'application Flask :
```bash
python app.py
```
Par défaut, le serveur démarrera sur [http://127.0.0.1:5000](http://127.0.0.1:5000).

---

## 🔒 Sécurité et Administration

L'accès à l'interface d'administration `/admin/login` est protégé par les identifiants configurés dans `app.py`. Par défaut :
- **Username** : `Lee-vayle`
- **Password** : `Lee123#`

*(Pensez à sécuriser ces identifiants pour des déploiements réels en les plaçant dans des variables d'environnement).*
