"""KAN-131: an India fintech build is not denied by default; APAC is not India."""

from aether_os.core.policy.compliance import ComplianceContext, ComplianceEngine


def _ctx(country="IN", region="APAC", industries=("fintech",), **kw):
    base = dict(country_code=country, region=region, deployment_type="saas", data_sensitivity="moderate",
                handles_personal_data=True, handles_biometric_data=False, handles_children_data=False,
                industries=list(industries), high_risk_use_cases=[], uses_strong_crypto=True, uses_weak_crypto=False,
                customer_requires_data_residency=False, uses_third_country_cloud=False, model_providers=[], repo_tags=[])
    base.update(kw)
    return ComplianceContext(**base)


def _ids(d):
    return {v.rule_id for v in d.violations}


def test_default_saas_india_fintech_is_not_denied_but_asks_to_confirm_hosting():
    d = ComplianceEngine().evaluate(_ctx())
    assert d.allowed and not d.denied
    assert "IN_RBI_DATA_LOCALISATION" not in _ids(d) and "IN_RBI_DATA_LOCALISATION_UNCONFIRMED" in _ids(d)


def test_hosting_in_india_clears_the_localisation_finding_and_hosting_abroad_denies():
    ok = ComplianceEngine().evaluate(_ctx(hosting_country="IN"))
    assert not ok.denied and not {i for i in _ids(ok) if "LOCALISATION" in i}
    # not blocked by default (KAN-131): hosting abroad asks for approval
    for kw in ({"hosting_country": "US"}, {"uses_third_country_cloud": True}):
        d = ComplianceEngine().evaluate(_ctx(**kw))
        assert not d.denied and d.requires_approval and "IN_RBI_DATA_LOCALISATION" in _ids(d)


def test_operator_can_opt_into_the_hard_rbi_deny(monkeypatch):
    monkeypatch.setenv("AETHER_RBI_LOCALISATION_BLOCK", "1")
    assert ComplianceEngine().evaluate(_ctx(hosting_country="US")).denied


def test_non_india_apac_gets_no_india_rules_and_india_non_fintech_needs_no_approval():
    sg = ComplianceEngine().evaluate(_ctx(country="SG", industries=("fintech",)))
    assert not {i for i in _ids(sg) if i.startswith("IN_")}
    plain = ComplianceEngine().evaluate(_ctx(industries=("retail",)))
    assert plain.allowed and not plain.requires_approval
