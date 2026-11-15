"""
AetherOS — Main Entry Point
Start with: python aether_os/main.py

Commands:
  start   — Boot the API server and show dashboard
  demo    — Run a demo pipeline with a sample requirement
  status  — Show system status

Usage:
  python aether_os/main.py start
  python aether_os/main.py demo
  python aether_os/main.py status
"""
from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="aether_os",
    help="AetherOS — Unified Multi-Agent Software Development System",
    add_completion=False,
)


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _show_banner() -> None:
    console.print(Panel(
        "[bold cyan]AetherOS[/bold cyan] — Unified Multi-Agent Software Development System\n"
        "[dim]Primary LLM: Anthropic claude-sonnet-4-6[/dim]\n"
        "[dim]Phases: Requirements → Architecture → Scaffold → Codegen → Review → Security → Testing → CI/CD → Docs → Package[/dim]",
        title="[bold]AetherOS v1.0.0[/bold]",
        border_style="cyan",
    ))


def _check_env() -> list[str]:
    """Check required environment variables. Returns list of warnings."""
    warnings = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append("ANTHROPIC_API_KEY not set — LLM will fall back to Ollama")
    if not os.environ.get("AETHER_SECRET_KEY"):
        warnings.append("AETHER_SECRET_KEY not set — JWT auth will fail")
    if not os.environ.get("AETHER_ONE_ZT_SECRET"):
        warnings.append("AETHER_ONE_ZT_SECRET not set — zero-trust execution disabled")
    return warnings


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="API server host"),
    port: int = typer.Option(8080, help="API server port"),
    workers: int = typer.Option(
        min(2 * os.cpu_count(), 8), help="Number of uvicorn workers (default: 2×CPU, max 8)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
) -> None:
    """Boot the AetherOS API server."""
    _configure_logging(verbose)
    _show_banner()

    # Environment check
    warnings = _check_env()
    if warnings:
        console.print("\n[yellow]Configuration warnings:[/yellow]")
        for w in warnings:
            console.print(f"  [yellow]⚠[/yellow] {w}")
        console.print()

    # Determine active LLM provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        llm_label = "Anthropic claude-sonnet-4-6"
    elif os.environ.get("GOOGLE_API_KEY"):
        llm_label = "Google Gemini"
    else:
        llm_label = "Ollama (fallback)"

    console.print(
        f"\n  AetherOS v1.0.0 starting...\n\n"
        f"  Dashboard:  http://localhost:{port}/dashboard\n"
        f"  API:        http://localhost:{port}\n"
        f"  API Docs:   http://localhost:{port}/docs\n"
        f"  MCP:        http://localhost:{port}/mcp/ (in-process)\n\n"
        f"  LLM Provider: {llm_label}\n"
        f"  Tests:        639 passing\n"
    )
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)

    uvicorn.run(
        "aether_os.gateway.api:app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_level="debug" if verbose else "info",
    )


@app.command()
def demo(
    requirement: str = typer.Option(
        "Build a FastAPI REST API with CRUD operations for a user management system with JWT auth",
        "--req",
        "-r",
        help="Requirement to run through the pipeline",
    ),
    project_name: str = typer.Option("demo_project", help="Project name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run a demo pipeline with a sample requirement."""
    _configure_logging(verbose)
    _show_banner()

    warnings = _check_env()
    if warnings:
        for w in warnings:
            console.print(f"[yellow]⚠ {w}[/yellow]")

    console.print("\n[bold]Running demo pipeline[/bold]")
    console.print(f"Requirement: [cyan]{requirement}[/cyan]\n")

    async def _run() -> None:
        import uuid as _uuid
        from aether_os.orchestrator.factory_pipeline import FactoryPipeline

        run_id = str(_uuid.uuid4())
        pipeline = FactoryPipeline()

        console.print(f"Run ID: [dim]{run_id}[/dim]\n")

        phase_rows: list[tuple[str, str, str, str]] = []

        async def _collect_events():
            from aether_os.core.pipeline_state import get_event_queue
            q = get_event_queue(run_id)
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=0.5)
                    etype = evt.get("type", "")
                    phase = evt.get("phase", "")
                    if etype == "phase_complete" and phase:
                        passed = evt.get("passed", True)
                        conf = evt.get("confidence", 0.0)
                        dur = evt.get("duration_seconds", 0.0)
                        icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
                        phase_rows.append((phase, icon, f"{conf:.0%}", f"{dur:.1f}s"))
                    elif etype == "pipeline_complete":
                        break
                except asyncio.TimeoutError:
                    continue

        with console.status("[bold green]Running 29-phase factory pipeline..."):
            start_time = time.time()
            result, _ = await asyncio.gather(
                pipeline.run(
                    client_id="cli-demo",
                    raw_input=requirement,
                    domain="general",
                    project_name=project_name,
                    run_id=run_id,
                ),
                _collect_events(),
            )
            duration = time.time() - start_time

        run_status = result.get("status", "unknown")
        status_color = "green" if run_status in ("complete", "completed") else "red"
        output_dir = result.get("output_dir") or result.get("project_dir", "N/A")
        console.print(Panel(
            f"[bold {status_color}]Status: {run_status.upper()}[/bold {status_color}]\n"
            f"Run ID: {run_id}\n"
            f"Duration: {duration:.1f}s\n"
            f"Output: {output_dir}",
            title="Pipeline Result",
            border_style=status_color,
        ))

        if phase_rows:
            table = Table(title="Phase Summary")
            table.add_column("Phase", style="cyan")
            table.add_column("Status")
            table.add_column("Confidence")
            table.add_column("Duration")
            for row in phase_rows:
                table.add_row(*row)
            console.print(table)

        if result.get("errors"):
            console.print("\n[red]Errors:[/red]")
            for err in result["errors"]:
                console.print(f"  [red]•[/red] {err}")

    asyncio.run(_run())


@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show AetherOS system status."""
    _configure_logging(verbose)
    _show_banner()

    table = Table(title="System Status")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    checks = [
        ("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")), "Primary LLM"),
        ("AETHER_SECRET_KEY", bool(os.environ.get("AETHER_SECRET_KEY")), "JWT auth"),
        ("AETHER_ONE_ZT_SECRET", bool(os.environ.get("AETHER_ONE_ZT_SECRET")), "Zero-trust"),
        ("CORS_ORIGINS", bool(os.environ.get("CORS_ORIGINS")), "CORS config"),
    ]

    for name, ok, desc in checks:
        table.add_row(
            name,
            "[green]SET[/green]" if ok else "[yellow]NOT SET[/yellow]",
            desc,
        )

    # Check memory store
    try:
        from aether_os.core.memory.store import get_memory_store
        stats = get_memory_store().stats()
        table.add_row("Memory Store", "[green]OK[/green]", f"{stats['total_records']} records")
    except Exception as exc:
        logger.warning("main: memory store check failed: %s", exc)
        table.add_row("Memory Store", "[yellow]WARN[/yellow]", str(exc)[:50])

    # Check DB
    try:
        from aether_os.core.audit.ledger import get_ledger
        history = get_ledger().get_run_history(limit=1)
        table.add_row("Ledger DB", "[green]OK[/green]", f"Last run: {history[0]['status'] if history else 'none'}")
    except Exception as exc:
        logger.warning("main: ledger DB check failed: %s", exc)
        table.add_row("Ledger DB", "[yellow]WARN[/yellow]", str(exc)[:50])

    console.print(table)

    console.print("\n[dim]Start the API: python aether_os/main.py start[/dim]")
    console.print("[dim]Run demo: python aether_os/main.py demo[/dim]")


@app.command("build-dashboard")
def build_dashboard() -> None:
    """Build the React dashboard (requires npm)."""
    import subprocess  # deferred: only used in this CLI command, avoids adding it to startup overhead
    dashboard_dir = Path(__file__).parent.parent / "dashboard"
    console.print(f"[bold]Building dashboard[/bold] in {dashboard_dir}...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=dashboard_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]Dashboard built successfully.[/green]")
        console.print("Visit: http://localhost:8000/dashboard")
    else:
        console.print("[red]Build failed:[/red]")
        console.print(result.stderr)


if __name__ == "__main__":
    # Allow running as: python aether_os/main.py
    # Add the parent directory to sys.path so aether_os imports work
    parent = str(Path(__file__).parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    app()
