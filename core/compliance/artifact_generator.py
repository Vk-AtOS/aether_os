from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class ComplianceArtifact:
    artifact_type: str  # AI_SYSTEM_CARD, DECISION_LOG, etc.
    content: str

class ComplianceArtifactGenerator:
    async def generate_artifact(self, run_id: str, artifact_type: str) -> ComplianceArtifact:
        return ComplianceArtifact(artifact_type, f"Compliance report for {run_id}")

ArtifactGenerator = ComplianceArtifactGenerator  # backwards-compat alias
