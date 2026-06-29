"""
Script de correction des dimensions de l'auditoire IF-102 dans Supabase.
Exécuter une seule fois : python fix_if102.py
"""
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL ou SUPABASE_KEY manquant dans le .env")
    exit(1)

from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Afficher les valeurs actuelles
res = sb.table("auditoriums").select("*").eq("code", "IF-102").execute()
if res.data:
    print(f"Valeurs actuelles IF-102 : {res.data[0]}")
else:
    print("❌ IF-102 introuvable dans Supabase")
    exit(1)

# Mettre à jour : radius 15m, tolerance 10m
update = sb.table("auditoriums").update({
    "radius_m": 15,
    "tolerance_m": 10
}).eq("code", "IF-102").execute()

print(f"✅ IF-102 mis à jour : radius_m=15, tolerance_m=10")
print(f"Résultat : {update.data}")
