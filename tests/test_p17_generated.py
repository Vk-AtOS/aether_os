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


# ── KAN-109 / KAN-196: the operator compiles from what is generated and reconciles for real ──
import os
import re
import shutil
import subprocess

import pytest


def _operator(tmp_path):
    from aether_os.phases.p17_control_plane.operator_generator import generate_operator_package
    ents = [{"table": "order", "fields": [{"name": "title", "type": "string", "required": True}, {"name": "qty"}]},
            {"table": "customer", "fields": []}]
    return generate_operator_package(ents, "shop", tmp_path)


def test_operator_imports_only_packages_that_are_generated_or_external(tmp_path):
    op = _operator(tmp_path)
    for go in op.rglob("*.go"):
        for imp in re.findall(r'"([^"]+)"', "\n".join(re.findall(r"import \((.*?)\)", go.read_text(), re.S))):
            assert not imp.startswith("shop-operator/api"), f"{go.name} imports a package nobody generates: {imp}"
    assert "MetricsBindAddress" not in (op / "main.go").read_text()   # removed in controller-runtime 0.17


def test_controllers_have_no_todo_and_no_duplicate_package_level_names(tmp_path):
    op = _operator(tmp_path)
    names = []
    for go in (op / "controllers").glob("*.go"):
        text = go.read_text()
        assert "TODO" not in text and "NotImplemented" not in text
        names += re.findall(r"^func (\w+)\(", text, re.M) + re.findall(r"^var (\w+)", text, re.M)
    assert len(names) == len(set(names)), [n for n in names if names.count(n) > 1]
    order = (op / "controllers" / "OrderController.go").read_text()
    assert 'requiredOrderFields = []string{"title"}' in order and 'Kind: "Order"' in order


def test_crd_status_has_phase(tmp_path):
    assert "phase:" in (_operator(tmp_path) / "config/crd/order_crd.yaml").read_text()


@pytest.mark.skipif(not shutil.which("go") or os.environ.get("AETHER_GO_BUILD_TEST") != "1",
                    reason="needs the go toolchain and network (go mod tidy); set AETHER_GO_BUILD_TEST=1")
def test_operator_builds_with_go(tmp_path):
    op = _operator(tmp_path)
    for cmd in (["go", "mod", "tidy"], ["go", "vet", "./..."]):
        done = subprocess.run(cmd, cwd=op, capture_output=True, text=True, timeout=600)
        assert done.returncode == 0, done.stdout + done.stderr
