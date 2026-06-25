from license_check import verify_license; verify_license()
from src.api.main import app
import uvicorn
import os

if __name__ == "__main__":
    host = os.environ.get("DCSP_HOST", "127.0.0.1")
    port = int(os.environ.get("DCSP_PORT", "8001"))
    print(f"Starting DCSP API on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
