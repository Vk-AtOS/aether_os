"""KAN-104: Velaris roles nobody holds are granted only by explicit configuration."""
from aether_os.core.velaris.roles import CONFIGURABLE_ROLES, velaris_roles

ENV = "AETHER_VELARIS_ROLE_GRANTS"


def test_default_grants_nothing_extra(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert velaris_roles("member") == frozenset()
    assert not (velaris_roles("owner") & CONFIGURABLE_ROLES)


def test_configured_grants_apply_per_org_role(monkeypatch):
    monkeypatch.setenv(ENV, '{"member": ["recruiter", "interviewer"]}')
    assert velaris_roles("member") == {"recruiter", "interviewer"}
    assert velaris_roles("viewer") == frozenset()
    assert "hr_admin" in velaris_roles("admin")          # defaults untouched


def test_admin_roles_cannot_be_granted_by_config(monkeypatch):
    monkeypatch.setenv(ENV, '{"member": ["hr_admin", "payroll_admin", "security_admin", "recruiter"]}')
    assert velaris_roles("member") == {"recruiter"}


def test_malformed_config_fails_closed(monkeypatch):
    for bad in ("not json", '["recruiter"]', '{"member": "recruiter"}'):
        monkeypatch.setenv(ENV, bad)
        assert velaris_roles("member") == frozenset()
