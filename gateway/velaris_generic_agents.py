"""Agents the generic /velaris/agents route and flow tools may reach (KAN-69 VP-4). An ALLOW-list: every HR agent
is served by /hr only (KAN-199), so it is absent here, and a new Velaris agent stays unreachable until it is
listed. tests/test_velaris_contract.py compares this set and HR_ALLOW with the real Velaris METHODS keys."""
from typing import FrozenSet

GENERIC_AGENTS: FrozenSet[str] = frozenset({
    "ADVANCED_SEARCH_ENGINE", "AMPLIFEX", "ARTESIA", "ATTRACTA", "AUDITOR", "AUTONOMOUS_RESEARCH_ENGINE",
    "AUTONOMOUS_SALES_NAVIGATOR", "COHORTUS", "CONFLUENCE", "CONTROL_LAYER", "CONVERTA", "CREATIVA",
    "CREATIVE_HOLODECK", "DOCUMENT_LIBRARY", "DOMAIN_ADVISOR", "FABRICA", "FISCALIS", "FLUXOR", "GENEFLOW",
    "IMAGINA", "INSIGHTA", "ITSM_ENGINE", "JIRA", "LOGISTA", "LONGTERM_MEMORY", "MODEL_COUNCIL", "OPERATUS",
    "OPTIMA", "ORACLE", "POLARIS", "PRAETOR", "PROBABILIS", "REALMEX", "RETENTA", "SAFETY_PERIMETER",
    "SIMULON", "STOCHASTIX", "TACTICIAN", "TARGETA", "TREASURIX",
})
