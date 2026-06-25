from __future__ import annotations
import json
import os
import pytest

EXTENSION_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(__file__)),
    "extensions", "vscode"
)

def test_extension_dir_exists():
    assert os.path.isdir(EXTENSION_DIR), \
        f"Extension dir not found: " \
        f"{EXTENSION_DIR}"

def test_package_json_exists():
    path = os.path.join(
        EXTENSION_DIR, "package.json")
    assert os.path.isfile(path)

def test_package_json_valid():
    path = os.path.join(
        EXTENSION_DIR, "package.json")
    with open(path) as f:
        pkg = json.load(f)
    assert pkg["name"] == "dcsp"
    assert "version" in pkg
    assert "engines" in pkg
    assert "vscode" in pkg["engines"]

def test_package_json_commands():
    path = os.path.join(
        EXTENSION_DIR, "package.json")
    with open(path) as f:
        pkg = json.load(f)
    commands = [
        c["command"]
        for c in pkg["contributes"][
            "commands"]
    ]
    assert "dcsp.repairFile" in commands
    assert "dcsp.showDashboard" in commands
    assert "dcsp.configure" in commands

def test_package_json_configuration():
    path = os.path.join(
        EXTENSION_DIR, "package.json")
    with open(path) as f:
        pkg = json.load(f)
    props = pkg["contributes"][
        "configuration"]["properties"]
    assert "dcsp.serverUrl" in props
    assert "dcsp.apiKey" in props
    assert "dcsp.autoRepair" in props

def test_tsconfig_exists():
    path = os.path.join(
        EXTENSION_DIR, "tsconfig.json")
    assert os.path.isfile(path)

def test_tsconfig_valid():
    path = os.path.join(
        EXTENSION_DIR, "tsconfig.json")
    with open(path) as f:
        cfg = json.load(f)
    assert "compilerOptions" in cfg
    assert cfg["compilerOptions"][
        "outDir"] == "./out"

def test_extension_source_exists():
    path = os.path.join(
        EXTENSION_DIR, "src",
        "extension.ts")
    assert os.path.isfile(path)

def test_extension_has_activate():
    path = os.path.join(
        EXTENSION_DIR, "src",
        "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "export function activate" \
        in content

def test_extension_has_deactivate():
    path = os.path.join(
        EXTENSION_DIR, "src",
        "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "export function deactivate" \
        in content

def test_extension_has_repair_command():
    path = os.path.join(
        EXTENSION_DIR, "src",
        "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "dcsp.repairFile" in content

def test_extension_has_dashboard_command():
    path = os.path.join(
        EXTENSION_DIR, "src",
        "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "dcsp.showDashboard" in content

def test_readme_exists():
    path = os.path.join(
        EXTENSION_DIR, "README.md")
    assert os.path.isfile(path)

def test_readme_has_content():
    path = os.path.join(
        EXTENSION_DIR, "README.md")
    with open(path) as f:
        content = f.read()
    assert "DCSP" in content
    assert len(content) > 100

def test_extension_has_status_bar():
    path = os.path.join(
        EXTENSION_DIR, "src", "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "statusBar" in content or \
        "StatusBar" in content or \
        "createStatusBarItem" in content

def test_extension_has_check_connection():
    path = os.path.join(
        EXTENSION_DIR, "src", "extension.ts")
    with open(path) as f:
        content = f.read()
    assert "checkConnection" in content

def test_package_json_has_check_command():
    path = os.path.join(
        EXTENSION_DIR, "package.json")
    with open(path) as f:
        pkg = json.load(f)
    commands = [
        c["command"]
        for c in pkg["contributes"]["commands"]
    ]
    assert "dcsp.checkConnection" in commands
