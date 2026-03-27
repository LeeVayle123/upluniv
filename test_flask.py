from app import app
import json

def test_api():
    with app.test_client() as client:
        print("Testing student lookup for 2024021018...")
        # L'API devrait maintenant fonctionner avec les tables en MAJUSCULES
        response = client.get('/api/student/2024021018')
        print("Status Code:", response.status_code)
        print("Data:", response.get_json())

if __name__ == "__main__":
    test_api()
