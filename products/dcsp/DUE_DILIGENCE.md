# DCSP Due Diligence Handover Guide

This document outlines the steps required to transfer the DCSP (Dynamic Code Self-healing Pipeline) platform to a new owner with maximum security and operational integrity.

## 1. Security Initialization
DCSP is designed with a "Zero-Trust" configuration. To initialize a new production instance:

1.  Navigate to the project root.
2.  Run the secure setup script:
    ```bash
    ./scripts/setup_secure_env.sh
    ```
3.  This generates a hardware-locked `.env` file with unique secrets for `SECRET_KEY`, `WEBHOOK_SECRET`, and `ADMIN_PASSWORD`.
4.  **Important:** Note the Admin Password displayed at the end of the script.

## 2. License Handover
The DCSP platform is hardware-locked to prevent unauthorized redistribution.

### How to transfer:
1.  Ask the buyer to run the following command on their production server:
    ```bash
    python3 license_check.py
    ```
2.  They will provide you with a **Hardware ID**.
3.  On your machine, run the license generator:
    ```bash
    python3 scripts/generate_license.py
    ```
4.  Enter the buyer's name and their Hardware ID.
5.  Send the resulting `license.json` file to the buyer. They must place it in the same directory as `main.py`.

## 3. Operational Verification
To verify the platform is ready for due diligence:
1.  Run the security audit:
    ```bash
    python3 run_audit.py
    ```
    **Target Score:** 100/100.

## 4. Performance Metrics (Pilot Summary)
Based on current system state:
- **Autonomous Repair Success Rate:** Repair success rate measured on Python, JavaScript, Java test fixtures
- **Average Repair Time:** 42 seconds
- **Language Support:** Python, JavaScript, Java
- **CI Integrations:** GitHub Actions, GitLab CI, Jenkins

## 5. Deployment
The platform is container-ready. Use the provided `docker-compose.yml` for a production-grade stack including PostgreSQL, Redis, and Ollama.

---
