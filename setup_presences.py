import mysql.connector
from db_config import host, user, password, database

def setup_presences_table():
    try:
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database
        )
        cursor = conn.cursor()

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
        device_signature VARCHAR(255),
        date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """
        
        cursor.execute(f"CREATE TABLE IF NOT EXISTS presences ({presence_columns})")
        print("Table 'presences' created or already exists.")

        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"Error: {err}")

if __name__ == "__main__":
    setup_presences_table()
