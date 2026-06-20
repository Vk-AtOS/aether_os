# Layer 8 registration — integrate into orchestrator/phase_sequence.py
# p20_multiregion: insert AFTER "p19_service_catalog" in PHASE_SEQUENCE
# (or after p15_handoff if Layer 7 not yet integrated)

PHASE_SEQUENCE_ADDITIONS = [
    ("after", "p19_service_catalog", "p20_multiregion"),  # Multi-region + chaos + capacity
]

PHASE_SUPERVISORS_ADDITIONS = {
    "p20_multiregion": "aether_os.phases.p20_multiregion.supervisor_agent.MultiRegionSupervisor",
}
