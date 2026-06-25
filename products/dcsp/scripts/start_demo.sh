#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== DCSP Demo Startup ==="

# Check if venv exists, if so activate it
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Checking PostgreSQL..."
if brew services list 2>/dev/null | grep postgresql | grep started > /dev/null 2>&1; then
  echo "  ✓ PostgreSQL running"
else
  echo "  Starting PostgreSQL..."
  # Try generic start if specific version check fails
  brew services start postgresql@15 || brew services start postgresql || echo "  ⚠ Could not start PostgreSQL automatically"
  sleep 2
fi

echo "Checking Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "  ✓ Ollama running"
else
  echo "  ⚠ Ollama not running. Start: ollama serve"
fi

echo "Running DB migration..."
python scripts/migrate_db.py

echo "Seeding demo data..."
python scripts/seed_demo_data.py

echo ""
echo "=== Starting DCSP API ==="
echo "Dashboard: http://localhost:8000/dashboard"
echo "Login: admin / dcsp2024"
echo ""
uvicorn src.api.main:app --reload --port 8000
