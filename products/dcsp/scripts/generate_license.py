import hashlib
import json
import os
import datetime

# The secret MUST match license_check.py
SECRET_KEY = "REDACTED_DCSP_KEY"

def generate_license(client_name, hardware_id, expiry_days=365):
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=expiry_days)).strftime("%Y-%m-%d")
    
    payload = f"{client_name}|{hardware_id}|{expiry_date}"
    signature = hashlib.sha256((payload + SECRET_KEY).encode()).hexdigest()
    
    license_data = {
        "client_name": client_name,
        "hardware_id": hardware_id,
        "expiry_date": expiry_date,
        "signature": signature
    }
    
    with open("license.json", "w") as f:
        json.dump(license_data, f, indent=4)
    
    print(f"License generated for {client_name} (HWID: {hardware_id})")
    print(f"File created: license.json")
    print(f"Expiry: {expiry_date}")

if __name__ == "__main__":
    print("DCSP License Generator")
    client = input("Client Name: ")
    hwid = input("Client Hardware ID: ")
    generate_license(client, hwid)
