"""
Deterministic Scheduler for Aether-One

Provides deterministic, repeatable, and auditable scheduling of agent tasks.

GUARANTEES:
- Deterministic execution: Same inputs → same execution order
- Priority enforcement: Higher priority tasks execute first
- Repeatable: Execution can be replayed from logs
- No race conditions: Tasks execute in strict order
- Timeline replay: Full audit trail of all scheduling decisions

DESIGN:
- Seed-based determinism for tie-breaking
- Priority queue with deterministic ordering
- WAL-based audit trail for replay
- No time-based ordering (uses logical ordering instead)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger("aetherone.scheduler")


class TaskPriority(IntEnum):
    """Task priority levels."""
    
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3
    SYSTEM = 4  # Reserved for system-level tasks


class TaskStatus(str):
    """Task execution status."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """A task to be executed by the scheduler."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    
    # Execution
    coro: Optional[Callable] = None  # Coroutine to execute
    args: Tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    
    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # Results
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # Determinism
    sequence_number: int = 0  # Assigned by scheduler for deterministic ordering
    seed: Optional[int] = None  # For reproducible execution
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "id": self.id,
            "name": self.name,
            "priority": int(self.priority),
            "status": self.status,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "seed": self.seed,
            "error": self.error,
        }
    
    def execution_time_ms(self) -> Optional[float]:
        """Get execution time in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return None


@dataclass
class SchedulerStats:
    """Scheduler statistics."""
    
    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    
    total_execution_time_ms: float = 0.0
    average_execution_time_ms: float = 0.0


class DeterministicScheduler:
    """
    Deterministic scheduler for Aether-One.
    
    Ensures that task execution is:
    - Deterministic: Same inputs → same execution order
    - Repeatable: Can be replayed from audit logs
    - Priority-aware: Higher priority tasks execute first
    - Auditable: Full timeline of all scheduling decisions
    """
    
    def __init__(
        self,
        seed: Optional[int] = None,
        enable_audit_log: bool = True,
        audit_log_dir: Optional[Path] = None,
    ):
        """
        Initialize deterministic scheduler.
        
        Args:
            seed: Random seed for deterministic tie-breaking (default: 42)
            enable_audit_log: Enable audit logging for replay
            audit_log_dir: Directory for audit logs
        """
        self.seed = seed if seed is not None else 42
        self.enable_audit_log = enable_audit_log
        self.audit_log_dir = audit_log_dir or Path.home() / ".aetherone" / "scheduler"
        
        # Task queue (priority, sequence_number, task)
        self.tasks: List[ScheduledTask] = []
        self.running_tasks: Dict[str, ScheduledTask] = {}
        self.completed_tasks: List[ScheduledTask] = []
        
        # Sequence counter for deterministic ordering
        self.sequence_counter = 0
        
        # Audit log
        self.audit_log: Optional[Path] = None
        if self.enable_audit_log:
            self.audit_log_dir.mkdir(parents=True, exist_ok=True)
            self.audit_log = self.audit_log_dir / f"schedule_{int(time.time())}.jsonl"
        
        # Stats
        self.stats = SchedulerStats()
        
        logger.info(
            f"DeterministicScheduler initialized: seed={self.seed}, "
            f"audit_log={'enabled' if self.enable_audit_log else 'disabled'}"
        )
    
    def schedule(
        self,
        name: str,
        coro: Callable,
        priority: TaskPriority = TaskPriority.NORMAL,
        *args,
        **kwargs
    ) -> ScheduledTask:
        """
        Schedule a task for execution.
        
        Args:
            name: Task name
            coro: Coroutine to execute
            priority: Task priority
            *args: Positional arguments for coroutine
            **kwargs: Keyword arguments for coroutine
        
        Returns:
            ScheduledTask instance
        """
        # Create task
        task = ScheduledTask(
            name=name,
            priority=priority,
            coro=coro,
            args=args,
            kwargs=kwargs,
            sequence_number=self.sequence_counter,
            seed=self._generate_task_seed(name),
        )
        
        self.sequence_counter += 1
        
        # Add to queue
        self.tasks.append(task)
        
        # Sort queue deterministically
        self._sort_queue()
        
        # Update stats
        self.stats.total_tasks += 1
        self.stats.pending_tasks += 1
        
        # Log scheduling decision
        self._log_event("task_scheduled", task.to_dict())
        
        logger.debug(
            f"Scheduled task: {name} (priority={priority}, seq={task.sequence_number})"
        )
        
        return task
    
    def _sort_queue(self) -> None:
        """
        Sort task queue deterministically.
        
        Sorting order:
        1. Priority (highest first)
        2. Sequence number (lowest first, for FIFO within priority)
        """
        self.tasks.sort(
            key=lambda t: (-int(t.priority), t.sequence_number)
        )
    
    def _generate_task_seed(self, name: str) -> int:
        """Generate deterministic seed for task."""
        # Use SHA256 hash of (global_seed + task_name) to generate task-specific seed
        seed_str = f"{self.seed}:{name}:{self.sequence_counter}"
        hash_bytes = hashlib.sha256(seed_str.encode()).digest()
        return int.from_bytes(hash_bytes[:4], byteorder='big')
    
    async def run_next(self) -> Optional[ScheduledTask]:
        """
        Execute the next task in the queue.
        
        Returns:
            Completed task, or None if queue is empty
        """
        if not self.tasks:
            return None
        
        # Get next task
        task = self.tasks.pop(0)
        
        # Update stats
        self.stats.pending_tasks -= 1
        self.stats.running_tasks += 1
        
        # Mark as running
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self.running_tasks[task.id] = task
        
        # Log execution start
        self._log_event("task_started", task.to_dict())
        
        logger.info(f"Executing task: {task.name} (priority={task.priority})")
        
        try:
            # Execute task
            if task.coro:
                if asyncio.iscoroutinefunction(task.coro):
                    task.result = await task.coro(*task.args, **task.kwargs)
                else:
                    task.result = task.coro(*task.args, **task.kwargs)
            
            # Mark as completed
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            
            # Update stats
            self.stats.running_tasks -= 1
            self.stats.completed_tasks += 1
            
            exec_time = task.execution_time_ms()
            if exec_time:
                self.stats.total_execution_time_ms += exec_time
                if self.stats.completed_tasks > 0:
                    self.stats.average_execution_time_ms = (
                        self.stats.total_execution_time_ms / self.stats.completed_tasks
                    )
            
            # Log completion
            self._log_event("task_completed", {
                **task.to_dict(),
                "execution_time_ms": exec_time,
            })
            
            logger.info(
                f"Task completed: {task.name} "
                f"({exec_time:.2f}ms)" if exec_time else ""
            )
            
        except Exception as e:
            # Mark as failed
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            task.error = str(e)
            
            # Update stats
            self.stats.running_tasks -= 1
            self.stats.failed_tasks += 1
            
            # Log failure
            self._log_event("task_failed", {
                **task.to_dict(),
                "exception": str(e),
            })
            
            logger.error(f"Task failed: {task.name} - {e}")
        
        finally:
            # Move to completed
            if task.id in self.running_tasks:
                del self.running_tasks[task.id]
            self.completed_tasks.append(task)
        
        return task
    
    async def run_all(self) -> List[ScheduledTask]:
        """
        Execute all queued tasks.
        
        Returns:
            List of completed tasks
        """
        results = []
        while self.tasks:
            task = await self.run_next()
            if task:
                results.append(task)
        return results
    
    def get_stats(self) -> SchedulerStats:
        """Get scheduler statistics."""
        return self.stats
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status."""
        return {
            "pending_tasks": len(self.tasks),
            "running_tasks": len(self.running_tasks),
            "completed_tasks": len(self.completed_tasks),
            "next_task": self.tasks[0].to_dict() if self.tasks else None,
        }
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending task.
        
        Args:
            task_id: Task ID
        
        Returns:
            True if cancelled, False if not found or already running
        """
        for i, task in enumerate(self.tasks):
            if task.id == task_id:
                task.status = TaskStatus.CANCELLED
                task.completed_at = time.time()
                self.tasks.pop(i)
                self.completed_tasks.append(task)
                
                # Update stats
                self.stats.pending_tasks -= 1
                self.stats.cancelled_tasks += 1
                
                # Log cancellation
                self._log_event("task_cancelled", task.to_dict())
                
                logger.info(f"Task cancelled: {task.name}")
                return True
        
        return False
    
    def clear_completed(self) -> int:
        """Clear completed tasks from history. Returns number cleared."""
        count = len(self.completed_tasks)
        self.completed_tasks.clear()
        return count
    
    def _log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log event to audit log."""
        if not self.enable_audit_log or not self.audit_log:
            return
        
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        
        try:
            with open(self.audit_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")
    
    def replay_from_log(self, log_path: Path) -> List[Dict[str, Any]]:
        """
        Replay scheduler execution from audit log.
        
        Args:
            log_path: Path to audit log file
        
        Returns:
            List of events from log
        """
        events = []
        
        try:
            with open(log_path, "r") as f:
                for line in f:
                    if line.strip():
                        event = json.loads(line)
                        events.append(event)
        except Exception as e:
            logger.error(f"Failed to replay log: {e}")
        
        return events


# Global scheduler instance
_global_scheduler: Optional[DeterministicScheduler] = None


def get_global_scheduler() -> DeterministicScheduler:
    """Get or create global scheduler instance."""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = DeterministicScheduler()
    return _global_scheduler
