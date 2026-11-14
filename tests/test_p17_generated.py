"""KAN-99/KAN-109: generated operator RBAC is valid YAML and the Dockerfile builds without a go.sum."""
import yaml

from aether_os.phases.p17_control_plane.operator_generator import (
    generate_operator_dockerfile, generate_rbac_yaml)


def test_role_yaml_parses_with_clean_resource_names():
    docs = list(yaml.safe_load_all(generate_rbac_yaml("my-app", [{"table": "invoice_items"}, {"table": "orders"}])))
    role = docs[0]
    own = [r for r in role["rules"] if r["apiGroups"] == ["my-app.aetheros.io"]]
    assert own[0]["resources"] == ["invoiceitemss", "orderss"]
    assert own[1]["resources"] == ["invoiceitemss/status", "orderss/status"]
    dep = [r for r in role["rules"] if "deployments" in r["resources"]][0]
    assert dep["apiGroups"] == ["apps"]
    assert docs[1]["kind"] == "ClusterRoleBinding"


def test_role_yaml_without_entities_is_valid():
    assert list(yaml.safe_load_all(generate_rbac_yaml("x", [])))


def test_dockerfile_does_not_require_go_sum():
    df = generate_operator_dockerfile()
    assert "COPY go.mod go.sum" not in df and "go mod tidy" in df
