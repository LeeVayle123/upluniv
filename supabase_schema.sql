-- SCHEMA POUR SUPABASE (POSTGRESQL)
-- A copier et coller dans l'éditeur SQL de votre tableau de bord Supabase

-- 1. Table des Étudiants (Unifiée)
CREATE TABLE IF NOT EXISTS students (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    matricule TEXT UNIQUE NOT NULL,
    nom TEXT NOT NULL,
    postnom TEXT,
    prenom TEXT,
    sexe TEXT CHECK (sexe IN ('M', 'F')),
    parcours TEXT, -- IAGE, TECHNOLOGIE
    promotion TEXT, -- Bac1, Bac2, etc.
    filiere TEXT, -- IA, GL, SI
    faculte TEXT,
    device_signature TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    date_inscription TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Table des Présences (Unifiée)
CREATE TABLE IF NOT EXISTS presences (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    matricule TEXT REFERENCES students(matricule) ON DELETE CASCADE,
    nom TEXT,
    postnom TEXT,
    prenom TEXT,
    sexe TEXT,
    parcours TEXT,
    promotion TEXT,
    filiere TEXT,
    faculte TEXT,
    type_presence TEXT CHECK (type_presence IN ('Entrée', 'Sortie')),
    device_signature TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    status_geoloc TEXT DEFAULT 'Inconnu',
    date_inscription TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Table des Auditoriums
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

-- 4. Table des Tentatives de Présence (Historique immuable)
CREATE TABLE IF NOT EXISTS attendance_attempts (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    student_external_id TEXT,
    auditorium_code TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    accuracy_meters DOUBLE PRECISION,
    timestamp TIMESTAMP WITH TIME ZONE,
    device_id TEXT,
    ip TEXT,
    device_info TEXT,
    distance DOUBLE PRECISION,
    result TEXT,
    reason TEXT,
    auditorium_version INTEGER
);

-- 5. Table des Contrôles Aléatoires
CREATE TABLE IF NOT EXISTS random_checks (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    matricule TEXT,
    auditorium_code TEXT,
    type TEXT,
    scheduled_time TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 6. Table des Réponses aux Contrôles
CREATE TABLE IF NOT EXISTS random_check_responses (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    check_id BIGINT REFERENCES random_checks(id),
    matricule TEXT,
    auditorium_code TEXT,
    auditorium_version_id INTEGER,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    accuracy_meters DOUBLE PRECISION,
    distance DOUBLE PRECISION,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    device_id TEXT,
    ip TEXT,
    device_info TEXT,
    result TEXT,
    reason TEXT
);

-- 7. Table des Contrôles de Présences (PIN/Vérification)
CREATE TABLE IF NOT EXISTS attendance_checks (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    attempt_id BIGINT REFERENCES attendance_attempts(id) ON DELETE CASCADE,
    check_type TEXT NOT NULL, -- ex: 'PIN'
    expected_value TEXT,
    received_value TEXT,
    status TEXT DEFAULT 'PENDING', -- PENDING, SUCCESS, FAILED
    responded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insertion des données de base pour les auditoires
INSERT INTO auditoriums (code, nom, latitude, longitude, radius_m, floor, tolerance_m, version)
VALUES 
    ('EC-101', 'Eco-A', -11.667, 27.483, 30, 1, 10, 1),
    ('D-101', 'Droit-1', -11.668, 27.484, 25, 0, 10, 1),
    ('B-101', 'Biblio', -11.669, 27.485, 40, 0, 15, 1),
    ('IF-301', 'Info-301', -11.670, 27.486, 30, 3, 10, 1),
    ('IF-101', 'Info-101', -11.671, 27.487, 30, 1, 10, 1),
    ('IF-302', 'Info-302', -11.672, 27.488, 30, 3, 10, 1),
    ('IF-102', 'Info-102', -11.673, 27.489, 20, 1, 40, 1),
    ('IF-304', 'Info-304', -11.674, 27.490, 30, 3, 10, 1)
ON CONFLICT (code) DO NOTHING;
