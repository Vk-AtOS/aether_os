import click
import json
import os
import requests
from pathlib import Path

CONFIG_FILE = Path.home() / ".aetheros" / "config.json"

def get_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def save_config(cfg):
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg))

@click.group()
def cli():
    pass

@cli.command()
@click.option("--url", required=True)
@click.option("--email", required=True)
@click.option("--password", required=True)
def login(url, email, password):
    resp = requests.post(f"{url}/auth/login", json={"email": email, "password": password})
    if resp.status_code == 200:
        data = resp.json()
        save_config({"url": url, "token": data["access_token"]})
        click.echo("Logged in successfully.")
    else:
        click.echo(f"Login failed: {resp.text}")

@cli.command()
@click.argument("requirement")
@click.option("--domain", default="general")
def start(requirement, domain):
    cfg = get_config()
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    resp = requests.post(f"{cfg['url']}/factory/start", 
                         headers=headers, 
                         json={"requirement": requirement, "domain": domain})
    click.echo(resp.json())

if __name__ == "__main__":
    cli()
