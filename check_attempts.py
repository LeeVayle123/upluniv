import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def check_attempts():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not (url and key):
        print("Credentials missing.")
        return

    supabase: Client = create_client(url, key)
    
    print("Fetching last 5 attempts...")
    res = supabase.table("attendance_attempts").select("*").order("timestamp", desc=True).limit(5).execute()
    
    if res.data:
        for attempt in res.data:
            print(f"Time: {attempt['timestamp']}")
            print(f"Auditorium: {attempt['auditorium_code']}")
            print(f"Student: {attempt['student_external_id']}")
            print(f"Lat/Lon: {attempt['latitude']}, {attempt['longitude']}")
            print(f"Distance calculated by server: {attempt['distance']}m")
            print(f"Result: {attempt['result']} - Reason: {attempt['reason']}")
            print("-" * 30)
    else:
        print("No attempts found.")

if __name__ == "__main__":
    check_attempts()
