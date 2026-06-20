# Layer 6 registration — integrate into orchestrator/phase_sequence.py
# p17_control_plane: insert AFTER "p15_handoff" in PHASE_SEQUENCE (current last phase)
# p18_billing_metering: insert AFTER "p17_control_plane" in PHASE_SEQUENCE

# To activate, add the entries below to orchestrator/phase_sequence.py:
#
#   PHASE_SEQUENCE:
#     append "p17_control_plane" after "p15_handoff"  (or after "p16_iam" when that phase ships)
#     append "p18_billing_metering" after "p17_control_plane"
#
#   PHASE_SUPERVISORS (dict entries to add):
#     "p17_control_plane":   "aether_os.phases.p17_control_plane.supervisor_agent.ControlPlaneSupervisor",
#     "p18_billing_metering":"aether_os.phases.p18_billing_metering.supervisor_agent.BillingMeteringSupervisor",

PHASE_SEQUENCE_ADDITIONS = [
    ("after", "p16_iam",            "p17_control_plane"),    # K8s Operator + CRDs
    ("after", "p17_control_plane",  "p18_billing_metering"), # OpenMeter + Stripe billing
]

PHASE_SUPERVISORS_ADDITIONS = {
    "p17_control_plane":    "aether_os.phases.p17_control_plane.supervisor_agent.ControlPlaneSupervisor",
    "p18_billing_metering": "aether_os.phases.p18_billing_metering.supervisor_agent.BillingMeteringSupervisor",
}
