"""The generated password-reset routes validate their bodies and never store a password unhashed."""
from aether_os.phases.p04a_backend_codegen.helpers import _fallback_auth_flow_code


def test_reset_routes_use_models_and_refuse_plaintext():
    code = _fallback_auth_flow_code()
    compile(code, "auth_flow.py", "exec")
    assert "body: ForgotPasswordRequest" in code and "body: ResetPasswordRequest" in code
    assert "new_password: str = _Field(min_length=8" in code
    assert "body: dict" not in code
    assert "user.password_hash = new_password" not in code and "status_code=503" in code
