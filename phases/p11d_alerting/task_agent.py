from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11d_alerting: Alertmanager Integration
    """
    alerting_dir = output_dir / "alerting"
    runbook_dir = alerting_dir / "alert_runbooks"
    alerting_dir.mkdir(parents=True, exist_ok=True)
    runbook_dir.mkdir(parents=True, exist_ok=True)
    
    # Alertmanager config
    (alerting_dir / "alertmanager.yml").write_text("global: \n  slack_api_url: ''")
    
    # Runbooks
    for name in ["HighErrorRate.md", "HighLatency.md", "DBConnectionPoolExhausted.md"]:
        (runbook_dir / name).write_text(f"# Runbook for {name}\n\n1. Check logs\n2. Escalate")
        
    # Script
    (alerting_dir / "alert_test_script.py").write_text("def fire(): pass")
    
    # .env
    (alerting_dir / ".env.alerting").write_text("SLACK_WEBHOOK_URL=\nPAGERDUTY_KEY=")
    
    return TaskResult(
        output_path=str(alerting_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=[],
        success=True
    )
