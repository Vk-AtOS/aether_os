"""
p09_documentation.gate — compatibility alias for p10_docs_delivery.gate.

Delegates all logic to p10_docs_delivery so there is a single implementation.
"""
from aether_os.phases.p10_docs_delivery.gate import validate  # noqa: F401
