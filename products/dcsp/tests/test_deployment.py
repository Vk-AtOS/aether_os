from __future__ import annotations
import os
import pytest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)))

def test_dockerfile_exists():
    path = os.path.join(
        PROJECT_ROOT, "Dockerfile")
    assert os.path.isfile(path)

def test_dockerfile_has_healthcheck():
    path = os.path.join(
        PROJECT_ROOT, "Dockerfile")
    with open(path) as f:
        content = f.read()
    assert "HEALTHCHECK" in content

def test_dockerfile_has_nonroot_user():
    path = os.path.join(
        PROJECT_ROOT, "Dockerfile")
    with open(path) as f:
        content = f.read()
    assert "USER dcsp" in content

def test_dockerfile_exposes_8000():
    path = os.path.join(
        PROJECT_ROOT, "Dockerfile")
    with open(path) as f:
        content = f.read()
    assert "EXPOSE 8000" in content

def test_docker_compose_exists():
    path = os.path.join(
        PROJECT_ROOT, "docker-compose.yml")
    assert os.path.isfile(path)

def test_docker_compose_has_services():
    path = os.path.join(
        PROJECT_ROOT, "docker-compose.yml")
    with open(path) as f:
        content = f.read()
    assert "app:" in content
    assert "db:" in content
    assert "redis:" in content
    assert "worker:" in content

def test_dockerignore_exists():
    path = os.path.join(
        PROJECT_ROOT, ".dockerignore")
    assert os.path.isfile(path)

def test_k8s_dir_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s")
    assert os.path.isdir(path)

def test_k8s_deployment_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "deployment.yaml")
    assert os.path.isfile(path)

def test_k8s_deployment_replicas():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "deployment.yaml")
    with open(path) as f:
        content = f.read()
    assert "replicas: 2" in content

def test_k8s_service_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "service.yaml")
    assert os.path.isfile(path)

def test_k8s_namespace_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "namespace.yaml")
    assert os.path.isfile(path)

def test_k8s_secret_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "secret.yaml")
    assert os.path.isfile(path)

def test_k8s_ingress_exists():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "ingress.yaml")
    assert os.path.isfile(path)

def test_k8s_has_liveness_probe():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "deployment.yaml")
    with open(path) as f:
        content = f.read()
    assert "livenessProbe" in content

def test_k8s_has_resource_limits():
    path = os.path.join(
        PROJECT_ROOT, "k8s",
        "deployment.yaml")
    with open(path) as f:
        content = f.read()
    assert "resources:" in content
    assert "limits:" in content
