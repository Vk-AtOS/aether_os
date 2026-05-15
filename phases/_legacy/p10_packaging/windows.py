"""
Aether-One Windows packaging utilities.

This module builds a relocatable Windows bundle for local distribution:

    dist/windows/aether-one/
        run-aether-one.bat
        run-aether-one.ps1
        README.txt

The bundle is intentionally simple and local-first:

- It does NOT require PyInstaller or MSI tooling.
- It bootstraps a local virtualenv inside the bundle on first run.
- It installs dependencies from the project's requirements.txt if present.
- It uses PYTHONPATH to point at the Aether-One project directory.
- It launches the Aether-One CLI via `python -m aetherone.cli`.

You can:

- Zip `dist/windows/aether-one` and ship it to Windows users.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WindowsBundleResult:
    """
    Result of creating a Windows bundle.

    Attributes:
        bundle_dir: Root directory of the bundle.
        bat_launcher: Path to the .bat launcher.
        ps_launcher: Path to the PowerShell launcher.
        readme_path: Path to the bundle's README file.
    """

    bundle_dir: Path
    bat_launcher: Path
    ps_launcher: Path
    readme_path: Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def create_windows_bundle(
    project_path: str,
    *,
    output_dir: Optional[str] = None,
    app_dir_name: str = "aether-one",
) -> WindowsBundleResult:
    """
    Create a Windows bundle for Aether-One.

    Arguments:
        project_path:
            Root of the Aether-One project (where `aetherone/` lives).
        output_dir:
            Base output directory for bundles. If None, uses:
                <project_path>/dist/windows
        app_dir_name:
            Name of the app directory under output_dir (default: "aether-one").

    Returns:
        WindowsBundleResult describing the bundle layout.
    """
    project_root = Path(project_path).expanduser().resolve()
    if not project_root.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_root}")

    if output_dir is None:
        output_root = project_root / "dist" / "windows"
    else:
        output_root = Path(output_dir).expanduser().resolve()

    bundle_dir = output_root / app_dir_name
    _ensure_dir(bundle_dir)

    bat_launcher = bundle_dir / "run-aether-one.bat"
    ps_launcher = bundle_dir / "run-aether-one.ps1"
    readme_path = bundle_dir / "README.txt"

    project_root_str = str(project_root)

    # Batch launcher
    bat_contents = f"""@echo off
setlocal enabledelayedexpansion

REM Aether-One Windows bundle launcher (.bat)

REM Resolve bundle directory (where this script lives)
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "PROJECT_DIR={project_root_str}"
set "VENV_DIR=%APP_DIR%\\.venv"
set "PYTHON_BIN=%VENV_DIR%\\Scripts\\python.exe"

echo [Aether-One] Windows bundle launcher
echo   APP_DIR:      %APP_DIR%
echo   PROJECT_DIR:  %PROJECT_DIR%
echo   VENV_DIR:     %VENV_DIR%

IF NOT EXIST "%VENV_DIR%" (
    echo [Aether-One] Creating virtualenv...
    python -m venv "%VENV_DIR%"
    "%PYTHON_BIN%" -m pip install --upgrade pip
    IF EXIST "%PROJECT_DIR%\\requirements.txt" (
        echo [Aether-One] Installing dependencies from requirements.txt...
        "%PYTHON_BIN%" -m pip install -r "%PROJECT_DIR%\\requirements.txt"
    ) ELSE (
        echo [Aether-One] WARNING: requirements.txt not found in %PROJECT_DIR%
    )
)

REM Ensure Python can import the project-local aetherone package
IF DEFINED PYTHONPATH (
    set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"
) ELSE (
    set "PYTHONPATH=%PROJECT_DIR%"
)

cd /d "%PROJECT_DIR%"
echo [Aether-One] Launching orchestrator CLI...
"%PYTHON_BIN%" -m aetherone.cli %*
endlocal
"""

    bat_launcher.write_text(bat_contents, encoding="utf-8")

    # PowerShell launcher
    ps_contents = f"""#!/usr/bin/env pwsh
# Aether-One Windows bundle launcher (PowerShell)

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsFromCaller
)

$ErrorActionPreference = "Stop"

# Resolve bundle directory (where this script lives)
$ScriptPath = $MyInvocation.MyCommand.Path
$AppDir = Split-Path -Parent $ScriptPath
$ProjectDir = "{project_root_str}"
$VenvDir = Join-Path $AppDir ".venv"
$PythonBin = Join-Path $VenvDir "Scripts/python.exe"

Write-Host "[Aether-One] Windows bundle launcher (PowerShell)"
Write-Host "  APP_DIR:      $AppDir"
Write-Host "  PROJECT_DIR:  $ProjectDir"
Write-Host "  VENV_DIR:     $VenvDir"

if (-not (Test-Path $VenvDir)) {{
    Write-Host "[Aether-One] Creating virtualenv..."
    python -m venv $VenvDir
    & $PythonBin -m pip install --upgrade pip
    $req = Join-Path $ProjectDir "requirements.txt"
    if (Test-Path $req) {{
        Write-Host "[Aether-One] Installing dependencies from requirements.txt..."
        & $PythonBin -m pip install -r $req
    }} else {{
        Write-Host "[Aether-One] WARNING: requirements.txt not found in $ProjectDir"
    }}
}}

# Ensure Python can import the project-local aetherone package
if ($env:PYTHONPATH) {{
    $env:PYTHONPATH = "$ProjectDir;$($env:PYTHONPATH)"
}} else {{
    $env:PYTHONPATH = $ProjectDir
}}

Set-Location $ProjectDir
Write-Host "[Aether-One] Launching orchestrator CLI..."
& $PythonBin -m aetherone.cli @ArgsFromCaller
"""

    ps_launcher.write_text(ps_contents, encoding="utf-8")

    readme_contents = f"""Aether-One Windows Bundle
==========================

This directory was generated by aetherone.packaging_windows.

Contents
--------

- run-aether-one.bat
    Double-click this file in Explorer to launch Aether-One.
    On first run it will:

    - Create a private virtual environment inside this folder (.venv)
    - Install dependencies from the project's requirements.txt (if present)
    - Set PYTHONPATH to the Aether-One project directory
    - Launch the Aether-One CLI via: python -m aetherone.cli

- run-aether-one.ps1
    PowerShell launcher with the same behaviour.

Usage (Developer)
-----------------

From Command Prompt (cmd.exe):

    cd "{bundle_dir}"
    run-aether-one.bat --help

From PowerShell:

    cd "{bundle_dir}"
    .\\run-aether-one.ps1 --help

Assumptions
-----------

- The original project root is:
    {project_root}
- The 'aetherone/' package directory lives under that root.
- Python 3 is available as 'python' on this system.

To rebuild this bundle:
-----------------------

From the project root:

    python -m aetherone.packaging_windows \\
      --project "{project_root}" \\
      --output-dir "{output_root}"

Distribution
------------

You can zip or 7z the entire "{bundle_dir}" directory and
ship it alongside the same project tree. Users do not need
global Python packages; everything is local to this bundle
and the project.
"""

    readme_path.write_text(readme_contents, encoding="utf-8")

    logger.info("Windows bundle created at %s", bundle_dir)

    return WindowsBundleResult(
        bundle_dir=bundle_dir,
        bat_launcher=bat_launcher,
        ps_launcher=ps_launcher,
        readme_path=readme_path,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entrypoint for `python -m aetherone.packaging_windows`.

    Example:

        python -m aetherone.packaging_windows --project . --output-dir dist/windows
    """
    parser = argparse.ArgumentParser(
        description="Build a Windows bundle for Aether-One."
    )
    parser.add_argument(
        "--project",
        "-p",
        dest="project",
        default=".",
        help="Path to the Aether-One project root (default: current directory).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        dest="output_dir",
        default=None,
        help="Output directory for the Windows bundle (default: <project>/dist/windows).",
    )
    parser.add_argument(
        "--app-dir-name",
        dest="app_dir_name",
        default="aether-one",
        help="Name of the app directory inside the output dir (default: aether-one).",
    )

    args = parser.parse_args(argv)

    try:
        result = create_windows_bundle(
            project_path=args.project,
            output_dir=args.output_dir,
            app_dir_name=args.app_dir_name,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to create Windows bundle: %s", exc)
        raise SystemExit(1) from exc

    print("Aether-One Windows bundle created:")
    print(f"  Bundle dir : {result.bundle_dir}")
    print(f"  .bat       : {result.bat_launcher}")
    print(f"  .ps1       : {result.ps_launcher}")
    print(f"  README     : {result.readme_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

