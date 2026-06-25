"""
Real-time local filesystem watcher for DCSP.
Monitors project directories and triggers the repair/intelligence pipeline on changes.
"""

import os
import threading
import logging
from pathlib import Path
from typing import Optional, List, Callable

try:
    from watchfiles import watch, Change
    HAS_WATCHFILES = True
except ImportError:
    HAS_WATCHFILES = False
    logger.warning("watchfiles dependency missing. Local monitoring will be disabled.")

logger = logging.getLogger(__name__)

class LocalProjectWatcher:
    """Watches local directories for code changes and triggers processing."""

    def __init__(self, on_change_callback: Optional[Callable] = None):
        self.monitored_paths: List[str] = []
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self.on_change_callback = on_change_callback

    def add_path(self, path: str):
        """Adds a path to the monitoring list and starts a watcher thread."""
        if not HAS_WATCHFILES:
            logger.error("Cannot add path: watchfiles dependency is missing.")
            return False
            
        absolute_path = os.path.abspath(path)
        if not os.path.exists(absolute_path):
            logger.error(f"Path does not exist: {absolute_path}")
            return False
        
        if absolute_path in self.monitored_paths:
            return True

        self.monitored_paths.append(absolute_path)
        thread = threading.Thread(
            target=self._watch_loop, 
            args=(absolute_path,),
            daemon=True
        )
        thread.start()
        self._threads.append(thread)
        logger.info(f"Started monitoring local path: {absolute_path}")
        return True

    def _watch_loop(self, path: str):
        """Internal loop using watchfiles to monitor changes."""
        logger.info(f"Watcher loop started for {path}")
        try:
            for changes in watch(path, stop_event=self._stop_event):
                for change_type, file_path in changes:
                    # Ignore non-code files and hidden directories
                    if any(part.startswith('.') for part in Path(file_path).parts):
                        continue
                    
                    ext = Path(file_path).suffix.lower()
                    if ext not in ['.py', '.js', '.jsx', '.ts', '.tsx', '.java']:
                        continue

                    logger.info(f"Detected {change_type.name} in {file_path}")
                    
                    if self.on_change_callback:
                        self.on_change_callback(change_type, file_path, path)
        except Exception as e:
            logger.error(f"Error in watcher loop for {path}: {e}")

    def stop(self):
        """Stops all watcher threads."""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=2)
        self.monitored_paths.clear()
        self._threads.clear()

# Global instance
PROJECT_WATCHER = LocalProjectWatcher()
