from __future__ import annotations
import os
import logging
import re
import tempfile
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DOCKER_AVAILABLE = False
try:
    import docker
    client = docker.from_env()
    client.ping()
    DOCKER_AVAILABLE = True
    logger.info("Docker available")
except Exception:
    logger.warning(
        "Docker not available — sandbox disabled")

SANDBOX_IMAGE = os.getenv(
    "SANDBOX_IMAGE",
    "python:3.11-slim")
SANDBOX_TIMEOUT = int(os.getenv(
    "SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY = os.getenv(
    "SANDBOX_MEMORY", "128m")
SANDBOX_CPU = float(os.getenv(
    "SANDBOX_CPU", "0.5"))

@dataclass
class SandboxResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    docker_available: bool = True
    error: Optional[str] = None

def is_sandbox_available() -> bool:
    """Check if Docker sandbox is available."""
    return DOCKER_AVAILABLE

def run_in_sandbox(
    code: str,
    language: str = "python",
    timeout: int = SANDBOX_TIMEOUT
) -> SandboxResult:
    """
    Run code in an isolated Docker container.
    Returns SandboxResult with exit code, stdout, stderr.
    
    If Docker unavailable, returns a result indicating sandbox is disabled.
    """
    if not DOCKER_AVAILABLE:
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="Sandbox unavailable",
            docker_available=False,
            error="Docker not available"
        )
    
    try:
        import docker as dk
        client = dk.from_env()
        
        # Write code to temp file
        suffix = ".py" if language == "python" else ".js"
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=suffix,
            delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name
        
        try:
            if language == "python":
                cmd = ["python", f"/code/{os.path.basename(tmp_path)}"]
                image = "python:3.11-slim"
            else:
                cmd = ["node", f"/code/{os.path.basename(tmp_path)}"]
                image = "node:18-slim"
            
            container = client.containers.run(
                image=image,
                command=cmd,
                volumes={
                    os.path.dirname(tmp_path): {
                        "bind": "/code",
                        "mode": "ro"
                    }
                },
                mem_limit=SANDBOX_MEMORY,
                cpu_period=100000,
                cpu_quota=int(SANDBOX_CPU * 100000),
                network_disabled=True,
                read_only=True,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                timeout=timeout
            )
            
            output = container.decode("utf-8", errors="replace") if isinstance(container, bytes) else str(container)
            
            return SandboxResult(
                success=True,
                exit_code=0,
                stdout=output,
                stderr="",
                docker_available=True
            )
        
        except dk.errors.ContainerError as e:
            return SandboxResult(
                success=False,
                exit_code=e.exit_status,
                stdout="",
                stderr=str(e.stderr or ""),
                docker_available=True
            )
        
        except Exception as e:
            logger.warning("p08_cicd docker sandbox: run_in_sandbox execution failed: %s", e)
            timed_out = "timeout" in str(e).lower()
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=timed_out,
                docker_available=True,
                error=str(e)
            )
        
        finally:
            try:
                os.unlink(tmp_path)
            except Exception as exc:
                logger.debug("p08 docker: failed to unlink temp file %s (non-fatal): %s", tmp_path, exc)
    
    except Exception as e:
        logger.warning("p08_cicd docker sandbox: run_in_sandbox outer error: %s", e)
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            docker_available=False,
            error=str(e)
        )

def validate_patch_in_sandbox(
    original_code: str,
    patch_diff: str,
    language: str = "python"
) -> SandboxResult:
    """
    Apply a patch to original code and run it in a sandbox to validate.
    Returns SandboxResult.
    """
    if not DOCKER_AVAILABLE:
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="Sandbox unavailable",
            docker_available=False,
            error="Docker not available"
        )
    
    try:
        patched_code = _apply_simple_patch(original_code, patch_diff)
        return run_in_sandbox(patched_code, language)
    except Exception as e:
        logger.warning("p08_cicd docker sandbox: validate_patch_in_sandbox failed: %s", e)
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            docker_available=True,
            error=f"Patch apply failed: {e}"
        )

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _apply_simple_patch(original: str, patch_diff: str) -> str:
    """Apply a unified diff to `original` and return the whole patched file.

    The old version returned only the added and context lines of the diff, so any diff that did not
    cover the entire file produced a truncated file, and the sandbox validated that instead of the
    patched code. Hunks are placed by their header line numbers; context and removed lines must match
    the original exactly, else ValueError (a patch that does not apply must fail, not be guessed).
    """
    if not patch_diff or not patch_diff.strip():
        return original
    src = original.splitlines()
    out: list = []
    pos = 0                                   # next original line (0-based) not yet copied
    in_hunk = False
    for line in patch_diff.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            start = int(m.group(1)) - (0 if m.group(2) == "0" else 1)   # "-N,0" inserts after line N
            if start < pos or start > len(src):
                raise ValueError(f"hunk at line {m.group(1)} overlaps an earlier hunk or is past the end of the file")
            out.extend(src[pos:start])
            pos = start
            in_hunk = True
        elif not in_hunk or line.startswith(("--- ", "+++ ", "\\")):
            continue                          # file headers / "\ No newline at end of file"
        elif line.startswith("+"):
            out.append(line[1:])
        elif line.startswith(("-", " ")) or line == "":
            text = line[1:]
            if pos >= len(src) or src[pos] != text:
                raise ValueError(f"patch does not apply: expected {text!r} at line {pos + 1}")
            if line.startswith(" ") or line == "":
                out.append(text)
            pos += 1
    if not in_hunk:
        raise ValueError("not a unified diff: no @@ hunk header")
    out.extend(src[pos:])
    return "\n".join(out) + ("\n" if original.endswith("\n") or not original else "")
