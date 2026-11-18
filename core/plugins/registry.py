"""
AetherOS — Plugin Registry

Plugins are the extension mechanism for AetherOS. Each plugin is a
self-contained bundle described by a YAML manifest:

  id:          "github"
  name:        "GitHub"
  version:     "1.0.0"
  type:        "connector"        # connector | skill | tool | provider
  description: "GitHub API integration for repo management"
  author:      "AetherOS"
  icon:        "github"
  config_schema:
    token:     { type: string, secret: true,  label: "Personal Access Token" }
    org:       { type: string, secret: false, label: "Default Organization" }
  capabilities:
    - read_repos
    - create_pr
    - manage_issues
  entry_point: "aether_os.core.plugins.connectors.github:GitHubConnector"

Plugins are discovered from three sources (in priority order):
  1. Built-in: shipped with AetherOS (core/plugins/builtin/)
  2. Installed: stored in ~/.aether_os/plugins/ (user-installed via marketplace)
  3. Org: per-org plugins from the DB (enterprise tier)

The registry is a process-level singleton that loads lazily on first access.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

_PLUGINS_DIR = Path.home() / ".aether_os" / "plugins"
_BUILTIN_DIR = Path(__file__).parent / "builtin"

# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ConfigField:
    type: str = "string"          # string | boolean | integer | select
    label: str = ""
    secret: bool = False
    required: bool = False
    default: Any = None
    options: List[str] = field(default_factory=list)  # for type=select


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    type: str                     # connector | skill | tool | provider
    description: str
    author: str = "AetherOS"
    icon: str = ""
    config_schema: Dict[str, ConfigField] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    entry_point: str = ""
    tags: List[str] = field(default_factory=list)
    is_builtin: bool = False
    requires_plan: str = "trial"  # minimum plan to install

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class InstalledPlugin:
    plugin_id: str
    org_id: str
    installed_at: float
    config: Dict[str, Any] = field(default_factory=dict)   # user-supplied values
    is_active: bool = True
    install_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "org_id": self.org_id,
            "installed_at": self.installed_at,
            "is_active": self.is_active,
            "install_id": self.install_id,
            # Never expose secret config values in API responses
            "config": {k: "***" if is_secret_key(k) else v for k, v in self.config.items()},
        }


_SECRET_HINTS = ("token", "secret", "password", "passwd", "key", "credential", "dsn", "auth", "bearer", "private")


def is_secret_key(name: str) -> bool:
    """Any config key that looks like a credential is masked in API responses."""
    n = str(name).lower()
    return any(h in n for h in _SECRET_HINTS)


def _pack_config(config: Dict[str, Any]) -> str:
    """Connector credentials are encrypted at rest (core/encryption.py)."""
    return encrypt(json.dumps(config))


def _unpack_config(stored: Optional[str]) -> Dict[str, Any]:
    """Decrypt a stored config; rows written before encryption was added are plain JSON."""
    raw = stored or "{}"
    try:
        raw = decrypt(raw)
    except ValueError:
        pass  # legacy plaintext row; re-encrypted on its next write
    return json.loads(raw)


# ── Built-in plugin manifests ─────────────────────────────────────────────────
# These are defined in code rather than YAML files for zero-dependency bootstrap.

BUILTIN_PLUGINS: List[PluginManifest] = [
    # ── Version Control ───────────────────────────────────────────────────────
    PluginManifest(
        id="github", name="GitHub", version="1.0.0", type="connector",
        description="Full GitHub integration: repos, PRs, issues, Actions CI/CD",
        icon="github", tags=["vcs", "devtools"],
        config_schema={
            "token":        ConfigField(type="string", label="Personal Access Token", secret=True, required=True),
            "default_org":  ConfigField(type="string", label="Default Organization"),
        },
        capabilities=["read_repos", "create_pr", "manage_issues", "trigger_workflow",
                       "read_actions", "clone_repo", "push_code"],
        entry_point="aether_os.core.plugins.connectors:GitHubConnector",
        is_builtin=True,
    ),
    PluginManifest(
        id="gitlab", name="GitLab", version="1.0.0", type="connector",
        description="GitLab integration: repos, MRs, pipelines, issues",
        icon="gitlab", tags=["vcs", "devtools"],
        config_schema={
            "token":        ConfigField(type="string", label="Personal Access Token", secret=True, required=True),
            "base_url":     ConfigField(type="string", label="GitLab URL", default="https://gitlab.com"),
        },
        capabilities=["read_repos", "create_mr", "manage_issues", "trigger_pipeline"],
        entry_point="aether_os.core.plugins.connectors:GitLabConnector",
        is_builtin=True,
    ),
    # ── Project Management ────────────────────────────────────────────────────
    PluginManifest(
        id="jira", name="Jira", version="1.0.0", type="connector",
        description="Jira integration: issues, sprints, epics, projects",
        icon="jira", tags=["pm", "agile"],
        config_schema={
            "base_url":     ConfigField(type="string", label="Jira URL", required=True),
            "email":        ConfigField(type="string", label="Email", required=True),
            "api_token":    ConfigField(type="string", label="API Token", secret=True, required=True),
        },
        capabilities=["create_issue", "update_issue", "list_sprints", "manage_epics"],
        entry_point="aether_os.core.plugins.connectors:JiraConnector",
        is_builtin=True,
    ),
    PluginManifest(
        id="linear", name="Linear", version="1.0.0", type="connector",
        description="Linear integration: issues, cycles, projects, teams",
        icon="linear", tags=["pm", "agile"],
        config_schema={
            "api_key":      ConfigField(type="string", label="API Key", secret=True, required=True),
            "team_id":      ConfigField(type="string", label="Default Team ID"),
        },
        capabilities=["create_issue", "update_issue", "list_cycles", "manage_projects"],
        entry_point="aether_os.core.plugins.connectors:LinearConnector",
        is_builtin=True,
    ),
    # ── Communication ─────────────────────────────────────────────────────────
    PluginManifest(
        id="slack", name="Slack", version="1.0.0", type="connector",
        description="Slack integration: messages, channels, notifications",
        icon="slack", tags=["comms"],
        config_schema={
            "bot_token":    ConfigField(type="string", label="Bot Token", secret=True, required=True),
            "channel":      ConfigField(type="string", label="Default Channel", default="#engineering"),
        },
        capabilities=["send_message", "create_channel", "post_file", "list_users"],
        entry_point="aether_os.core.plugins.connectors:SlackConnector",
        is_builtin=True,
    ),
    # ── Design ───────────────────────────────────────────────────────────────
    PluginManifest(
        id="figma", name="Figma", version="1.0.0", type="connector",
        description="Figma integration: export components, read design tokens",
        icon="figma", tags=["design"],
        config_schema={
            "access_token": ConfigField(type="string", label="Access Token", secret=True, required=True),
        },
        capabilities=["read_file", "export_component", "read_tokens", "list_projects"],
        entry_point="aether_os.core.plugins.connectors:FigmaConnector",
        is_builtin=True,
    ),
    # ── Cloud / Deployment ────────────────────────────────────────────────────
    PluginManifest(
        id="vercel", name="Vercel", version="1.0.0", type="connector",
        description="Deploy to Vercel: projects, deployments, domains, env vars",
        icon="vercel", tags=["deploy", "cloud"],
        config_schema={
            "token":        ConfigField(type="string", label="Access Token", secret=True, required=True),
            "team_id":      ConfigField(type="string", label="Team ID"),
        },
        capabilities=["create_deployment", "list_deployments", "set_env", "add_domain"],
        entry_point="aether_os.core.plugins.connectors:VercelConnector",
        is_builtin=True,
    ),
    PluginManifest(
        id="aws", name="AWS", version="1.0.0", type="connector",
        description="AWS: EC2, S3, Lambda, RDS, ECS, CloudFormation",
        icon="aws", tags=["cloud", "deploy"], requires_plan="growth",
        config_schema={
            "access_key_id":     ConfigField(type="string", label="Access Key ID", secret=True, required=True),
            "secret_access_key": ConfigField(type="string", label="Secret Access Key", secret=True, required=True),
            "region":            ConfigField(type="string", label="Default Region", default="us-east-1"),
        },
        capabilities=["deploy_lambda", "manage_s3", "manage_ec2", "run_ecs_task"],
        entry_point="aether_os.core.plugins.connectors:AWSConnector",
        is_builtin=True,
    ),
    PluginManifest(
        id="gcp", name="Google Cloud", version="1.0.0", type="connector",
        description="GCP: Cloud Run, GCS, Cloud SQL, Cloud Build",
        icon="gcp", tags=["cloud", "deploy"], requires_plan="growth",
        config_schema={
            "credentials_json": ConfigField(type="string", label="Service Account JSON", secret=True, required=True),
            "project_id":       ConfigField(type="string", label="Project ID", required=True),
        },
        capabilities=["deploy_cloud_run", "manage_gcs", "run_cloud_build"],
        entry_point="aether_os.core.plugins.connectors:GCPConnector",
        is_builtin=True,
    ),
    # ── Payments ─────────────────────────────────────────────────────────────
    PluginManifest(
        id="stripe", name="Stripe", version="1.0.0", type="connector",
        description="Stripe: generate payment integration code, test mode support",
        icon="stripe", tags=["payments", "fintech"],
        config_schema={
            "secret_key":   ConfigField(type="string", label="Secret Key", secret=True, required=True),
            "webhook_secret": ConfigField(type="string", label="Webhook Secret", secret=True),
        },
        capabilities=["generate_checkout", "generate_webhook_handler", "read_products"],
        entry_point="aether_os.core.plugins.connectors:StripeConnector",
        is_builtin=True,
    ),
    # ── Database / Storage ────────────────────────────────────────────────────
    PluginManifest(
        id="supabase", name="Supabase", version="1.0.0", type="connector",
        description="Supabase: tables, auth, storage, realtime, edge functions",
        icon="supabase", tags=["database", "backend"],
        config_schema={
            "url":          ConfigField(type="string", label="Project URL", required=True),
            "anon_key":     ConfigField(type="string", label="Anon Key", secret=True, required=True),
            "service_key":  ConfigField(type="string", label="Service Role Key", secret=True),
        },
        capabilities=["generate_schema", "generate_rls", "generate_auth", "read_schema"],
        entry_point="aether_os.core.plugins.connectors:SupabaseConnector",
        is_builtin=True,
    ),
    PluginManifest(
        id="planetscale", name="PlanetScale", version="1.0.0", type="connector",
        description="PlanetScale MySQL: branches, deploy requests, schema management",
        icon="planetscale", tags=["database"],
        config_schema={
            "service_token":    ConfigField(type="string", label="Service Token", secret=True, required=True),
            "service_token_id": ConfigField(type="string", label="Token ID", required=True),
            "org":              ConfigField(type="string", label="Organization", required=True),
        },
        capabilities=["create_branch", "deploy_schema", "read_schema"],
        entry_point="aether_os.core.plugins.connectors:PlanetScaleConnector",
        is_builtin=True,
    ),
    # ── Observability ─────────────────────────────────────────────────────────
    PluginManifest(
        id="sentry", name="Sentry", version="1.0.0", type="connector",
        description="Sentry: error tracking, release management, source maps",
        icon="sentry", tags=["observability", "monitoring"],
        config_schema={
            "dsn":          ConfigField(type="string", label="DSN", required=True),
            "auth_token":   ConfigField(type="string", label="Auth Token", secret=True),
            "org_slug":     ConfigField(type="string", label="Organization Slug"),
        },
        capabilities=["configure_sdk", "upload_sourcemaps", "list_issues"],
        entry_point="aether_os.core.plugins.connectors:SentryConnector",
        is_builtin=True,
    ),
    # ── Skills ────────────────────────────────────────────────────────────────
    PluginManifest(
        id="skill_auth", name="Auth Skill", version="1.0.0", type="skill",
        description="Generate complete authentication systems: JWT, OAuth, magic links, MFA",
        icon="lock", tags=["auth", "security"],
        capabilities=["jwt_auth", "oauth_google", "oauth_github", "magic_link", "mfa_totp"],
        entry_point="aether_os.core.plugins.skills:AuthSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_crud", name="CRUD Skill", version="1.0.0", type="skill",
        description="Generate full CRUD API with validation, pagination, filtering",
        icon="database", tags=["backend", "api"],
        capabilities=["rest_crud", "graphql_crud", "openapi_spec"],
        entry_point="aether_os.core.plugins.skills:CRUDSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_payment", name="Payment Skill", version="1.0.0", type="skill",
        description="Generate payment flows: Stripe checkout, subscriptions, webhooks",
        icon="credit-card", tags=["payments"],
        capabilities=["stripe_checkout", "stripe_subscription", "stripe_webhook"],
        entry_point="aether_os.core.plugins.skills:PaymentSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_email", name="Email Skill", version="1.0.0", type="skill",
        description="Generate email systems: transactional, templates, queue",
        icon="mail", tags=["email"],
        capabilities=["sendgrid_integration", "resend_integration", "email_templates"],
        entry_point="aether_os.core.plugins.skills:EmailSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_search", name="Search Skill", version="1.0.0", type="skill",
        description="Generate search: full-text, vector/semantic, faceted",
        icon="search", tags=["search"],
        capabilities=["postgres_fts", "typesense_integration", "vector_search"],
        entry_point="aether_os.core.plugins.skills:SearchSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_file_upload", name="File Upload Skill", version="1.0.0", type="skill",
        description="Generate file upload: S3/GCS/R2, image processing, virus scan",
        icon="upload", tags=["storage"],
        capabilities=["s3_upload", "r2_upload", "image_resize", "pdf_extract"],
        entry_point="aether_os.core.plugins.skills:FileUploadSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_notifications", name="Notifications Skill", version="1.0.0", type="skill",
        description="Generate notification systems: push, SMS, in-app, webhooks",
        icon="bell", tags=["notifications"],
        capabilities=["push_fcm", "sms_twilio", "in_app_notifications", "webhooks"],
        entry_point="aether_os.core.plugins.skills:NotificationsSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_analytics", name="Analytics Skill", version="1.0.0", type="skill",
        description="Generate analytics: events, dashboards, funnels, retention",
        icon="bar-chart", tags=["analytics"],
        capabilities=["event_tracking", "posthog_integration", "mixpanel_integration"],
        entry_point="aether_os.core.plugins.skills:AnalyticsSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_admin", name="Admin Panel Skill", version="1.0.0", type="skill",
        description="Generate admin panels: user management, data tables, exports",
        icon="settings", tags=["admin"],
        capabilities=["user_management", "data_tables", "csv_export", "role_management"],
        entry_point="aether_os.core.plugins.skills:AdminSkill",
        is_builtin=True,
    ),
    PluginManifest(
        id="skill_i18n", name="i18n Skill", version="1.0.0", type="skill",
        description="Generate internationalization: translation files, locale switching",
        icon="globe", tags=["i18n"],
        capabilities=["react_i18n", "next_i18n", "translation_files"],
        entry_point="aether_os.core.plugins.skills:I18nSkill",
        is_builtin=True,
    ),
]

_BUILTIN_INDEX: Dict[str, PluginManifest] = {p.id: p for p in BUILTIN_PLUGINS}


# ── Persistence (installed plugins — PostgreSQL via main engine) ──────────────
# No more per-process SQLite files. All workers share the installed_plugins table.

import time


async def _db_get_installed(org_id: str) -> List[InstalledPlugin]:
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import InstalledPluginRecord
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(InstalledPluginRecord)
                .where(InstalledPluginRecord.org_id == org_id)
            )).scalars().all()
        result = []
        for r in rows:
            try:
                cfg = _unpack_config(r.config_json)
            except Exception as e:
                logger.warning("PluginRegistry: could not parse config_json for plugin %s: %s", r.plugin_id, e)
                cfg = {}
            result.append(InstalledPlugin(
                install_id=r.id, plugin_id=r.plugin_id, org_id=r.org_id,
                config=cfg, is_active=True, installed_at=r.installed_at,
            ))
        return result
    except Exception as exc:
        logger.debug("PluginRegistry get_installed failed: %s", exc)
        return []


async def _db_install(plugin_id: str, org_id: str, config: Dict[str, Any], _retried: bool = False) -> InstalledPlugin:
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import InstalledPluginRecord
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    now = time.time()
    sf = get_session_factory()
    async with sf() as session:
        existing = (await session.execute(
            select(InstalledPluginRecord)
            .where(InstalledPluginRecord.org_id == org_id,
                   InstalledPluginRecord.plugin_id == plugin_id)
        )).scalar_one_or_none()
        if existing:
            existing.config_json  = _pack_config(config)
            existing.installed_at = now
            install_id = existing.id
        else:
            rec = InstalledPluginRecord(
                org_id=org_id, plugin_id=plugin_id,
                config_json=_pack_config(config), installed_at=now,
            )
            session.add(rec)
            try:
                await session.flush()
            except IntegrityError:
                # A concurrent install of the same plugin won the unique key (uq_installed_plugin_org_plugin).
                await session.rollback()
                if _retried:
                    raise
                return await _db_install(plugin_id, org_id, config, _retried=True)
            install_id = rec.id
        await session.commit()
    return InstalledPlugin(install_id=install_id, plugin_id=plugin_id, org_id=org_id,
                           config=config, is_active=True, installed_at=now)


async def _db_uninstall(plugin_id: str, org_id: str) -> bool:
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import InstalledPluginRecord
        from sqlalchemy import delete
        sf = get_session_factory()
        async with sf() as session:
            result = await session.execute(
                delete(InstalledPluginRecord)
                .where(InstalledPluginRecord.org_id == org_id,
                       InstalledPluginRecord.plugin_id == plugin_id)
            )
            await session.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("_db_uninstall failed for plugin %s org %s: %s", plugin_id, org_id, e)
        return False


async def _db_update_config(plugin_id: str, org_id: str, config: Dict[str, Any]) -> bool:
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import InstalledPluginRecord
        from sqlalchemy import update as sa_update
        sf = get_session_factory()
        async with sf() as session:
            result = await session.execute(
                sa_update(InstalledPluginRecord)
                .where(InstalledPluginRecord.org_id == org_id,
                       InstalledPluginRecord.plugin_id == plugin_id)
                .values(config_json=_pack_config(config))
            )
            await session.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("_db_update_config failed for plugin %s org %s: %s", plugin_id, org_id, e)
        return False


# ── Registry class ────────────────────────────────────────────────────────────

class PluginRegistry:
    """
    Central registry for all AetherOS plugins.
    Supports catalog browsing, install/uninstall, and live config updates.
    """

    # ── Catalog ───────────────────────────────────────────────────────────────

    def list_available(
        self,
        plugin_type: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[PluginManifest]:
        plugins = list(_BUILTIN_INDEX.values())
        if plugin_type:
            plugins = [p for p in plugins if p.type == plugin_type]
        if tag:
            plugins = [p for p in plugins if tag in p.tags]
        return plugins

    def get_manifest(self, plugin_id: str) -> Optional[PluginManifest]:
        return _BUILTIN_INDEX.get(plugin_id)

    # ── Installation ──────────────────────────────────────────────────────────

    async def install(
        self,
        plugin_id: str,
        org_id: str,
        config: Dict[str, Any],
        plan: str = "trial",
    ) -> InstalledPlugin:
        manifest = self.get_manifest(plugin_id)
        if not manifest:
            raise LookupError(f"Plugin '{plugin_id}' not found in registry")
        plan_order = ["trial", "starter", "growth", "enterprise"]
        required = manifest.requires_plan
        if plan_order.index(plan) < plan_order.index(required):
            raise PermissionError(
                f"Plugin '{plugin_id}' requires '{required}' plan (current: '{plan}')"
            )
        installed = await _db_install(plugin_id, org_id, config)
        logger.info("Plugin '%s' installed for org %s", plugin_id, org_id)
        return installed

    async def uninstall(self, plugin_id: str, org_id: str) -> bool:
        ok = await _db_uninstall(plugin_id, org_id)
        if ok:
            logger.info("Plugin '%s' uninstalled for org %s", plugin_id, org_id)
        return ok

    async def update_config(
        self, plugin_id: str, org_id: str, config: Dict[str, Any]
    ) -> bool:
        return await _db_update_config(plugin_id, org_id, config)

    async def get_installed(self, org_id: str) -> List[InstalledPlugin]:
        return await _db_get_installed(org_id)

    async def get_installed_config(
        self, plugin_id: str, org_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the raw (unmasked) config for a plugin — used by connector calls."""
        installed = await _db_get_installed(org_id)
        for p in installed:
            if p.plugin_id == plugin_id:
                return p.config  # Already decoded from DB
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
