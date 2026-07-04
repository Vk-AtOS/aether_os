"""
Long-form template strings for the AetherOS Python CLI generator.

Kept in a separate module so cli_generator.py stays under 600 lines.
Exports:
  gen_auth_commands_py()    — commands/auth.py  (login/logout/whoami/token)
  gen_config_commands_py()  — commands/config.py (set/get/reset)
  gen_entity_command_py()   — commands/<entity>.py (list/get/create/update/delete)
"""
from __future__ import annotations

from typing import Dict, List


def _label(name: str) -> str:
    return name.replace("_", " ").title()


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


# ── auth commands ─────────────────────────────────────────────────────────────

def gen_auth_commands_py() -> str:
    """Return the source for commands/auth.py."""
    return '''\
"""Auth commands — login, logout, whoami, token."""
import sys
import click
import httpx
from rich.console import Console
from rich.panel import Panel
from config import get_api_base, get_token, set_token

console = Console()
err_console = Console(stderr=True)


@click.group("auth")
def auth_group():
    """Authenticate and manage session tokens."""


@auth_group.command("login")
@click.option("--email", prompt=True, help="Account email address")
@click.option("--password", prompt=True, hide_input=True, help="Account password")
def login_cmd(email: str, password: str) -> None:
    """Log in and store your access token in the system keyring."""
    try:
        r = httpx.post(
            f"{get_api_base()}/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        r.raise_for_status()
        token = r.json().get("access_token", "")
        if not token:
            err_console.print("[red]Login failed: no access_token in response.[/red]")
            sys.exit(1)
        set_token(token)
        console.print("[green]Logged in successfully. Token stored.[/green]")
    except httpx.HTTPStatusError as exc:
        err_console.print(f"[red]Login failed ({exc.response.status_code}): {exc.response.text}[/red]")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Login error: {exc}[/red]")
        sys.exit(1)


@auth_group.command("logout")
def logout_cmd() -> None:
    """Clear the stored access token."""
    set_token("")
    console.print("[green]Logged out. Token cleared.[/green]")


@auth_group.command("whoami")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def whoami_cmd(as_json: bool) -> None:
    """Show the currently authenticated user."""
    token = get_token()
    if not token:
        err_console.print("[red]Not logged in. Run: auth login[/red]")
        sys.exit(1)
    try:
        r = httpx.get(
            f"{get_api_base()}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        if as_json:
            console.print_json(r.text)
        else:
            data = r.json()
            console.print(
                Panel(
                    "\\n".join(f"[bold]{k}[/bold]: {v}" for k, v in data.items()),
                    title="Current User",
                    border_style="blue",
                )
            )
    except httpx.HTTPStatusError as exc:
        err_console.print(f"[red]Request failed ({exc.response.status_code}): {exc.response.text}[/red]")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)


@auth_group.command("token")
def token_cmd() -> None:
    """Print the current access token (useful for scripting)."""
    token = get_token()
    if not token:
        err_console.print("[red]No token stored. Run: auth login[/red]")
        sys.exit(1)
    # Plain print so the value can be captured with $(...) without Rich markup
    print(token)
'''


# ── config commands ───────────────────────────────────────────────────────────

def gen_config_commands_py() -> str:
    """Return the source for commands/config.py."""
    return '''\
"""Config commands — set/get/reset API base URL."""
import sys
import click
from rich.console import Console
from config import get_api_base, set_api_base, reset_config

console = Console()
err_console = Console(stderr=True)


@click.group("config")
def config_group():
    """Manage CLI configuration (API URL, defaults)."""


@config_group.group("set")
def config_set_group():
    """Set a configuration value."""


@config_set_group.command("api-url")
@click.argument("url")
def config_set_api_url(url: str) -> None:
    """Set the API base URL (e.g. https://api.example.com)."""
    set_api_base(url)
    console.print(f"[green]API URL set to:[/green] {url}")


@config_group.group("get")
def config_get_group():
    """Get a configuration value."""


@config_get_group.command("api-url")
def config_get_api_url() -> None:
    """Show the current API base URL."""
    url = get_api_base()
    console.print(f"[bold]API URL:[/bold] {url}")


@config_group.command("reset")
@click.confirmation_option(prompt="Reset all config to defaults?")
def config_reset() -> None:
    """Reset all configuration to factory defaults."""
    reset_config()
    console.print("[green]Configuration reset to defaults.[/green]")
'''


# ── entity commands ───────────────────────────────────────────────────────────

def gen_entity_command_py(entity: Dict) -> str:
    """Return a full production-grade commands/<entity>.py with list/get/create/update/delete."""
    table = entity.get("table", "item")
    fields: List[Dict] = [
        f for f in entity.get("fields", [])
        if f.get("name") not in ("id", "created_at", "updated_at", "password_hash")
    ]
    label = _label(table)

    # Build option strings for create/update
    create_opts = "\n".join(
        f'@click.option("--{f["name"].replace("_", "-")}", '
        f'help="{_label(f["name"])}")'
        for f in fields
    )
    create_params = ", ".join(f['name'] for f in fields)
    create_payload_items = ", ".join(
        f'"{f["name"]}": {f["name"]}' for f in fields
    )
    update_payload_items = ", ".join(
        f'"{f["name"]}": {f["name"]}' for f in fields
    )

    # Field names for interactive prompts
    field_names_list = repr([f["name"] for f in fields])

    return f'''\
"""CLI commands for {label}."""
import json as _json
import sys
import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from config import get_api_base, auth_header

console = Console()
err_console = Console(stderr=True)

_FIELDS = {field_names_list}


def _handle_error(exc: Exception) -> None:
    """Print a consistent error and exit."""
    if isinstance(exc, httpx.HTTPStatusError):
        err_console.print(
            f"[red]HTTP {{exc.response.status_code}}:[/red] {{exc.response.text[:400]}}"
        )
    else:
        err_console.print(f"[red]Error: {{exc}}[/red]")
    sys.exit(1)


@click.group("{table}")
def {table}_group():
    """Manage {label} records."""


@{table}_group.command("list")
@click.option("--limit", default=20, show_default=True, help="Max records to return")
@click.option("--skip", default=0, show_default=True, help="Records to skip (pagination)")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON instead of a table")
def list_cmd(limit: int, skip: int, as_json: bool) -> None:
    """List {label} records."""
    try:
        r = httpx.get(
            f"{{get_api_base()}}/{table}s",
            params={{"limit": limit, "skip": skip}},
            headers=auth_header(),
            timeout=30,
        )
        r.raise_for_status()
        if as_json:
            console.print_json(r.text)
            return
        data = r.json()
        rows = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            rows = [rows]
        tbl = Table(title="[bold cyan]{label}[/bold cyan]", show_lines=True)
        if rows:
            for col in rows[0]:
                tbl.add_column(str(col), style="white")
            for row in rows:
                tbl.add_row(*[str(row.get(c, "")) for c in rows[0]])
        else:
            tbl.add_column("(empty)")
        console.print(tbl)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@{table}_group.command("get")
@click.argument("id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON instead of a panel")
def get_cmd(id: str, as_json: bool) -> None:
    """Get a single {label} by ID."""
    try:
        r = httpx.get(
            f"{{get_api_base()}}/{table}s/{{id}}",
            headers=auth_header(),
            timeout=15,
        )
        r.raise_for_status()
        if as_json:
            console.print_json(r.text)
            return
        data = r.json()
        console.print(
            Panel(
                "\\n".join(f"[bold]{{k}}[/bold]: {{v}}" for k, v in data.items()),
                title=f"[cyan]{label} #{{id}}[/cyan]",
                border_style="blue",
            )
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@{table}_group.command("create")
@click.option("--data", "-d", "kv_pairs", multiple=True,
              metavar="KEY=VALUE", help="Field values (repeatable)")
@click.option("--interactive", "-i", is_flag=True, help="Prompt for each field interactively")
@click.option("--json", "as_json", is_flag=True, help="Output created record as raw JSON")
{create_opts}
def create_cmd(kv_pairs: tuple, interactive: bool, as_json: bool, {create_params}) -> None:
    """Create a new {label}.

    Provide values via --data KEY=VALUE flags, or use --interactive for prompts.
    Named options (e.g. --field-name) also work and take priority.
    """
    try:
        # Start with named option values (non-None only)
        payload: dict = {{
            k: v for k, v in {{{create_payload_items}}}.items()
            if v is not None
        }}
        # --data KEY=VALUE pairs (override named options)
        for pair in kv_pairs:
            if "=" in pair:
                k, v = pair.split("=", 1)
                payload[k.strip()] = v.strip()
        # --interactive prompts for any field not yet in payload
        if interactive:
            for field in _FIELDS:
                if field not in payload:
                    val = click.prompt(f"  {{field}}", default="", show_default=False)
                    if val:
                        payload[field] = val
        r = httpx.post(
            f"{{get_api_base()}}/{table}s",
            json=payload,
            headers=auth_header(),
            timeout=30,
        )
        r.raise_for_status()
        console.print("[green]Created successfully.[/green]")
        if as_json:
            console.print_json(r.text)
        else:
            data = r.json()
            console.print(
                Panel(
                    "\\n".join(f"[bold]{{k}}[/bold]: {{v}}" for k, v in data.items()),
                    title="[green]New {label}[/green]",
                    border_style="green",
                )
            )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@{table}_group.command("update")
@click.argument("id")
@click.option("--data", "-d", "kv_pairs", multiple=True,
              metavar="KEY=VALUE", help="Field values to update (repeatable)")
@click.option("--json", "as_json", is_flag=True, help="Output updated record as raw JSON")
{create_opts}
def update_cmd(id: str, kv_pairs: tuple, as_json: bool, {create_params}) -> None:
    """Update a {label} by ID.

    Only fields explicitly provided are sent — omitted fields are left unchanged.
    """
    try:
        payload: dict = {{
            k: v for k, v in {{{update_payload_items}}}.items()
            if v is not None
        }}
        for pair in kv_pairs:
            if "=" in pair:
                k, v = pair.split("=", 1)
                payload[k.strip()] = v.strip()
        if not payload:
            err_console.print("[yellow]No fields provided — nothing to update.[/yellow]")
            sys.exit(0)
        r = httpx.put(
            f"{{get_api_base()}}/{table}s/{{id}}",
            json=payload,
            headers=auth_header(),
            timeout=30,
        )
        r.raise_for_status()
        console.print("[green]Updated successfully.[/green]")
        if as_json:
            console.print_json(r.text)
        else:
            data = r.json()
            console.print(
                Panel(
                    "\\n".join(f"[bold]{{k}}[/bold]: {{v}}" for k, v in data.items()),
                    title=f"[cyan]{label} #{{id}} (updated)[/cyan]",
                    border_style="blue",
                )
            )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@{table}_group.command("delete")
@click.argument("id")
@click.option("--confirm", is_flag=True,
              help="Skip the confirmation prompt (useful for scripting)")
def delete_cmd(id: str, confirm: bool) -> None:
    """Delete a {label} by ID."""
    if not confirm:
        click.confirm(f"Delete {label} #{{id}}?", abort=True)
    try:
        r = httpx.delete(
            f"{{get_api_base()}}/{table}s/{{id}}",
            headers=auth_header(),
            timeout=15,
        )
        r.raise_for_status()
        console.print(f"[red]Deleted {label} #{{id}}.[/red]")
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
'''
