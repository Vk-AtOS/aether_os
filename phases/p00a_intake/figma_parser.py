"""
G7: Figma file export parser for P00a multimodal intake.

Converts a Figma REST API /files/{key} export JSON into a structured
requirements dict that P00 can use directly.

Public API:
    parse_figma(figma_json: dict) -> dict
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _collect_text_nodes(node: dict, depth: int = 0) -> List[str]:
    """Recursively collect TEXT node characters from a Figma node tree."""
    texts: List[str] = []
    if node.get("type") == "TEXT":
        chars = node.get("characters", "").strip()
        if chars:
            texts.append(chars)
    for child in node.get("children", []):
        texts.extend(_collect_text_nodes(child, depth + 1))
    return texts


def _classify_entity_candidates(component_names: List[str]) -> List[str]:
    """
    Heuristic: frame/component names that look like entity names.
    Filters out generic UI names like 'Group', 'Frame', 'Button'.
    """
    generic_terms = {
        "group", "frame", "container", "wrapper", "section",
        "header", "footer", "sidebar", "modal", "overlay",
        "button", "input", "icon", "text", "label", "image",
        "divider", "spacer", "page", "screen",
    }
    candidates: List[str] = []
    for name in component_names:
        normalized = name.strip().lower()
        if normalized not in generic_terms and len(normalized) > 2:
            # CamelCase splitting: "UserProfile" → entity candidate
            candidates.append(name)
    return list(dict.fromkeys(candidates))  # deduplicate preserving order


def parse_figma(figma_json: dict) -> dict:
    """
    Parse a Figma file export JSON into a structured requirements dict.

    Extracts:
    - entities: component/frame names that map to domain objects
    - screens: list of top-level Canvas pages with their frames
    - navigation: detected interaction links between frames
    - inferred_domain: heuristic domain guess from text content
    - raw_spec: plain-English requirements derived from the structure

    Returns a dict with keys:
        entities, screens, navigation, inferred_domain, raw_spec

    Never raises — logs warnings and returns best-effort output.
    """
    try:
        document = figma_json.get("document", {})
        project_name = figma_json.get("name", "Unknown Project")
        pages = [c for c in document.get("children", []) if c.get("type") == "CANVAS"]

        screens: List[Dict[str, Any]] = []
        all_component_names: List[str] = []
        all_text_content: List[str] = []
        navigation_links: List[Dict[str, str]] = []

        for page in pages:
            page_name = page.get("name", "Page")
            frames = [c for c in page.get("children", []) if c.get("type") in ("FRAME", "COMPONENT_SET")]

            frame_info: List[Dict[str, Any]] = []
            for frame in frames:
                frame_name = frame.get("name", "")
                all_component_names.append(frame_name)

                # Collect text content from this frame
                texts = _collect_text_nodes(frame)
                all_text_content.extend(texts)

                # Collect form fields: look for INPUT_TEXT / input-like components
                form_fields = [
                    child.get("name", "")
                    for child in frame.get("children", [])
                    if "input" in child.get("name", "").lower()
                    or "field" in child.get("name", "").lower()
                    or child.get("type") == "TEXT"
                ]

                # Prototype interactions
                for child in frame.get("children", []):
                    for interaction in child.get("interactions", []):
                        action = interaction.get("action", {})
                        dest_id = action.get("destinationId", "")
                        if dest_id:
                            navigation_links.append({
                                "from": frame_name,
                                "to": dest_id,
                                "trigger": interaction.get("trigger", {}).get("type", "click"),
                            })

                frame_info.append({
                    "name": frame_name,
                    "form_fields": form_fields[:10],
                    "text_snippets": texts[:5],
                })

            screens.append({"page": page_name, "frames": frame_info})

        # Infer domain from text content
        text_blob = " ".join(all_text_content).lower()
        inferred_domain = "general"
        domain_keywords = {
            "healthcare": ["patient", "prescription", "diagnosis", "clinic", "doctor", "ehr"],
            "fintech": ["payment", "transaction", "invoice", "bank", "wallet", "transfer"],
            "ecommerce": ["cart", "product", "order", "checkout", "shipping", "inventory"],
            "hrm": ["employee", "payroll", "leave", "attendance", "department", "salary"],
            "education": ["course", "student", "assignment", "grade", "curriculum", "teacher"],
            "real_estate": ["property", "listing", "rent", "mortgage", "tenant", "lease"],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in text_blob for kw in keywords):
                inferred_domain = domain
                break

        entity_candidates = _classify_entity_candidates(all_component_names)

        # Build plain-English spec
        screen_names = [s["page"] for s in screens]
        spec_parts = [
            f"Application '{project_name}' with {len(screens)} screens: {', '.join(screen_names)}.",
        ]
        if entity_candidates:
            spec_parts.append(f"Key entities/components: {', '.join(entity_candidates[:10])}.")
        if navigation_links:
            nav_summary = "; ".join(
                f"{l['from']} → {l['to']} ({l['trigger']})"
                for l in navigation_links[:6]
            )
            spec_parts.append(f"Navigation flows: {nav_summary}.")

        return {
            "entities": entity_candidates[:20],
            "screens": screens,
            "navigation": navigation_links,
            "inferred_domain": inferred_domain,
            "raw_spec": " ".join(spec_parts),
        }

    except Exception as exc:
        logger.warning("[p00a_intake] parse_figma failed: %s", exc)
        return {
            "entities": [],
            "screens": [],
            "navigation": [],
            "inferred_domain": "general",
            "raw_spec": "Figma import failed — please provide requirements as text.",
        }
