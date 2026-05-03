"""P00 Task Agent — parse raw input into structured IntakeRecord."""
from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import LLMClient

logger = logging.getLogger(__name__)

INTAKE_SCHEMA = {
    "source": "manual",
    "raw_text": "",
    "structured_requirements": "",
    "client_id": "",
    "timestamp": "",
    "word_count": 0,
    "domain": "general"
}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    client = LLMClient()
    
    # Standardize input field name
    raw_input = phase_input.input_data.get("raw_input", phase_input.input_data.get("raw_text", ""))
    client_id = phase_input.client_id
    
    # Ensure domain is classified
    prompt = (
        f"Extract and clean this software requirement: {raw_input}\n\n"
        "Classify the application domain into one of these: "
        "general, industrial, fintech, healthcare, saas_multitenant, ecommerce, logistics, education."
    )
    
    result = await client.call_structured(
        prompt=prompt,
        schema_example={
            **INTAKE_SCHEMA,
            "raw_text": raw_input,
            "client_id": client_id,
            "word_count": len(raw_input.split()),
            "timestamp": datetime.utcnow().isoformat()
        },
        task_type="documentation"
    )
    
    # Update pipeline input data so subsequent phases see the detected domain
    if result.get("domain"):
        phase_input.input_data["domain"] = result["domain"]
    
    # Always write output to disk
    # The supervisor passes output_dir, but the prompt asked for a specific path construction
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "intake.json"
    
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    
    return TaskResult(
        output_path=str(output_file),
        confidence=0.9,
        success=True,
        metadata={"intake_record": result}
    )
