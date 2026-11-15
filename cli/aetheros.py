"""AetherOS Factory CLI — interact with your factory from the terminal."""
from __future__ import annotations

import json
import logging
import time
import webbrowser
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

import typer
import requests
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.markup import escape
from rich import box

app = typer.Typer(
    name="aether",
    help="[bold cyan]AetherOS Factory CLI[/bold cyan] — build production apps from a single prompt.",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

CONFIG_DIR  = Path.home() / ".aetheros"
CONFIG_FILE = CONFIG_DIR / "config.json"

PHASE_ORDER = [
    "p01_intake_requirements", "p02_architecture", "p03_scaffolding",
    "p04_backend", "p05_frontend", "p06_review_security", "p07_testing",
    "p07b_self_healing", "p08_cicd_deployment", "p09_observability",
    "p10_docs_delivery", "p11_deployment",
]
PHASE_LABEL = {
    "p01_intake_requirements": "Intake",       "p02_architecture":   "Architecture",
    "p03_scaffolding":         "Scaffolding",  "p04_backend":        "Backend",
    "p05_frontend":            "Frontend",     "p06_review_security":"Security",
    "p07_testing":             "Testing",      "p07b_self_healing":  "Self-Heal",
    "p08_cicd_deployment":     "CI/CD",        "p09_observability":  "Observability",
    "p10_docs_delivery":       "Docs",         "p11_deployment":     "Deploy",
}

# ── config helpers ────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception as e:
            logger.warning("_load_cfg: could not parse config file: %s", e)
            return {}
    return {}

def _save_cfg(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)

def _require_cfg() -> dict:
    cfg = _load_cfg()
    if not cfg.get("token") or not cfg.get("url"):
        console.print("[red]Not logged in.[/red] Run [bold]aether login[/bold] first.")
        raise typer.Exit(1)
    return cfg

def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"}

def _get(cfg: dict, path: str, **kwargs):
    url = cfg["url"].rstrip("/") + path
    r = requests.get(url, headers=_headers(cfg), timeout=30, **kwargs)
    r.raise_for_status()
    return r

def _post(cfg: dict, path: str, **kwargs):
    url = cfg["url"].rstrip("/") + path
    r = requests.post(url, headers=_headers(cfg), timeout=60, **kwargs)
    r.raise_for_status()
    return r

def _delete(cfg: dict, path: str, **kwargs):
    url = cfg["url"].rstrip("/") + path
    r = requests.delete(url, headers=_headers(cfg), timeout=30, **kwargs)
    r.raise_for_status()
    return r

# ── status helpers ────────────────────────────────────────────────────────────

STATUS_STYLE = {
    "running":     "bold cyan",
    "completed":   "bold green",
    "failed":      "bold red",
    "interrupted": "yellow",
    "pending":     "dim",
    "passed":      "bold green",
}

def _style_status(s: str) -> Text:
    return Text(s.upper(), style=STATUS_STYLE.get(s.lower(), "white"))

def _phase_bar(phases: dict, width: int = 24) -> str:
    filled, total = 0, len(PHASE_ORDER)
    for p in PHASE_ORDER:
        st = (phases.get(p) or {}).get("status", "")
        if st in ("passed", "completed", "timeout"):
            filled += 1
    blocks = int((filled / total) * width)
    bar = "█" * blocks + "░" * (width - blocks)
    return f"[green]{bar}[/green] {filled}/{total}"

# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def login(
    url:      str = typer.Option(..., "--url",      "-u", help="Gateway URL, e.g. http://localhost:8000", prompt="Gateway URL"),
    email:    str = typer.Option(..., "--email",    "-e", help="Your account email",                      prompt="Email"),
    password: str = typer.Option(..., "--password", "-p", help="Your password", hide_input=True,          prompt="Password"),
):
    """Authenticate and save credentials locally."""
    url = url.rstrip("/")
    with console.status("Authenticating…"):
        try:
            r = requests.post(f"{url}/auth/login", json={"email": email, "password": password}, timeout=15)
            r.raise_for_status()
        except requests.HTTPError as e:
            console.print(f"[red]Login failed:[/red] {e.response.text}")
            raise typer.Exit(1) from e
        except Exception as e:
            console.print(f"[red]Connection error:[/red] {e}")
            raise typer.Exit(1) from e
    data = r.json()
    if data.get("mfa_required"):
        # MFA account: /auth/login returns only a short-lived challenge, no access_token.
        code = typer.prompt("Authenticator code")
        try:
            r = requests.post(f"{url}/auth/mfa/confirm", json={"mfa_token": data["mfa_token"], "code": code}, timeout=15)
            r.raise_for_status()
        except requests.HTTPError as e:
            console.print(f"[red]MFA failed:[/red] {e.response.text}")
            raise typer.Exit(1) from e
        except Exception as e:
            console.print(f"[red]Connection error:[/red] {e}")
            raise typer.Exit(1) from e
        data = r.json()
    _save_cfg({"url": url, "token": data["access_token"], "email": email})
    console.print(Panel(f"[bold green]Logged in[/bold green] as [cyan]{email}[/cyan]\nGateway: {url}", title="AetherOS", border_style="green"))


@app.command()
def logout():
    """Clear local credentials."""
    cfg = _load_cfg()
    if cfg:
        try:
            _post(cfg, "/auth/logout")
        except Exception as exc:
            logger.debug("CLI logout: server-side logout call failed (non-fatal): %s", exc)
    _save_cfg({})
    console.print("[green]Logged out.[/green]")


@app.command()
def whoami():
    """Show current logged-in user."""
    cfg = _require_cfg()
    try:
        r = _get(cfg, "/account/usage")
        d = r.json()
        console.print(Panel(
            f"[bold]{cfg.get('email','—')}[/bold]\n"
            f"Plan: [cyan]{d.get('plan','free')}[/cyan]  "
            f"Org: [cyan]{d.get('org_name','—')}[/cyan]\n"
            f"Gateway: {cfg['url']}",
            title="Who am I", border_style="cyan"
        ))
    except Exception as e:
        logger.warning("whoami: could not fetch account usage: %s", e)
        console.print(f"Email: {cfg.get('email','—')}  Gateway: {cfg['url']}")


@app.command("run")
def run_pipeline(
    requirement: str = typer.Argument(..., help="Natural-language requirement for the factory"),
    domain:      str = typer.Option("general",  "--domain",  "-d", help="Project domain (web, api, data, mobile…)"),
    name:        str = typer.Option("",         "--name",    "-n", help="Optional project name"),
    watch:       bool = typer.Option(False,     "--watch",   "-w", help="Stream progress after starting"),
    template:    str = typer.Option("",         "--template","-t", help="Template ID to use"),
):
    """Start a new factory run."""
    cfg = _require_cfg()
    payload: dict = {"raw_input": requirement, "domain": domain}
    if name:     payload["project_name"] = name
    if template: payload["template_id"]  = template
    with console.status("[cyan]Starting factory run…[/cyan]"):
        try:
            r = _post(cfg, "/factory/start", json=payload)
        except requests.HTTPError as e:
            console.print(f"[red]Failed:[/red] {e.response.text}")
            raise typer.Exit(1) from e
    data   = r.json()
    run_id = data.get("run_id") or data.get("id")
    console.print(Panel(
        f"[bold green]Run started[/bold green]\nID: [cyan]{run_id}[/cyan]\nDomain: {domain}\n"
        f"\nTrack with: [bold]aether status {run_id}[/bold]\nStream logs: [bold]aether logs {run_id}[/bold]",
        title="Factory Run", border_style="green",
    ))
    if watch:
        _do_watch(cfg, run_id)


@app.command("ls")
def list_runs(
    limit:  int = typer.Option(20, "--limit", "-l", help="Number of runs to show"),
    status: str = typer.Option("",  "--status",     help="Filter by status (running/completed/failed)"),
):
    """List factory runs."""
    cfg = _require_cfg()
    with console.status("Fetching runs…"):
        try:
            params = {"limit": limit}
            if status: params["status"] = status
            r = _get(cfg, "/factory/runs", params=params)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from e
    data = r.json()
    runs = data.get("items") or data.get("runs") or (data if isinstance(data, list) else [])

    t = Table(box=box.ROUNDED, border_style="bright_black", header_style="bold cyan", show_lines=False)
    t.add_column("ID",        style="dim cyan",  max_width=36, no_wrap=True)
    t.add_column("Project",   style="bold white", max_width=30)
    t.add_column("Status",    justify="center",  min_width=12)
    t.add_column("Domain",    style="dim",       max_width=12)
    t.add_column("Progress",  min_width=28)
    t.add_column("Cost",      justify="right",   style="green")
    t.add_column("Started",   style="dim",       max_width=16)

    for run in runs:
        rid    = run.get("run_id") or run.get("id") or "—"
        pname  = run.get("project_name") or "Untitled"
        st     = run.get("status") or "unknown"
        domain = run.get("domain") or "—"
        cost   = run.get("cost") or run.get("total_cost") or 0
        ts     = run.get("started_at")
        phases = run.get("phases") or {}
        bar    = _phase_bar(phases)
        ts_str = time.strftime("%m/%d %H:%M", time.localtime(ts)) if ts else "—"
        t.add_row(rid, pname, _style_status(st), domain, bar, f"${cost:.3f}" if cost else "—", ts_str)

    if not runs:
        console.print("[dim]No runs found.[/dim]")
    else:
        console.print(t)
        console.print(f"[dim]{len(runs)} run(s) shown[/dim]")


@app.command()
def status(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
    raw:    bool = typer.Option(False, "--raw", "-r", help="Print raw JSON"),
):
    """Show detailed status of a factory run."""
    cfg = _require_cfg()
    with console.status(f"Fetching {run_id}…"):
        try:
            r = _get(cfg, f"/factory/runs/{run_id}")
        except requests.HTTPError as e:
            console.print(f"[red]Not found:[/red] {e}")
            raise typer.Exit(1) from e
    run = r.json()
    if raw:
        console.print_json(json.dumps(run))
        return

    phases = run.get("phases") or {}
    t = Table(title=f"Phase Status — {run.get('project_name','—')}", box=box.SIMPLE_HEAD,
              header_style="bold cyan", border_style="bright_black")
    t.add_column("Phase",    style="dim")
    t.add_column("Status",   justify="center")
    t.add_column("Duration", justify="right", style="dim")

    for p in PHASE_ORDER:
        info = phases.get(p) or {}
        st   = info.get("status") or "—"
        dur  = info.get("duration_s")
        dur_s = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "—"
        t.add_row(PHASE_LABEL.get(p, p), _style_status(st), dur_s)

    cost = run.get("cost") or run.get("total_cost") or 0
    console.print(Panel(
        f"Project: [bold]{run.get('project_name','—')}[/bold]\n"
        f"Status:  {_style_status(run.get('status','—'))}\n"
        f"Phase:   {run.get('current_phase','—')}\n"
        f"Cost:    [green]${cost:.4f}[/green]\n"
        f"Bar:     {_phase_bar(phases)}",
        title=f"Run {run_id[:16]}…", border_style="cyan",
    ))
    console.print(t)


@app.command()
def logs(
    run_id: str = typer.Argument(..., help="Run ID to stream"),
    tail:   int = typer.Option(50, "--tail", "-n", help="Lines of history to show"),
    follow: bool = typer.Option(True, "--follow/--no-follow", "-f/-F", help="Stream new events"),
):
    """Stream live logs from a factory run."""
    cfg = _require_cfg()
    url = cfg["url"].rstrip("/") + f"/factory/runs/{run_id}/stream"
    hdrs = _headers(cfg)
    hdrs["Accept"] = "text/event-stream"

    console.print(f"[dim]Streaming logs for [cyan]{run_id}[/cyan] — [bold]Ctrl+C[/bold] to stop[/dim]\n")
    try:
        with requests.get(url, headers=hdrs, stream=True, timeout=None) as resp:
            resp.raise_for_status()
            lines_shown = 0
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        console.print("\n[green]Run complete.[/green]")
                        break
                    try:
                        ev = json.loads(payload)
                        phase  = ev.get("phase", "")
                        msg    = ev.get("message") or ev.get("log") or str(ev)
                        etype  = ev.get("type", "")
                        label  = PHASE_LABEL.get(phase, phase) if phase else ""
                        prefix = f"[dim cyan][{label}][/dim cyan] " if label else ""
                        style  = "green" if etype == "complete" else "red" if etype == "error" else ""
                        if style:
                            console.print(f"{prefix}[{style}]{escape(msg)}[/{style}]")
                        else:
                            console.print(f"{prefix}{escape(msg)}")
                        lines_shown += 1
                        if not follow and lines_shown >= tail:
                            break
                    except json.JSONDecodeError:
                        console.print(f"[dim]{line}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except Exception as e:
        logger.warning("stream_logs: stream error for run %s: %s", run_id, e)
        console.print(f"[red]Stream error:[/red] {e}")
        console.print(f"[dim]Try [bold]aether status {run_id}[/bold] for a snapshot.[/dim]")


def _do_watch(cfg: dict, run_id: str) -> None:
    """Poll status until complete, showing a live phase bar."""
    with Live(console=console, refresh_per_second=2) as live:
        while True:
            try:
                r = _get(cfg, f"/factory/runs/{run_id}")
                run = r.json()
                st  = run.get("status", "running")
                phases = run.get("phases") or {}
                bar = _phase_bar(phases)
                cur = run.get("current_phase", "—")
                live.update(Panel(
                    f"Status: {_style_status(st)}  Phase: {cur}\nProgress: {bar}",
                    title=f"[cyan]{run.get('project_name','—')}[/cyan]",
                    border_style="cyan",
                ))
                if st in ("completed", "failed", "interrupted"):
                    break
            except Exception as _e:
                logger.warning("_do_watch: watch error for run %s: %s", run_id, _e)
                console.print(f"[red]Watch error:[/red] {_e}")
                break
            time.sleep(3)


@app.command()
def cancel(
    run_id: str = typer.Argument(..., help="Run ID to cancel"),
    force:  bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Cancel a running factory pipeline."""
    cfg = _require_cfg()
    if not force:
        typer.confirm(f"Cancel run {run_id}?", abort=True)
    with console.status(f"Cancelling {run_id}…"):
        try:
            _post(cfg, f"/factory/runs/{run_id}/cancel")
        except requests.HTTPError as e:
            console.print(f"[red]Failed:[/red] {e.response.text}")
            raise typer.Exit(1) from e
    console.print(f"[yellow]Cancelled[/yellow] run [cyan]{run_id}[/cyan]")


@app.command()
def download(
    run_id:  str = typer.Argument(..., help="Run ID to download artifacts from"),
    out_dir: str = typer.Option(".", "--out", "-o", help="Output directory"),
):
    """Download all artifacts from a completed run."""
    cfg = _require_cfg()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with console.status("Fetching artifact list…"):
        try:
            r = _get(cfg, f"/factory/runs/{run_id}/artifacts")
        except requests.HTTPError as e:
            console.print(f"[red]Failed:[/red] {e.response.text}")
            raise typer.Exit(1) from e
    artifacts = r.json()
    if isinstance(artifacts, dict):
        artifacts = artifacts.get("items") or artifacts.get("artifacts") or []

    if not artifacts:
        console.print("[yellow]No artifacts found.[/yellow]")
        return

    console.print(f"[cyan]Downloading {len(artifacts)} artifact(s) to [bold]{out}[/bold]…[/cyan]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TimeElapsedColumn(), console=console) as prog:
        task = prog.add_task("Downloading", total=len(artifacts))
        for art in artifacts:
            fpath = art.get("path") or art.get("name") or f"artifact_{art.get('id','?')}"
            art_id = art.get("id")
            if art_id:
                try:
                    res = _get(cfg, f"/factory/artifacts/{art_id}/download", stream=True)
                    dest = out / Path(fpath).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(res.content)
                except Exception as e:
                    logger.warning("download: could not download artifact %s: %s", fpath, e)
                    console.print(f"[red]  ✗ {fpath}:[/red] {e}")
            prog.advance(task)
    console.print(f"[green]Done.[/green] Artifacts saved to [bold]{out}[/bold]")


@app.command("open")
def open_project(
    run_id: str = typer.Argument(..., help="Run ID to open in browser"),
):
    """Open a factory run in the web dashboard."""
    cfg = _require_cfg()
    base = cfg["url"].rstrip("/")
    # Dashboard is on same host, port 3000 or /dashboard
    dashboard_url = base.replace(":8000", ":3000").replace(":8080", ":3000")
    url = f"{dashboard_url}/project/{run_id}"
    console.print(f"Opening [link={url}]{url}[/link]")
    webbrowser.open(url)


@app.command()
def config(
    url:   Optional[str] = typer.Option(None, "--url",   help="Override gateway URL"),
    token: Optional[str] = typer.Option(None, "--token", help="Override auth token"),
    show:  bool          = typer.Option(False, "--show",  help="Print current config"),
):
    """View or update CLI configuration."""
    cfg = _load_cfg()
    if url:
        cfg["url"] = url.rstrip("/")
    if token:
        cfg["token"] = token
    if url or token:
        _save_cfg(cfg)
        console.print("[green]Config updated.[/green]")
    if show or not (url or token):
        safe = {k: (v[:8] + "…" if k == "token" and v else v) for k, v in cfg.items()}
        console.print_json(json.dumps(safe, indent=2))


@app.command()
def health():
    """Check gateway health."""
    cfg = _require_cfg()
    with console.status("Checking health…"):
        try:
            r = _get(cfg, "/health")
        except Exception as e:
            console.print(f"[red]Unreachable:[/red] {e}")
            raise typer.Exit(1) from e
    data = r.json()
    st = data.get("status", "unknown")
    style = "green" if st in ("ok", "healthy") else "yellow"
    console.print(Panel(
        f"Status: [{style}]{st.upper()}[/{style}]\n"
        + "\n".join(f"  {k}: {v}" for k, v in data.items() if k != "status"),
        title="Gateway Health", border_style=style,
    ))


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    app()

if __name__ == "__main__":
    main()
