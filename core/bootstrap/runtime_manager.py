"""
Runtime Manager for Aether-One

Central coordinator for system lifecycle, initialization, and runtime management.

RESPONSIBILITIES:
- Bootstrap system in correct order
- Initialize all subsystems
- Manage runtime state transitions
- Monitor system health
- Handle power level management
- Coordinate graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List

from .environment_detector import EnvironmentInfo, detect_environment
from .offline_guard import OfflineGuard, get_global_offline_guard
from .safe_mode import SafeMode, SafeModeReason, get_global_safe_mode

logger = logging.getLogger("aether_os.runtime")


class RuntimeState(str, Enum):
    """Runtime states for Aether-One."""
    
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    SAFE_MODE = "safe_mode"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
    FAILED = "failed"


class PowerLevel(str, Enum):
    """Power levels for system operation."""
    
    MINIMAL = "minimal"        # Only essential services
    NORMAL = "normal"          # Standard operation
    FULL = "full"             # All features enabled
    DIAGNOSTIC = "diagnostic"  # Debug mode with extra logging


@dataclass
class RuntimeConfig:
    """Configuration for runtime manager."""
    
    base_path: Path
    offline_mode: bool = True
    strict_offline: bool = True
    power_level: PowerLevel = PowerLevel.NORMAL
    enable_telemetry: bool = False  # Must be False for offline mode
    auto_recovery: bool = True
    
    def validate(self) -> tuple[bool, list[str]]:
        """Validate configuration."""
        issues = []
        
        if self.offline_mode and self.enable_telemetry:
            issues.append("Telemetry cannot be enabled in offline mode")
        
        if not self.base_path.exists():
            issues.append(f"Base path does not exist: {self.base_path}")
        
        return len(issues) == 0, issues


@dataclass
class RuntimeStatus:
    """Current runtime status."""
    
    state: RuntimeState
    power_level: PowerLevel
    uptime_seconds: float
    environment: Optional[EnvironmentInfo]
    safe_mode_active: bool
    offline_guard_active: bool
    violations: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state.value,
            "power_level": self.power_level.value,
            "uptime_seconds": self.uptime_seconds,
            "environment": self.environment.to_dict() if self.environment else None,
            "safe_mode_active": self.safe_mode_active,
            "offline_guard_active": self.offline_guard_active,
            "violations": self.violations,
            "errors": self.errors,
        }


class RuntimeManager:
    """
    Central runtime manager for Aether-One.
    
    This is the authoritative entrypoint for system initialization and lifecycle.
    """
    
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.state = RuntimeState.UNINITIALIZED
        self.start_time: Optional[datetime] = None
        self.environment: Optional[EnvironmentInfo] = None
        self.offline_guard: OfflineGuard = get_global_offline_guard()
        self.safe_mode: SafeMode = get_global_safe_mode()
        
        # Component status tracking
        self.components_initialized: Dict[str, bool] = {}
        self.component_errors: Dict[str, str] = {}
    
    async def bootstrap(self) -> bool:
        """
        Bootstrap the entire system.
        
        Returns:
            True if bootstrap succeeded, False otherwise
        """
        logger.info("=" * 80)
        logger.info("Aether-One Bootstrap Starting")
        logger.info("=" * 80)
        
        self.state = RuntimeState.INITIALIZING
        self.start_time = datetime.now()
        
        try:
            # Step 1: Validate configuration
            if not await self._validate_config():
                return False
            
            # Step 2: Detect environment
            if not await self._detect_environment():
                return False
            
            # Step 3: Check minimum requirements
            if not await self._check_requirements():
                return False
            
            # Step 4: Enable offline guard
            if self.config.offline_mode:
                if not await self._enable_offline_guard():
                    return False
            
            # Step 5: Initialize core subsystems
            if not await self._initialize_subsystems():
                return False
            
            # Step 6: Start agent mesh
            if not await self._start_agent_mesh():
                return False
            
            # Step 7: Final verification
            if not await self._final_verification():
                return False
            
            # Bootstrap complete
            self.state = RuntimeState.RUNNING
            logger.info("=" * 80)
            logger.info("Aether-One Bootstrap Complete - System RUNNING")
            logger.info("=" * 80)
            
            return True
            
        except Exception as e:
            logger.critical(f"Bootstrap failed with exception: {e}", exc_info=True)
            self.state = RuntimeState.FAILED
            self.safe_mode.enter(
                SafeModeReason.STARTUP_FAILURE,
                f"Bootstrap failed: {e}",
                "RuntimeManager"
            )
            return False
    
    async def _validate_config(self) -> bool:
        """Validate runtime configuration."""
        logger.info("Step 1: Validating configuration...")
        
        valid, issues = self.config.validate()
        if not valid:
            for issue in issues:
                logger.error(f"  ✗ {issue}")
            self.component_errors["config"] = "; ".join(issues)
            return False
        
        logger.info("  ✓ Configuration valid")
        self.components_initialized["config"] = True
        return True
    
    async def _detect_environment(self) -> bool:
        """Detect system environment."""
        logger.info("Step 2: Detecting environment...")
        
        try:
            self.environment = detect_environment(self.config.base_path)
            logger.info(f"  ✓ OS: {self.environment.os_type} {self.environment.os_release}")
            logger.info(f"  ✓ CPU: {self.environment.cpu_count} cores @ {self.environment.cpu_freq_mhz or 0:.0f} MHz")
            logger.info(f"  ✓ RAM: {self.environment.memory_total_gb:.1f} GB total, {self.environment.memory_available_gb:.1f} GB available")
            logger.info(f"  ✓ Disk: {self.environment.disk_free_gb:.1f} GB free of {self.environment.disk_total_gb:.1f} GB total")
            logger.info(f"  ✓ Python: {self.environment.python_version}")
            
            self.components_initialized["environment"] = True
            return True
        except Exception as e:
            logger.error(f"  ✗ Environment detection failed: {e}")
            self.component_errors["environment"] = str(e)
            return False
    
    async def _check_requirements(self) -> bool:
        """Check minimum system requirements."""
        logger.info("Step 3: Checking system requirements...")
        
        if not self.environment:
            logger.error("  ✗ Environment not detected")
            return False
        
        meets_reqs, issues = self.environment.meets_minimum_requirements()
        if not meets_reqs:
            logger.error("  ✗ System does not meet minimum requirements:")
            for issue in issues:
                logger.error(f"    - {issue}")
            self.component_errors["requirements"] = "; ".join(issues)
            return False
        
        logger.info("  ✓ System meets all requirements")
        self.components_initialized["requirements"] = True
        return True
    
    async def _enable_offline_guard(self) -> bool:
        """Enable offline enforcement."""
        logger.info("Step 4: Enabling offline guard...")
        
        try:
            self.offline_guard.enable()
            
            # Verify offline status
            is_offline, msg = self.offline_guard.verify_offline()
            if not is_offline and self.config.strict_offline:
                logger.error(f"  ✗ {msg}")
                logger.error("  ✗ Cannot start in strict offline mode with active network")
                self.component_errors["offline_guard"] = msg
                return False
            
            logger.info(f"  ✓ Offline guard enabled ({msg})")
            self.components_initialized["offline_guard"] = True
            return True
        except Exception as e:
            logger.error(f"  ✗ Failed to enable offline guard: {e}")
            self.component_errors["offline_guard"] = str(e)
            return False
    
    async def _initialize_subsystems(self) -> bool:
        """Initialize core subsystems."""
        logger.info("Step 5: Initializing subsystems...")
        
        subsystems = [
            "database",
            "policy_engine",
            "memory_system",
            "snapshot_manager",
        ]
        
        for subsystem in subsystems:
            try:
                # In a real implementation, this would call actual initialization
                logger.info(f"  → Initializing {subsystem}...")
                await asyncio.sleep(0.1)  # Simulate initialization
                logger.info(f"  ✓ {subsystem} initialized")
                self.components_initialized[subsystem] = True
            except Exception as e:
                logger.error(f"  ✗ {subsystem} failed: {e}")
                self.component_errors[subsystem] = str(e)
                return False
        
        return True
    
    async def _start_agent_mesh(self) -> bool:
        """Start the agent mesh."""
        logger.info("Step 6: Starting agent mesh...")
        
        try:
            # In a real implementation, this would start the AHM and register agents
            logger.info("  → Starting Adaptive Hybrid Mesh (AHM)...")
            await asyncio.sleep(0.1)
            logger.info("  ✓ AHM started")
            
            logger.info("  → Registering agents...")
            await asyncio.sleep(0.1)
            logger.info("  ✓ Agents registered")
            
            self.components_initialized["agent_mesh"] = True
            return True
        except Exception as e:
            logger.error(f"  ✗ Agent mesh startup failed: {e}")
            self.component_errors["agent_mesh"] = str(e)
            return False
    
    async def _final_verification(self) -> bool:
        """Final verification before going live."""
        logger.info("Step 7: Final verification...")
        
        # Check all critical components initialized
        critical_components = [
            "config",
            "environment",
            "requirements",
            "database",
            "policy_engine",
            "agent_mesh",
        ]
        
        for component in critical_components:
            if not self.components_initialized.get(component, False):
                logger.error(f"  ✗ Critical component not initialized: {component}")
                return False
        
        # Check for any errors
        if self.component_errors:
            logger.error("  ✗ Errors detected during bootstrap:")
            for component, error in self.component_errors.items():
                logger.error(f"    - {component}: {error}")
            return False
        
        logger.info("  ✓ All verifications passed")
        return True
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the system."""
        logger.info("Initiating graceful shutdown...")
        self.state = RuntimeState.SHUTTING_DOWN
        
        try:
            # Disable offline guard
            if self.offline_guard:
                self.offline_guard.disable()
            
            # Stop agent mesh
            logger.info("  → Stopping agent mesh...")
            await asyncio.sleep(0.1)
            
            # Shutdown subsystems in reverse order
            logger.info("  → Shutting down subsystems...")
            await asyncio.sleep(0.1)
            
            self.state = RuntimeState.STOPPED
            logger.info("Shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            self.state = RuntimeState.FAILED
    
    def get_status(self) -> RuntimeStatus:
        """Get current runtime status."""
        uptime = 0.0
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()
        
        violations = []
        if self.offline_guard:
            violations = [
                f"{v.violation_type}: {v.details}"
                for v in self.offline_guard.check_violations()
            ]
        
        return RuntimeStatus(
            state=self.state,
            power_level=self.config.power_level,
            uptime_seconds=uptime,
            environment=self.environment,
            safe_mode_active=self.safe_mode.is_active(),
            offline_guard_active=self.offline_guard._monkey_patched if self.offline_guard else False,
            violations=violations,
            errors=list(self.component_errors.values()),
        )
