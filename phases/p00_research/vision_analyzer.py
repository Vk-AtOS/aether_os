"""
Vision Analysis Service for P00 Domain Research.
Uses Claude/Bedrock vision capabilities to extract design patterns from screenshots.
"""
import json
import logging
from typing import Dict, Any
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

VISION_PROMPT = """
You are analyzing a {domain} web application for design pattern extraction.
Look at this screenshot and extract:
1. Navigation structure (what links appear, where they are positioned)
2. Page section layout (what sections exist, in what order)
3. Card/grid patterns (how items are displayed)
4. Color usage (primary, background, accent — describe as color families, not hex codes)
5. Typography style (heading weight, body density)
6. Key UI components (search bars, filters, badges, status indicators)
7. What customer actions this interface supports

Do NOT reproduce specific copy, brand names, or exact layouts.
Extract the PATTERNS, not the content.
Return as structured JSON.
"""

async def analyze_screenshot(domain: str, image_data: bytes) -> Dict[str, Any]:
    """Analyzes a screenshot using Claude vision via Bedrock."""
    llm = get_llm_client()
    
    prompt = VISION_PROMPT.format(domain=domain)
    
    try:
        response = await llm.call_vision(prompt, image_data, task_type="analysis")
        # Ensure it parses as JSON
        from aether_os.core.llm.client import safe_parse_json
        return safe_parse_json(response)
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        return {"error": str(e)}
