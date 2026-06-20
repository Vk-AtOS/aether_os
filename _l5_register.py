# Layer 5 registration — to be integrated into orchestrator/phase_sequence.py
# Insert p05e_serverless AFTER "p05d_cli" in PHASE_SEQUENCE
# Insert p16_iam AFTER "p15_handoff" in PHASE_SEQUENCE

PHASE_SEQUENCE_ADDITIONS = [
    ("after", "p05d_cli",    "p05e_serverless"),  # Knative functions — skips for non-serverless
    ("after", "p15_handoff", "p16_iam"),           # OPA + Keycloak — always generated
]

PHASE_SUPERVISORS_ADDITIONS = {
    "p05e_serverless": "aether_os.phases.p05e_serverless.supervisor_agent.ServerlessSupervisor",
    "p16_iam":         "aether_os.phases.p16_iam.supervisor_agent.IAMSupervisor",
}
