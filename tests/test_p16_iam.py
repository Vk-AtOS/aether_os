"""KAN-99/KAN-109: generated OPA policy verifies the JWT, has a valid package, uses p02c permissions."""
import json
import re

from aether_os.phases.p16_iam.iam_generator import generate_iam_package, generate_opa_policy

PM = {"roles": ["Admin", "Staff"], "permissions": {"Admin": {"Invoice": ["read", "delete"]}, "Staff": {"Invoice": ["read"]}}}


def test_policy_verifies_signature_and_fails_closed():
    rego = generate_opa_policy(PM, "my-app")
    assert "io.jwt.decode_verify" in rego
    assert "base64url.decode" not in rego and "json.unmarshal" not in rego
    assert '"iss"' in rego and '"cert"' in rego


def test_package_name_is_valid_for_hyphen_and_quote_slugs():
    for slug in ["my-app", 'a"b', "x y", "../z", "UPPER"]:
        pkg = re.search(r"^package authz\.(\S+)$", generate_opa_policy(PM, slug), re.M).group(1)
        assert re.fullmatch(r"[a-z0-9_]+", pkg), (slug, pkg)


def test_permissions_key_from_p02c_is_used():
    rego = generate_opa_policy(PM, "app")
    assert 'claims.role == "Admin"' in rego and 'input.resource == "Invoice"' in rego
    assert '"delete"' in rego
    assert 'claims.role == "user"' not in rego  # defaults not used


def test_role_with_quote_cannot_inject_policy():
    rego = generate_opa_policy({"permissions": {'a" ; true ; "': {"r": ["read"]}}}, "app")
    assert 'claims.role == "a\\" ; true ; \\""' in rego


def test_realm_and_helm_use_dns_slug(tmp_path):
    d = generate_iam_package(PM, "My App!", tmp_path)
    realm = json.loads((d / "keycloak-realm.json").read_text())
    assert re.fullmatch(r"[a-z0-9-]+", realm["realm"])
    helm = (d / "opa-values.yaml").read_text()
    assert "my-app-opa-policy" in helm and "authz/my_app/allow" in helm
