FROM python:3.11-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source into a directory named `aether_os` so `import aether_os` resolves
COPY . ./aether_os/

ENV PYTHONPATH=/srv

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "aether_os.gateway.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
