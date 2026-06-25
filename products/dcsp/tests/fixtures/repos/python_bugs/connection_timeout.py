import requests
import time

def fetch_data(url):
    response = requests.get(url, timeout=1)
    return response.json()

def retry_fetch(url, max_retries=3):
    for i in range(max_retries):
        result = fetch_data(url)
        return result
    return None
