
import os
import json
import sys

# Manual .env loader to avoid dependency issues
def load_env_manual(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                os.environ[key] = value

# Ensure we can import from src
sys.path.append(os.getcwd())

# Load .env
load_env_manual()

from src.security.audit import run_security_audit, get_audit_summary

def main():
    print("Running DCSP Security Audit...")
    report = run_security_audit()
    summary = get_audit_summary(report)
    
    print(f"\nAudit Score: {summary['score']}/100")
    print(f"Passed: {summary['passed']}")
    print(f"Failed: {summary['failed']} (Critical: {summary['critical']}, High: {summary['high']})")
    
    print("\nFindings:")
    for f in summary['findings']:
        status = "PASSED" if f['passed'] else f['severity'].upper()
        print(f"- [{status}] {f['title']}: {f['description']}")
        if not f['passed']:
            print(f"  Remediation: {f['remediation']}")

if __name__ == "__main__":
    main()
