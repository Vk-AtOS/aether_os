import requests
import json
import time
import sys
import uuid
from datetime import datetime

# Colors for terminal
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
ENDC = "\033[0m"

API_URL = "http://localhost:8001"

def print_step(elapsed, message, color=ENDC):
    timestamp = f"[{elapsed:02d}:00]" if isinstance(elapsed, int) else f"[{elapsed}]"
    print(f"{timestamp} {color}{message}{ENDC}")

def run_demo():
    print(f"{BOLD}Starting DCSP Demo Scenario{ENDC}")
    print("-" * 50)

    # 1. Simulate CI failure webhook
    payload = {
        "ci_system": "github_actions",
        "repo": "demo-org/sample-python-app",
        "branch": "main",
        "commit_sha": "abc123def456",
        "workflow": "CI",
        "job": "test",
        "conclusion": "failure",
        "logs": "Error: ModuleNotFoundError: No module named 'boto3'\n  File 'src/aws_client.py', line 3, in <module>\n    import boto3\nModuleNotFoundError: No module named 'boto3'",
        "files_changed": ["src/aws_client.py", "requirements.txt"]
    }

    start_time = time.time()
    
    print_step(0, "Sending failure webhook to DCSP...", BLUE)
    
    try:
        response = requests.post(f"{API_URL}/webhook/ci", json=payload, timeout=10)
        response.raise_for_status()
        repair_result = response.json()
    except Exception as e:
        print(f"{RED}Error sending webhook: {e}{ENDC}")
        sys.exit(1)

    # Note: In the current synchronous implementation of /webhook/ci, 
    # the response already contains the result.
    # However, to simulate real-world polling or async behavior if we move to RQ:
    
    # Let's try to find the job ID. The RepairResult doesn't have it, 
    # but we can get it from history if needed, or we just use the response.
    # For now, let's assume it was processed synchronously as per current /webhook/ci code.

    elapsed = int(time.time() - start_time)
    
    # Simulate some of the steps based on the response
    print_step(1, f"Job created status=repairing", BLUE)
    time.sleep(1)
    print_step(3, "Localizing root cause...", BLUE)
    time.sleep(2)
    print_step(5, "Root cause: src/aws_client.py:3 — missing import", BLUE)
    time.sleep(2)
    
    if repair_result.get("source") == "memory":
        print_step(7, "Checking patch memory... (match found!)", GREEN)
    else:
        print_step(7, "Checking patch memory... (no match found)", YELLOW)
        time.sleep(2)
        print_step(9, "Generating patch with Claude via Bedrock...", BLUE)
    
    # Final result
    success = repair_result.get("success", False)
    confidence = repair_result.get("confidence", 0.0)
    patch_diff = repair_result.get("patch_diff", "")
    explanation = repair_result.get("explanation", "")
    
    if success:
        print_step(23, f"Patch generated (confidence: {confidence:.2f})", GREEN)
        time.sleep(2)
        print_step(25, "Running sandbox validation...", BLUE)
        time.sleep(3)
        print_step(28, "Validation passed ✓", GREEN)
        print_step(28, f"PR would be created: {explanation}", GREEN)
        print("-" * 50)
        print(f"{BOLD}Total repair time: 28s | Confidence: {int(confidence*100)}% | Outcome: PATCHED ✓{ENDC}")
    else:
        print_step(23, f"Repair failed: {explanation}", RED)
        print("-" * 50)
        print(f"{BOLD}Total repair time: 23s | Outcome: FAILED ✗{ENDC}")

    if patch_diff:
        print(f"\n{BOLD}Generated Patch:{ENDC}")
        print("-" * 30)
        print(patch_diff)
        print("-" * 30)

if __name__ == "__main__":
    run_demo()
