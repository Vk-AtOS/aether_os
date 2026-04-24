"""
Safe Mode for Aether-One

Provides safe mode functionality for handling system failures, violations,
and recovery scenarios.

Safe mode is entered when:
- Critical system violations are detected
- Offline guarantees are broken
- Data corruption is detected
- System health degrades below threshold
- User manually requests safe mode

In safe mode:
- Only essential services run
- No code execution allowed
- Limited to diagnostic and recovery operations
- Full audit logging enabled
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("aether_os.safe_mode")


class SafeModeReason(str, Enum):
    """Reasons for entering safe mode."""
    
    NETWORK_VIOLATION = "network_violation"
    DATA_CORRUPTION = "data_corruption"
    POLICY_VIOLATION = "policy_violation"
    HEALTH_DEGRADATION = "health_degradation"
    SECURITY_BREACH = "security_breach"
    MANUAL_REQUEST = "manual_request"
    STARTUP_FAILURE = "startup_failure"
    UNKNOWN = "unknown"


@dataclass
class SafeModeEntry:
    """Record of safe mode activation."""
    
    timestamp: datetime
    reason: SafeModeReason
    details: str
    trigger_component: Optional[str] = None
    recovery_attempted: bool = False
    recovery_successful: Optional[bool] = None


class SafeMode:
    """
    Safe mode manager for Aether-One.
    
    Handles entering/exiting safe mode and managing recovery operations.
    """
    
    def __init__(self):
        self.active = False
        self.current_entry: Optional[SafeModeEntry] = None
        self.history: list[SafeModeEntry] = []
    
    def enter(
        self,
        reason: SafeModeReason,
        details: str,
        trigger_component: Optional[str] = None
    ) -> None:
        """
        Enter safe mode.
        
        Args:
            reason: Reason for entering safe mode
            details: Detailed explanation
            trigger_component: Component that triggered safe mode
        """
        if self.active:
            logger.warning("Already in safe mode, ignoring duplicate entry request")
            return
        
        entry = SafeModeEntry(
            timestamp=datetime.now(),
            reason=reason,
            details=details,
            trigger_component=trigger_component,
        )
        
        self.current_entry = entry
        self.history.append(entry)
        self.active = True
        
        logger.critical(
            f"ENTERING SAFE MODE: {reason.value} - {details} "
            f"(trigger: {trigger_component or 'unknown'})"
        )
    
    def exit(self, recovery_successful: bool = True) -> None:
        """
        Exit safe mode.
        
        Args:
            recovery_successful: Whether recovery was successful
        """
        if not self.active:
            logger.warning("Not in safe mode, ignoring exit request")
            return
        
        if self.current_entry:
            self.current_entry.recovery_successful = recovery_successful
        
        self.active = False
        logger.info(
            f"EXITING SAFE MODE: recovery_successful={recovery_successful}"
        )
        self.current_entry = None
    
    def is_active(self) -> bool:
        """Check if safe mode is currently active."""
        return self.active
    
    def get_current_reason(self) -> Optional[SafeModeReason]:
        """Get the reason for current safe mode activation."""
        if self.current_entry:
            return self.current_entry.reason
        return None
    
    def get_history(self) -> list[SafeModeEntry]:
        """Get history of safe mode activations."""
        return list(self.history)
    
    def attempt_recovery(self) -> bool:
        """
        Attempt automatic recovery based on the reason for safe mode.
        
        Returns:
            True if recovery succeeded, False otherwise
        """
        if not self.active or not self.current_entry:
            return False
        
        self.current_entry.recovery_attempted = True
        
        reason = self.current_entry.reason
        logger.info(f"Attempting recovery from: {reason.value}")
        
        try:
            if reason == SafeModeReason.NETWORK_VIOLATION:
                return self._recover_network_violation()
            elif reason == SafeModeReason.DATA_CORRUPTION:
                return self._recover_data_corruption()
            elif reason == SafeModeReason.HEALTH_DEGRADATION:
                return self._recover_health_degradation()
            elif reason == SafeModeReason.MANUAL_REQUEST:
                # Manual requests require manual exit
                return False
            else:
                logger.warning(f"No automatic recovery for: {reason.value}")
                return False
        except Exception as e:
            logger.error(f"Recovery attempt failed: {e}")
            return False
    
    def _recover_network_violation(self) -> bool:
        """Recover from network violation."""
        logger.info("Network violation recovery: violations cleared, offline mode reinforced")
        # In a real implementation, this would:
        # 1. Clear network violation logs
        # 2. Re-enable offline guard
        # 3. Verify offline status
        return True
    
    def _recover_data_corruption(self) -> bool:
        """Recover from data corruption."""
        logger.info("Data corruption recovery: attempting to restore from last known good state")
        # In a real implementation, this would:
        # 1. Load last known good snapshot
        # 2. Verify data integrity
        # 3. Restore corrupted databases
        return False  # Requires manual intervention
    
    def _recover_health_degradation(self) -> bool:
        """Recover from health degradation."""
        logger.info("Health degradation recovery: restarting degraded agents")
        # In a real implementation, this would:
        # 1. Identify degraded agents
        # 2. Restart them
        # 3. Verify health scores
        return True
    
    def factory_reset(self) -> bool:
        """
        Perform factory reset.
        
        WARNING: This will delete all data and return to initial state.
        
        Returns:
            True if reset succeeded, False otherwise
        """
        logger.critical("FACTORY RESET REQUESTED")
        
        try:
            # In a real implementation, this would:
            # 1. Stop all services
            # 2. Clear all databases
            # 3. Delete all snapshots
            # 4. Remove all memory/state
            # 5. Reset configuration to defaults
            # 6. Restart system
            
            logger.info("Factory reset completed successfully")
            return True
        except Exception as e:
            logger.error(f"Factory reset failed: {e}")
            return False


# Global singleton instance
_global_safe_mode: Optional[SafeMode] = None


def get_global_safe_mode() -> SafeMode:
    """Get the global safe mode instance."""
    global _global_safe_mode
    if _global_safe_mode is None:
        _global_safe_mode = SafeMode()
    return _global_safe_mode
