"""
Script to create product-specific DCSP configurations.
"""

import os
import yaml
import uuid
import argparse

def create_config(product_name, domain):
    config = {
        "product": product_name,
        "domain": domain,
        "tenant_id": str(uuid.uuid4()),
        "pipeline_stages": {
            "resume_received": {"expected_seconds": 86400, "criticality": "high"},
            "ai_parsed": {"expected_seconds": 14400, "criticality": "critical"},
            "interview_scheduled": {"expected_seconds": 172800, "criticality": "medium"},
            "interviewed": {"expected_seconds": 86400, "criticality": "high"},
            "selected": {"expected_seconds": 43200, "criticality": "high"},
            "offer_sent": {"expected_seconds": 86400, "criticality": "critical"},
            "joined": {"expected_seconds": 259200, "criticality": "medium"}
        },
        "alerts": {
            "slack_webhook": None,
            "email": None,
            "escalation_after_seconds": 3600
        },
        "self_healing": {
            "on_warning": "log_and_notify",
            "on_critical": "notify_and_escalate",
            "on_emergency": "pause_and_require_human"
        }
    }
    
    os.makedirs("config/products", exist_ok=True)
    file_path = f"config/products/{product_name}.yaml"
    with open(file_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    
    print(f"Created configuration for {product_name} at {file_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    
    create_config(args.product, args.domain)
