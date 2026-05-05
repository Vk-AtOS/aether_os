from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class ScanResult:
    passed: bool
    critical_count: int
    high_count: int
    medium_count: int
    findings: List[Dict[str, Any]]
    scan_duration_seconds: float
