"""
SCRIPT DE MIGRATION - Ajout de la colonne type_presence
=========================================================
Ce script se connecte à la base de données et ajoute automatiquement
la colonne 'type_presence' (Entrée/Sortie) à TOUTES les tables
dont le nom commence par 'presence_'.

Si la colonne existe déjà, il l'ignore et passe à la suivante.
"""

import mysql.connector
from db_config import host, user, password, database

def migrate_add_type_presence():
    try:
        # Connexion à la base de données
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database
        )
        cursor = conn.cursor()

        # 1. On récupère la liste de TOUTES les tables qui commencent par 'presence_'
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            AND table_name LIKE 'presence_%%'
        """, (database,))
        
        tables = [row[0] for row in cursor.fetchall()]
        
        if not tables:
            print("Aucune table de présence trouvée dans la base.")
            return

        print(f"{len(tables)} table(s) de présence trouvée(s).\n")

        for table in tables:
            # 2. On vérifie si la colonne 'type_presence' existe déjà dans cette table
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_schema = %s 
                AND table_name = %s 
                AND column_name = 'type_presence'
            """, (database, table))
            
            already_exists = cursor.fetchone()[0]

            if already_exists:
                # La colonne est déjà là, on passe à la suivante
                print(f"[SKIP]    {table} -> colonne 'type_presence' deja presente.")
            else:
                # 3. La colonne n'existe pas → on l'ajoute avec ALTER TABLE
                # DEFAULT 'Entrée' : les anciennes lignes auront automatiquement 'Entrée'
                cursor.execute(f"""
                    ALTER TABLE `{table}` 
                    ADD COLUMN `type_presence` ENUM('Entree', 'Sortie') DEFAULT 'Entree'
                    AFTER `faculte`
                """)
                conn.commit()
                print(f"[AJOUTE] {table} -> colonne 'type_presence' ajoutee avec succes.")


        cursor.close()
        conn.close()
        print("\n[OK] Migration terminee avec succes !")


    except mysql.connector.Error as err:
        print(f"❌ Erreur de base de données : {err}")

if __name__ == "__main__":
    migrate_add_type_presence()
