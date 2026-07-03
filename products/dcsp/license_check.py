import hashlib
import logging
import uuid
import socket
import json
import os
import datetime
import sys

logger = logging.getLogger(__name__)

# Simple secret for offline signature verification
SECRET_KEY = "vkatos_enterprise_secret_2026"

def get_hardware_id():
    try:
        # Get MAC address and hostname
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0,8*6,8)][::-1])
        hostname = socket.gethostname()
        return hashlib.sha256((mac + hostname).encode()).hexdigest()
    except Exception as e:
        logger.warning("license_check: get_hardware_id failed: %s", e)
        return "unknown_hwid"

def verify_license():
    # Allow VPS deployments to bypass hardware-locked license check via env var.
    # Set DCSP_LICENSE_BYPASS=1 in the container/service environment.
    if os.environ.get("DCSP_LICENSE_BYPASS", "0") == "1":
        return True

    # Look for license.json in the same directory as the executable
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    license_path = os.path.join(application_path, "license.json")
    
    if not os.path.exists(license_path):
        print("License missing. Contact velan317@gmail.com")
        sys.exit(1)
    
    try:
        with open(license_path, 'r') as f:
            data = json.load(f)
        
        # 1. Verify Hardware ID
        if data.get('hardware_id') != get_hardware_id():
            print("License invalid (Hardware ID mismatch). Contact velan317@gmail.com")
            sys.exit(1)
        
        # 2. Verify Expiry
        expiry = datetime.datetime.strptime(data.get('expiry_date'), "%Y-%m-%d")
        if datetime.datetime.now() > expiry:
            print("License expired. Contact velan317@gmail.com")
            sys.exit(1)
            
        # 3. Verify Signature
        payload = f"{data['client_name']}|{data['hardware_id']}|{data['expiry_date']}"
        expected_sig = hashlib.sha256((payload + SECRET_KEY).encode()).hexdigest()
        
        if data.get('signature') != expected_sig:
            print("License invalid (Signature mismatch). Contact velan317@gmail.com")
            sys.exit(1)
            
        return True
    except Exception as e:
        logger.warning("License verification error: %s", e)
        print("License invalid. Contact velan317@gmail.com")
        sys.exit(1)

if __name__ == "__main__":
    # If run directly, print the local Hardware ID for the client
    print(f"Hardware ID for this machine: {get_hardware_id()}")
