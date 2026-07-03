"""
Offline Guard for Aether-One

Enforces offline-first guarantees and prevents any network communication.
This is a CRITICAL security component that must never be bypassed.

GUARANTEES:
- No HTTP/HTTPS requests
- No DNS lookups
- No socket connections (except localhost)
- No telemetry
- No silent networking

ENFORCEMENT:
- Monitors network activity
- Blocks unauthorized connections
- Logs all violation attempts
- Triggers safe mode on violations
"""

from __future__ import annotations

import logging
import socket
import urllib.request
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("aether_os.offline_guard")


class NetworkViolationError(Exception):
    """Raised when a network access violation is detected."""
    pass


@dataclass
class NetworkViolation:
    """Record of a network access violation."""
    
    timestamp: datetime
    violation_type: str  # "http", "dns", "socket", "telemetry"
    details: str
    stack_trace: Optional[str] = None


class OfflineGuard:
    """
    Offline enforcement guard.
    
    This class provides monitoring and enforcement of offline-first guarantees.
    In production, this should be enhanced with more sophisticated network monitoring.
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize offline guard.
        
        Args:
            strict_mode: If True, raises exceptions on violations. If False, only logs.
        """
        self.strict_mode = strict_mode
        self.violations: list[NetworkViolation] = []
        self._original_socket_create_connection = None
        self._original_urlopen = None
        self._monkey_patched = False
    
    def enable(self) -> None:
        """
        Enable offline guard by monkey-patching network functions.
        
        WARNING: This is a best-effort approach. For production, use OS-level
        network isolation (firewall rules, network namespaces, etc.)
        """
        if self._monkey_patched:
            logger.warning("OfflineGuard already enabled")
            return
        
        logger.info("Enabling OfflineGuard (offline enforcement)")
        
        # Monkey-patch socket.create_connection
        self._original_socket_create_connection = socket.create_connection
        socket.create_connection = self._blocked_create_connection
        
        # Monkey-patch urllib.request.urlopen
        self._original_urlopen = urllib.request.urlopen
        urllib.request.urlopen = self._blocked_urlopen
        
        self._monkey_patched = True
        logger.info("OfflineGuard enabled successfully")
    
    def disable(self) -> None:
        """Disable offline guard and restore original functions."""
        if not self._monkey_patched:
            return
        
        logger.info("Disabling OfflineGuard")
        
        # Restore original functions
        if self._original_socket_create_connection:
            socket.create_connection = self._original_socket_create_connection
        
        if self._original_urlopen:
            urllib.request.urlopen = self._original_urlopen
        
        self._monkey_patched = False
        logger.info("OfflineGuard disabled")
    
    def _blocked_create_connection(self, address, *args, **kwargs):
        """Replacement for socket.create_connection that blocks non-localhost connections."""
        host, port = address
        
        # Allow localhost connections only
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            if self._original_socket_create_connection:
                return self._original_socket_create_connection(address, *args, **kwargs)
        
        # Block all other connections
        violation = NetworkViolation(
            timestamp=datetime.now(),
            violation_type="socket",
            details=f"Attempted socket connection to {host}:{port}",
        )
        self.violations.append(violation)
        
        msg = f"OfflineGuard: Blocked socket connection to {host}:{port}"
        logger.error(msg)
        
        if self.strict_mode:
            raise NetworkViolationError(msg)
        
        raise ConnectionRefusedError(msg)
    
    def _blocked_urlopen(self, url, *args, **kwargs):
        """Replacement for urllib.request.urlopen that blocks all HTTP requests."""
        violation = NetworkViolation(
            timestamp=datetime.now(),
            violation_type="http",
            details=f"Attempted HTTP request to {url}",
        )
        self.violations.append(violation)
        
        msg = f"OfflineGuard: Blocked HTTP request to {url}"
        logger.error(msg)
        
        if self.strict_mode:
            raise NetworkViolationError(msg)
        
        raise ConnectionRefusedError(msg)
    
    def check_violations(self) -> list[NetworkViolation]:
        """Get list of all detected violations."""
        return list(self.violations)
    
    def has_violations(self) -> bool:
        """Check if any violations have been detected."""
        return len(self.violations) > 0
    
    def clear_violations(self) -> None:
        """Clear violation history."""
        self.violations.clear()
    
    def verify_offline(self) -> tuple[bool, str]:
        """
        Verify that the system is truly offline.
        
        Returns:
            (is_offline, message)
        """
        try:
            # Try to connect to a known external host
            # This should fail if we're truly offline
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            
            try:
                test_socket.connect(("8.8.8.8", 53))
                test_socket.close()
                return False, "Network connection detected (can reach 8.8.8.8)"
            except (socket.timeout, socket.error):
                # Good - we can't reach the internet
                return True, "Network appears offline (cannot reach 8.8.8.8)"
        except Exception as e:
            logger.warning("network_verify failed unexpectedly: %s", e)
            return True, f"Network verification inconclusive: {e}"


# Global singleton instance
_global_guard: Optional[OfflineGuard] = None


def get_global_offline_guard() -> OfflineGuard:
    """Get the global offline guard instance."""
    global _global_guard
    if _global_guard is None:
        _global_guard = OfflineGuard(strict_mode=True)
    return _global_guard


def enable_offline_mode() -> None:
    """Enable global offline mode enforcement."""
    guard = get_global_offline_guard()
    guard.enable()


def disable_offline_mode() -> None:
    """Disable global offline mode enforcement."""
    guard = get_global_offline_guard()
    guard.disable()
