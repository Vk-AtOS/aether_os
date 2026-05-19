"""
AetherOS Compliance Artifact Generator.

Wraps code_scanner + pdf_report for use by the API layer and phase pipeline.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ComplianceArtifact:
    artifact_type: str
    content: str
    pdf_path: Optional[str] = None
    score: Optional[int] = None


class ComplianceArtifactGenerator:

    async def generate_artifact(
        self,
        run_id: str,
        artifact_type: str = "COMPLIANCE_SCAN",
        main_py_path: Optional[str] = None,
        project_name: str = "",
        domain: str = "general",
    ) -> ComplianceArtifact:
        """
        Generate a compliance artifact for the given run.

        If main_py_path is provided the real code scanner runs and a PDF report
        is written next to the source file.  Otherwise returns a lightweight
        placeholder so the API never errors.
        """
        if main_py_path:
            from .code_scanner import scan_file
            from .pdf_report import generate_pdf

            main_py = Path(main_py_path)
            result = scan_file(main_py, project_name=project_name, domain=domain)

            pdf_out = main_py.parent.parent / "compliance_report.pdf"
            try:
                actual_pdf = generate_pdf(result, pdf_out)
            except Exception:
                actual_pdf = None

            return ComplianceArtifact(
                artifact_type=artifact_type,
                content=json.dumps(asdict(result), indent=2, default=str),
                pdf_path=str(actual_pdf) if actual_pdf and actual_pdf.exists() else None,
                score=result.score,
            )

        return ComplianceArtifact(
            artifact_type=artifact_type,
            content=json.dumps({"run_id": run_id, "status": "no_source_provided"}),
            pdf_path=None,
            score=None,
        )


# Backward-compat alias kept from the original stub
ArtifactGenerator = ComplianceArtifactGenerator
