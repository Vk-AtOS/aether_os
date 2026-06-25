import requests

API_TOKEN = "hardcoded_secret_123"

def call_api(endpoint):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 401:
        raise Exception("Unauthorized")
    return response.json()
