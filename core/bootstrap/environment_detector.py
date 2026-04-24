"""
Environment Detection for Aether-One Bootstrap

Detects and validates the system environment before starting Aether-One.
All checks are local and offline-only.
"""

from __future__ import annotations

import os
import platform
import psutil
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class EnvironmentInfo:
    """System environment information."""
    
    # Operating system
    os_type: str  # Linux, Darwin, Windows
    os_version: str
    os_release: str
    
    # Hardware
    cpu_count: int
    cpu_freq_mhz: Optional[float]
    memory_total_gb: float
    memory_available_gb: float
    disk_total_gb: float
    disk_free_gb: float
    
    # Python environment
    python_version: str
    python_executable: str
    
    # Network status
    hostname: str
    network_interfaces: Dict[str, str]
    
    # Aether-One paths
    install_path: Path
    data_path: Path
    config_path: Path
    
    def meets_minimum_requirements(self) -> tuple[bool, list[str]]:
        """
        Check if environment meets minimum requirements.
        
        Returns:
            (meets_requirements, list_of_issues)
        """
        issues = []
        
        # Minimum 4GB RAM
        if self.memory_total_gb < 4.0:
            issues.append(f"Insufficient RAM: {self.memory_total_gb:.1f}GB (minimum 4GB required)")
        
        # Minimum 2GB free disk
        if self.disk_free_gb < 2.0:
            issues.append(f"Insufficient disk space: {self.disk_free_gb:.1f}GB (minimum 2GB required)")
        
        # Minimum 2 CPU cores
        if self.cpu_count < 2:
            issues.append(f"Insufficient CPU cores: {self.cpu_count} (minimum 2 required)")
        
        # Python 3.9+
        major, minor = map(int, self.python_version.split('.')[:2])
        if major < 3 or (major == 3 and minor < 9):
            issues.append(f"Python version too old: {self.python_version} (minimum 3.9 required)")
        
        return len(issues) == 0, issues
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            "os_type": self.os_type,
            "os_version": self.os_version,
            "os_release": self.os_release,
            "cpu_count": self.cpu_count,
            "cpu_freq_mhz": self.cpu_freq_mhz,
            "memory_total_gb": round(self.memory_total_gb, 2),
            "memory_available_gb": round(self.memory_available_gb, 2),
            "disk_total_gb": round(self.disk_total_gb, 2),
            "disk_free_gb": round(self.disk_free_gb, 2),
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "hostname": self.hostname,
            "network_interfaces": self.network_interfaces,
            "install_path": str(self.install_path),
            "data_path": str(self.data_path),
            "config_path": str(self.config_path),
        }


def detect_environment(base_path: Optional[Path] = None) -> EnvironmentInfo:
    """
    Detect and return system environment information.
    
    Args:
        base_path: Base installation path for Aether-One. If None, uses current directory.
    
    Returns:
        EnvironmentInfo with all detected system information.
    """
    if base_path is None:
        base_path = Path.cwd()
    
    # Operating system
    os_type = platform.system()
    os_version = platform.version()
    os_release = platform.release()
    
    # CPU
    cpu_count = psutil.cpu_count(logical=True) or 1
    cpu_freq = psutil.cpu_freq()
    cpu_freq_mhz = cpu_freq.current if cpu_freq else None
    
    # Memory
    memory = psutil.virtual_memory()
    memory_total_gb = memory.total / (1024 ** 3)
    memory_available_gb = memory.available / (1024 ** 3)
    
    # Disk
    disk = psutil.disk_usage(str(base_path))
    disk_total_gb = disk.total / (1024 ** 3)
    disk_free_gb = disk.free / (1024 ** 3)
    
    # Python
    python_version = platform.python_version()
    python_executable = os.sys.executable
    
    # Network (for informational purposes only, not for making connections)
    hostname = socket.gethostname()
    network_interfaces = {}
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                network_interfaces[iface] = addr.address
                break
    
    # Paths
    install_path = base_path
    data_path = base_path / "data"
    config_path = base_path / "config"
    
    # Ensure directories exist
    data_path.mkdir(parents=True, exist_ok=True)
    config_path.mkdir(parents=True, exist_ok=True)
    
    return EnvironmentInfo(
        os_type=os_type,
        os_version=os_version,
        os_release=os_release,
        cpu_count=cpu_count,
        cpu_freq_mhz=cpu_freq_mhz,
        memory_total_gb=memory_total_gb,
        memory_available_gb=memory_available_gb,
        disk_total_gb=disk_total_gb,
        disk_free_gb=disk_free_gb,
        python_version=python_version,
        python_executable=python_executable,
        hostname=hostname,
        network_interfaces=network_interfaces,
        install_path=install_path,
        data_path=data_path,
        config_path=config_path,
    )
