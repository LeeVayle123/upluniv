import mysql.connector

# Import connection parameters
from db_config import host, user, password, database

def create_database():
    try:
        # Connect without specifying database
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        print(f"Database {database} created or already exists.")
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"Error creating database: {err}")

def create_tables():
    try:
        # Connect to MySQL
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database
        )
        cursor = conn.cursor()

        # definition des colonnes communes pour les tables des étudiants
        student_columns = """
        matricule VARCHAR(50) PRIMARY KEY,
        nom VARCHAR(100),
        postnom VARCHAR(100),
        prenom VARCHAR(100),
        sexe ENUM('M', 'F'),
        parcours VARCHAR(50),
        promotion VARCHAR(50),
        filiere VARCHAR(50),
        faculte VARCHAR(100),
        device_signature VARCHAR(100),
        latitude DOUBLE,
        longitude DOUBLE,
        date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """

        # listes de tables des étudiants à créer
        student_tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]

        for table in student_tables:
            create_table_query = f"CREATE TABLE IF NOT EXISTS {table} ({student_columns})"
            cursor.execute(create_table_query)
            print(f"Table {table} created or already exists.")

        # definition des colonnes pour la table de présence
        # type_presence : indique si c'est une ENTRÉE (arrivée) ou une SORTIE (départ)
        presence_columns = """
        id INT AUTO_INCREMENT PRIMARY KEY,
        matricule VARCHAR(50),
        nom VARCHAR(100),
        postnom VARCHAR(100),
        prenom VARCHAR(100),
        sexe ENUM('M', 'F'),
        parcours VARCHAR(50),
        promotion VARCHAR(50),
        filiere VARCHAR(50),
        faculte VARCHAR(100),
        type_presence ENUM('Entrée', 'Sortie') DEFAULT 'Entrée',
        device_signature VARCHAR(100),
        latitude DOUBLE,
        longitude DOUBLE,
        status_geoloc VARCHAR(50) DEFAULT 'Inconnu',
        date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """
        
        # Création des tables de présence spécifiques pour chaque promotion/filière
        for table in student_tables:
            presence_table_name = f"presence_{table}"
            create_presence_query = f"CREATE TABLE IF NOT EXISTS {presence_table_name} ({presence_columns})"
            cursor.execute(create_presence_query)
            print(f"Table {presence_table_name} created or already exists.")

        # Garder la table presence générale pour la compatibilité ou vue globale si nécessaire
        cursor.execute(f"CREATE TABLE IF NOT EXISTS presence ({presence_columns})")
        print("Table presence created or already exists.")

        conn.commit()
        cursor.close()
        conn.close()
        print("All tables created successfully.")

    except mysql.connector.Error as err:
        print(f"Error: {err}")

if __name__ == "__main__":
    create_database()
    create_tables()