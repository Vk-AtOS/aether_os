import os
import hashlib
from src.api.auth import verify_credentials

# Set hash for 'password'
os.environ["ADMIN_PASSWORD_HASH"] = hashlib.sha256("password".encode()).hexdigest()

print(f"Verified 'admin'/'password': {verify_credentials('admin', 'password')}")
print(f"Verified 'admin'/'wrong': {verify_credentials('admin', 'wrong')}")
