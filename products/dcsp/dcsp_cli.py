#!/usr/bin/env python3
"""
DCSP Command Line Interface.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from urllib import request, error

logger = logging.getLogger(__name__)
BASE_URL = os.environ.get("DCSP_URL", "http://localhost:8000")

def get_health():
    """Fetch health status from the API."""
    try:
        with request.urlopen(f"{BASE_URL}/health", timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logger.debug("dcsp_cli: get_health failed: %s", e)
        return None

def cmd_status(args):
    """Print DCSP running status and service health."""
    health = get_health()
    if not health:
        print("DCSP is not running (could not connect to API).")
        return

    print("DCSP is running.")
    print(f"Environment: {health.get('environment', 'unknown')}")
    print(f"Database:    {health.get('database', 'unknown')}")
    print(f"Ollama:      {health.get('ollama', 'unknown')}")
    print(f"Redis:       {health.get('redis', 'unknown')}")

def cmd_metrics(args):
    """Fetch and print job metrics (requires auth handling)."""
    # Note: metrics requires auth, so we expect a 302 redirect to /login
    # if not authenticated. urllib follows redirects by default.
    try:
        # We simulate a request. If it redirects to /login, we detect it.
        req = request.Request(f"{BASE_URL}/api/metrics")
        with request.urlopen(req, timeout=5) as response:
            if response.geturl().endswith("/login"):
                print("Login required to view metrics. Please use the web dashboard.")
                return
            
            data = json.loads(response.read().decode())
            print("DCSP Job Metrics:")
            print(f"Total Jobs:      {data.get('total_jobs', 0)}")
            print(f"Success Rate:    {data.get('success_rate', 0.0) * 100:.1f}%")
            print(f"Avg Confidence:  {data.get('avg_confidence', 0.0):.2f}")
    except error.HTTPError as e:
        if e.code == 302 or e.code == 401:
            print("Login required to view metrics.")
        else:
            print(f"Error fetching metrics: {e}")
    except Exception as e:
        logger.warning("dcsp_cli: cmd_metrics failed: %s", e)
        print(f"Error connecting to API: {e}")

def cmd_seed(args):
    """Run the demo data seeding script."""
    print("Running seed_demo_data.py...")
    try:
        # Run scripts/seed_demo_data.py using the same interpreter
        subprocess.run([sys.executable, "scripts/seed_demo_data.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Seeding failed: {e}")
    except FileNotFoundError:
        print("Error: scripts/seed_demo_data.py not found.")

def cmd_health(args):
    """Exit with code 1 if any core service is unavailable."""
    health = get_health()
    if not health:
        print("DCSP is DOWN (API unreachable)")
        sys.exit(1)
    
    services = ["database", "ollama", "redis"]
    all_ok = True
    for s in services:
        status = health.get(s)
        if status != "connected":
            print(f"Service {s} is {status}")
            all_ok = False
    
    if all_ok:
        print("DCSP Health: OK")
        sys.exit(0)
    else:
        print("DCSP Health: DEGRADED")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="DCSP CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("status", help="Check DCSP status")
    subparsers.add_parser("metrics", help="Show repair metrics")
    subparsers.add_parser("seed", help="Seed demo data")
    subparsers.add_parser("health", help="Health check for scripting (exits with code 1 if any service is down)")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "metrics":
        cmd_metrics(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command == "health":
        cmd_health(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
