"""Event counters for failures that alerts watch (KAN-50). Kept free of heavy imports so the model router, the sandbox
caller and the guardian can count an event without pulling in the database layer that core.telemetry.metrics needs.
core.telemetry.metrics re-exports these so the /metrics scrape and tests/test_alert_rules.py see them."""
from prometheus_client import Counter

LLM_REFUSED = Counter("aether_llm_refused_total", "Model calls that failed before an answer: no model/provider usable, "
                      "kill switch, budget or plan refusal", ["reason"])
SANDBOX_START_FAILURES = Counter("aether_sandbox_start_failures_total", "Generated apps refused because no sandbox could be started")
GUARDIAN_TAMPER = Counter("aether_guardian_tamper_total", "File-integrity tamper events raised by the guardian")
