#!/bin/bash

# Setup Secure Environment for DCSP
# This script generates a secure .env file for production

if [ -f .env ]; then
    echo "Error: .env file already exists. Delete it if you want to regenerate."
    exit 1
fi

echo "Generating secure DCSP environment..."

# Generate random secrets
S_KEY=$(openssl rand -hex 32)
W_SECRET=$(openssl rand -hex 16)
A_PASS=$(openssl rand -hex 12)

cat <<EOF > .env
# AUTO-GENERATED DCSP CONFIGURATION
SECRET_KEY=$S_KEY
WEBHOOK_SECRET=$W_SECRET
ADMIN_PASSWORD=$A_PASS
DATABASE_URL=sqlite:///./dcsp_prod.db
SANDBOX_ENABLED=true
BASE_URL=http://localhost:8000
DEBUG=false
EOF

chmod 600 .env

echo "------------------------------------------------"
echo "✓ Secure .env generated with random secrets."
echo "✓ Admin Password: $A_PASS"
echo "✓ Permissions restricted to owner (600)."
echo "------------------------------------------------"
echo "KEEP THESE SECRETS SAFE. DO NOT COMMIT .ENV."
