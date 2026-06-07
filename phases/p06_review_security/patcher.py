"""
AST-based security patcher for AetherOS.
Provides structured, semantically-safe code modification.
"""
import ast
import astor
import logging

logger = logging.getLogger(__name__)

class ASTSecurityPatcher(ast.NodeTransformer):
    """AST transformer to apply security patches."""
    
    def __init__(self):
        self.patches_applied = []
        
    def visit_Call(self, node: ast.Call):
        # Patch CORS wildcard
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'CORSMiddleware':
            for keyword in node.keywords:
                if keyword.arg == 'allow_origins':
                    if isinstance(keyword.value, ast.List):
                        for elt in keyword.value.elts:
                            if isinstance(elt, ast.Constant) and elt.value == '*':
                                # Replace ["*"] with env var lookup
                                keyword.value = ast.parse(
                                    'os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")'
                                ).body[0].value
                                self.patches_applied.append("cors_wildcard_fix")
                                logger.info("AST: patched CORS wildcard")
        
        # Patch hardcoded SECRET_KEY? Harder to do in visit_Call as it's an assignment
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # Patch hardcoded SECRET_KEY
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'SECRET_KEY':
                if isinstance(node.value, ast.Constant):
                    # Replace hardcoded string
                    node.value = ast.parse(
                        'os.environ.get("SECRET_KEY", __import__("secrets").token_hex(32))'
                    ).body[0].value
                    self.patches_applied.append("secret_key_hardening")
                    logger.info("AST: patched hardcoded SECRET_KEY")
        return self.generic_visit(node)
