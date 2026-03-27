import mysql.connector
from db_config import host, user, password, database
import datetime
from datetime import timezone, timedelta

def test_search():
    try:
        conn = mysql.connector.connect(host=host, user=user, password=password, database=database)
        cursor = conn.cursor(dictionary=True)
        matricule = '2024021018'
        tables = [
            'bac1_IAGE', 'bac2_IAGE', 'bac3_IAGE',
            'bac1_tech_IA', 'bac1_tech_GL', 'bac1_tech_SI',
            'bac2_tech_IA', 'bac2_tech_GL', 'bac2_tech_SI',
            'bac3_tech_IA', 'bac3_tech_GL', 'bac3_tech_SI',
            'bac4_tech_IA', 'bac4_tech_GL', 'bac4_tech_SI'
        ]
        
        found = False
        result = None
        for table in tables:
            print(f"Checking table {table}...")
            query = f"SELECT * FROM {table} WHERE matricule = %s"
            cursor.execute(query, (matricule,))
            result = cursor.fetchone()
            if result:
                found = True
                print(f"Found in {table}!")
                break
        
        if found:
            student_dict = result
            query_check = """
                SELECT c.id, c.check_type, c.status 
                FROM attendance_checks c
                JOIN attendance_attempts a ON c.attempt_id = a.id
                WHERE a.student_external_id = %s AND c.status = 'PENDING'
                ORDER BY c.sent_at DESC LIMIT 1
            """
            cursor.execute(query_check, (matricule,))
            check = cursor.fetchone()
            print("Check found:", check)
            
            student_dict['pending_check'] = dict(check) if check else None
            print("Final student_dict:", student_dict)
        else:
            print("Not found in any table.")
            
        conn.close()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_search()
