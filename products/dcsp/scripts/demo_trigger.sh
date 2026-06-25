#!/bin/bash
BASE_URL="${DCSP_URL:-http://localhost:8000}"
echo "Triggering DCSP demo repair..."
curl -s -X POST "$BASE_URL/webhook/ci" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_name": "acme/billing-service",
    "branch": "main",
    "ci_job_name": "pytest",
    "log_content": "Traceback (most recent call last):\n  File \"/app/billing/processor.py\", line 47, in charge_customer\n    result = payment_gateway.charge(amount, card_token)\n  File \"/app/billing/gateway.py\", line 23, in charge\n    raise ConnectionError(\"Payment gateway timeout after 30s\")\nConnectionError: Payment gateway timeout after 30s\n\nDuring handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File \"/app/billing/processor.py\", line 52, in charge_customer\n    raise BillingError(f\"Failed to charge customer {customer_id}\")\nBillingError: Failed to charge customer cust_12345"
  }' | python3 -m json.tool || echo "Server may not be running"
echo ""
echo "Check dashboard at $BASE_URL/dashboard"
