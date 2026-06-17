"""
Active Directory / LDAP connector for enterprise SSO and user directory integration.

Uses the ldap3 library for all LDAP operations (pure Python, no system LDAP required).
All methods are run in a thread pool executor so they don't block the async event loop.

Typical config keys:
  server      — LDAP server hostname or IP, e.g. "dc.corp.example.com" or "ldap://dc:389"
  port        — LDAP port (default 389; 636 for LDAPS)
  use_ssl     — true/false (default false; set to true for LDAPS on port 636)
  bind_dn     — service account DN, e.g. "CN=svc-aetheros,OU=ServiceAccounts,DC=corp,DC=example,DC=com"
  bind_password — service account password
  base_dn     — search base, e.g. "DC=corp,DC=example,DC=com"
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from aether_os.core.plugins.connectors import BaseConnector, ConnectorError

logger = logging.getLogger(__name__)

# Default LDAP attributes to retrieve for user objects
_USER_ATTRIBUTES = [
    "cn", "sAMAccountName", "userPrincipalName", "mail",
    "displayName", "department", "title", "telephoneNumber",
    "memberOf", "userAccountControl",
]

# Active Directory objectClass filter for users
_USER_FILTER = "(&(objectClass=person)(objectCategory=user))"


def _run_sync(fn, *args):
    """Run a synchronous function in the default thread pool executor."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, fn, *args)


class LDAPConnector(BaseConnector):
    """
    Active Directory / LDAP connector.

    Expected config keys: server, bind_dn, bind_password, base_dn.
    Optional: port (default 389), use_ssl (default false).
    """

    def _get_server_info(self) -> Dict[str, Any]:
        """Extract and normalise connection parameters from config."""
        server = self.config.get("server", "")
        if not server:
            raise ConnectorError("LDAP connector requires 'server' in config")
        port = int(self.config.get("port", 636 if self.config.get("use_ssl") else 389))
        use_ssl = bool(self.config.get("use_ssl", False))
        return {"server": server, "port": port, "use_ssl": use_ssl}

    def _make_connection(self, bind_dn: str | None = None, bind_password: str | None = None):
        """
        Create and bind an ldap3 Connection.  Returns the connection object.
        Raises ConnectorError on failure.
        """
        try:
            from ldap3 import Server, Connection, ALL, NTLM, SAFE_SYNC  # type: ignore
        except ImportError as exc:
            raise ConnectorError(
                "ldap3 is not installed. Add it to requirements.txt: ldap3>=2.9"
            ) from exc

        info = self._get_server_info()
        bind_dn = bind_dn or self.config.get("bind_dn", "")
        bind_password = bind_password or self.config.get("bind_password", "")

        if not bind_dn or not bind_password:
            raise ConnectorError(
                "LDAP connector requires 'bind_dn' and 'bind_password' in config"
            )

        try:
            from ldap3 import Server, Connection, ALL
            srv = Server(
                info["server"],
                port=info["port"],
                use_ssl=info["use_ssl"],
                get_info=ALL,
                connect_timeout=10,
            )
            conn = Connection(srv, user=bind_dn, password=bind_password, auto_bind=True)
            return conn
        except Exception as exc:
            raise ConnectorError(f"LDAP bind failed: {exc}") from exc

    # ── Public async API ──────────────────────────────────────────────────────

    async def validate(
        self,
        server: str | None = None,
        bind_dn: str | None = None,
        bind_password: str | None = None,
    ) -> Dict[str, Any]:
        """
        Test LDAP connectivity by performing a bind operation.

        Returns {"ok": True, "server": ..., "bind_dn": ..., "message": ...} on success.
        """
        def _sync():
            try:
                info = self._get_server_info()
                _server = server or info["server"]
                _bind_dn = bind_dn or self.config.get("bind_dn", "")
                _bind_password = bind_password or self.config.get("bind_password", "")

                if not _bind_dn or not _bind_password:
                    return {"ok": False, "message": "bind_dn and bind_password are required"}

                try:
                    from ldap3 import Server, Connection, ALL
                except ImportError:
                    return {
                        "ok": False,
                        "message": "ldap3 not installed — run: pip install ldap3>=2.9",
                    }

                srv = Server(
                    _server,
                    port=info["port"],
                    use_ssl=info["use_ssl"],
                    get_info=ALL,
                    connect_timeout=10,
                )
                conn = Connection(srv, user=_bind_dn, password=_bind_password, auto_bind=True)
                conn.unbind()
                return {
                    "ok": True,
                    "server": _server,
                    "bind_dn": _bind_dn,
                    "message": f"LDAP bind successful to {_server}",
                }
            except ConnectorError as exc:
                return {"ok": False, "message": str(exc)}
            except Exception as exc:
                return {"ok": False, "message": str(exc)}

        return await asyncio.get_running_loop().run_in_executor(None, _sync)

    async def test(self) -> Dict[str, Any]:
        """BaseConnector compatibility — delegates to validate()."""
        return await self.validate()

    async def list_users(
        self,
        server: str | None = None,
        bind_dn: str | None = None,
        bind_password: str | None = None,
        base_dn: str | None = None,
        search_filter: str = _USER_FILTER,
        max_results: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Search for all user objects under base_dn.

        Returns a list of dicts with keys: cn, sAMAccountName, userPrincipalName,
        mail, displayName, department, title, telephoneNumber, memberOf.
        """
        def _sync():
            conn = self._make_connection(bind_dn, bind_password)
            _base = base_dn or self.config.get("base_dn", "")
            if not _base:
                raise ConnectorError("LDAP list_users requires 'base_dn'")

            try:
                conn.search(
                    search_base=_base,
                    search_filter=search_filter,
                    attributes=_USER_ATTRIBUTES,
                    size_limit=max_results,
                )
                users = []
                for entry in conn.entries:
                    user: Dict[str, Any] = {"dn": entry.entry_dn}
                    for attr in _USER_ATTRIBUTES:
                        try:
                            val = getattr(entry, attr, None)
                            if val is not None:
                                raw = val.value
                                if isinstance(raw, list):
                                    user[attr] = [str(v) for v in raw]
                                elif raw is not None:
                                    user[attr] = str(raw)
                        except Exception as exc:
                            logger.debug("LDAP user attribute parse error for attr %s: %s", attr, exc)
                    users.append(user)
                return users
            finally:
                conn.unbind()

        try:
            return await asyncio.get_running_loop().run_in_executor(None, _sync)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"LDAP list_users failed: {exc}") from exc

    async def authenticate_user(
        self,
        username: str,
        password: str,
        server: str | None = None,
        bind_dn: str | None = None,
        bind_password: str | None = None,
        base_dn: str | None = None,
    ) -> bool:
        """
        Authenticate a user against Active Directory / LDAP.

        Performs two operations:
          1. Service account bind (to search for the user's full DN)
          2. Bind with the user's own credentials (to verify their password)

        Returns True if authentication succeeds, False otherwise.
        """
        def _sync() -> bool:
            # Step 1: find the user's DN using the service account
            svc_conn = self._make_connection(bind_dn, bind_password)
            _base = base_dn or self.config.get("base_dn", "")
            if not _base:
                raise ConnectorError("LDAP authenticate_user requires 'base_dn'")

            user_dn: str | None = None
            try:
                # Search by sAMAccountName (AD) or uid (OpenLDAP)
                search_filter = (
                    f"(|(sAMAccountName={username})(uid={username})"
                    f"(userPrincipalName={username}))"
                )
                svc_conn.search(
                    search_base=_base,
                    search_filter=search_filter,
                    attributes=["dn"],
                    size_limit=2,
                )
                if svc_conn.entries:
                    user_dn = svc_conn.entries[0].entry_dn
            finally:
                svc_conn.unbind()

            if not user_dn:
                logger.info("LDAP authenticate_user: user '%s' not found", username)
                return False

            # Step 2: attempt bind with the user's own credentials
            try:
                from ldap3 import Server, Connection, ALL
                info = self._get_server_info()
                srv = Server(
                    server or info["server"],
                    port=info["port"],
                    use_ssl=info["use_ssl"],
                    get_info=ALL,
                    connect_timeout=10,
                )
                user_conn = Connection(srv, user=user_dn, password=password, auto_bind=True)
                user_conn.unbind()
                logger.info("LDAP authenticate_user: '%s' authenticated successfully", username)
                return True
            except Exception:
                logger.info("LDAP authenticate_user: '%s' authentication failed (bad password)", username)
                return False

        try:
            return await asyncio.get_running_loop().run_in_executor(None, _sync)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"LDAP authenticate_user failed: {exc}") from exc

    # ── BaseConnector action dispatch ─────────────────────────────────────────

    async def action_list_users(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self.list_users(
            base_dn=params.get("base_dn"),
            search_filter=params.get("search_filter", _USER_FILTER),
            max_results=int(params.get("max_results", 500)),
        )

    async def action_authenticate_user(self, params: Dict[str, Any]) -> Dict[str, Any]:
        username = params.get("username", "")
        password = params.get("password", "")
        if not username or not password:
            raise ConnectorError("action_authenticate_user requires 'username' and 'password'")
        ok = await self.authenticate_user(
            username=username,
            password=password,
            base_dn=params.get("base_dn"),
        )
        return {"authenticated": ok, "username": username}
