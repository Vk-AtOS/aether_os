#!/bin/bash
set -e

echo "Starting DCSP API entrypoint..."

# Wait for postgres
echo "Waiting for PostgreSQL at $DATABASE_URL..."
ATTEMPTS=0
MAX_ATTEMPTS=30
# Extract host and port from DATABASE_URL
PGHOST=$(echo $DATABASE_URL | sed -e 's/.*@//' -e 's/:.*//')
PGPORT=$(echo $DATABASE_URL | sed -e 's/.*://' -e 's/\/.*//')

until curl -s $PGHOST:$PGPORT > /dev/null 2>&1 || [ $ATTEMPTS -eq $MAX_ATTEMPTS ]; do
  echo "PostgreSQL is unavailable - sleeping (attempt $((ATTEMPTS+1))/$MAX_ATTEMPTS)"
  sleep 2
  ATTEMPTS=$((ATTEMPTS+1))
done

if [ $ATTEMPTS -eq $MAX_ATTEMPTS ]; then
  echo "PostgreSQL did not become available in time. Continuing anyway..."
fi

# Wait for ollama
echo "Waiting for Ollama at $OLLAMA_URL..."
ATTEMPTS=0
until curl -s $OLLAMA_URL/api/tags > /dev/null 2>&1 || [ $ATTEMPTS -eq $MAX_ATTEMPTS ]; do
  echo "Ollama is unavailable - sleeping (attempt $((ATTEMPTS+1))/$MAX_ATTEMPTS)"
  sleep 2
  ATTEMPTS=$((ATTEMPTS+1))
done

if [ $ATTEMPTS -eq $MAX_ATTEMPTS ]; then
  echo "Ollama did not become available in time. Model pull may fail."
else
  # Pull model if not present
  echo "Checking for deepseek-coder:6.7b model..."
  if ! curl -s $OLLAMA_URL/api/tags | grep -q "deepseek-coder:6.7b"; then
    echo "Model not found. Pulling deepseek-coder:6.7b (this may take a few minutes)..."
    curl -X POST $OLLAMA_URL/api/pull -d '{"name": "deepseek-coder:6.7b"}'
  else
    echo "Model deepseek-coder:6.7b is already present."
  fi
fi

echo "Starting uvicorn..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
