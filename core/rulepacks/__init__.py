"""Rule packs for generated projects: design, security and prod-readiness (KAN-243).

Each pack has two halves: compact prompt rules given to the model before it writes code, and deterministic
checks run on what it wrote. See docs/RULEPACKS.md for every rule id and NOTICE.md for sources.

    from aether_os.core.rulepacks import generate_tokens, design_prompt_rules, security_prompt_rules
    from aether_os.core.rulepacks import scan_project, repair_prompt
"""
from aether_os.core.rulepacks.design_rules import design_prompt_rules
from aether_os.core.rulepacks.design_tokens import DesignTokens, generate_tokens
from aether_os.core.rulepacks.report import Report, repair_prompt, scan_project
from aether_os.core.rulepacks.security_rules import detect_features, security_prompt_rules

__all__ = ["DesignTokens", "Report", "design_prompt_rules", "detect_features", "generate_tokens", "repair_prompt",
           "scan_project", "security_prompt_rules"]
