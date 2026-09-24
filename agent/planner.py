"""Structured DAG-based planning engine for Robin.

Provides a formal task decomposition graph with dependency resolution,
state management (pending, ready, in_progress, completed, failed),
cycle detection, and progress visualization.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanTask:
    id: str
    title: str
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result_summary: Optional[str] = None
    verification_criteria: Optional[str] = None
    assigned_toolset: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanTask:
        status_val = data.get("status", "pending")
        try:
            status = TaskStatus(status_val)
        except ValueError:
            status = TaskStatus.PENDING
        return cls(
            id=str(data.get("id", "")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            dependencies=list(data.get("dependencies", [])),
            status=status,
            result_summary=data.get("result_summary"),
            verification_criteria=data.get("verification_criteria"),
            assigned_toolset=data.get("assigned_toolset"),
            metadata=data.get("metadata", {}),
        )


class PlanGraph:
    """Directed Acyclic Graph (DAG) for managing multi-step agent plans."""

    def __init__(self, plan_id: str, title: str = "", description: str = ""):
        self.plan_id = plan_id
        self.title = title
        self.description = description
        self.tasks: Dict[str, PlanTask] = {}
        self._execution_log: List[Dict[str, Any]] = []

    def add_task(
        self,
        task_id: str,
        title: str,
        description: str = "",
        dependencies: Optional[List[str]] = None,
        verification_criteria: Optional[str] = None,
        assigned_toolset: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PlanTask:
        """Add a task node to the DAG."""
        deps = dependencies or []
        task = PlanTask(
            id=task_id,
            title=title,
            description=description,
            dependencies=deps,
            status=TaskStatus.PENDING,
            verification_criteria=verification_criteria,
            assigned_toolset=assigned_toolset,
            metadata=metadata or {},
        )
        self.tasks[task_id] = task
        self._update_ready_states()
        return task

    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate DAG: check that all dependencies exist and there are no cycles."""
        for tid, task in self.tasks.items():
            for dep in task.dependencies:
                if dep not in self.tasks:
                    return False, f"Task '{tid}' depends on non-existent task '{dep}'"

        # Cycle detection via DFS
        visited: Dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited

        def _has_cycle(node_id: str) -> bool:
            visited[node_id] = 1
            for dep in self.tasks[node_id].dependencies:
                if visited.get(dep, 0) == 1:
                    return True
                if visited.get(dep, 0) == 0:
                    if _has_cycle(dep):
                        return True
            visited[node_id] = 2
            return False

        for node_id in self.tasks:
            if visited.get(node_id, 0) == 0:
                if _has_cycle(node_id):
                    return False, "Cycle detected in plan dependencies"

        return True, None

    def _update_ready_states(self) -> None:
        """Update tasks from PENDING to READY when all dependencies are COMPLETED."""
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING:
                all_deps_met = all(
                    self.tasks.get(dep) and self.tasks[dep].status == TaskStatus.COMPLETED
                    for dep in task.dependencies
                )
                if all_deps_met:
                    task.status = TaskStatus.READY

    def get_ready_tasks(self) -> List[PlanTask]:
        """Return all tasks that are ready to execute right now."""
        self._update_ready_states()
        return [t for t in self.tasks.values() if t.status == TaskStatus.READY]

    def mark_in_progress(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.IN_PROGRESS
        return True

    def mark_completed(self, task_id: str, summary: Optional[str] = None) -> bool:
        task = self.tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.COMPLETED
        task.result_summary = summary
        self._update_ready_states()
        return True

    def mark_failed(self, task_id: str, error_msg: Optional[str] = None) -> bool:
        task = self.tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.FAILED
        task.result_summary = f"FAILED: {error_msg}"
        return True

    def is_complete(self) -> bool:
        """True if all tasks are in a terminal state (COMPLETED, FAILED, or SKIPPED)."""
        if not self.tasks:
            return True
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)
            for t in self.tasks.values()
        )

    def is_successful(self) -> bool:
        """True if all tasks are COMPLETED."""
        if not self.tasks:
            return True
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks.values())

    def get_progress_summary(self) -> str:
        """Generate a concise visual progress summary for CLI or gateway rendering."""
        total = len(self.tasks)
        if total == 0:
            return "No tasks in plan."

        completed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        in_progress = sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS)
        failed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED)
        ready = sum(1 for t in self.tasks.values() if t.status == TaskStatus.READY)
        pending = sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING)

        pct = int((completed / total) * 100) if total else 0
        bar_len = 15
        filled = int((completed / total) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        lines = [
            f"**Plan: {self.title or self.plan_id}** [{bar}] {pct}% ({completed}/{total})",
        ]

        status_icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.READY: "🟡",
            TaskStatus.IN_PROGRESS: "▶️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
        }

        for tid, task in self.tasks.items():
            icon = status_icons.get(task.status, "•")
            deps_str = f" (after: {', '.join(task.dependencies)})" if task.dependencies else ""
            line = f"{icon} `{tid}`: {task.title}{deps_str}"
            if task.result_summary and task.status == TaskStatus.COMPLETED:
                line += f" — *{task.result_summary[:60]}*"
            elif task.result_summary and task.status == TaskStatus.FAILED:
                line += f" — ⚠️ *{task.result_summary[:60]}*"
            lines.append(line)

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "description": self.description,
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanGraph:
        graph = cls(
            plan_id=data.get("plan_id", "default"),
            title=data.get("title", ""),
            description=data.get("description", ""),
        )
        for tid, tdata in (data.get("tasks") or {}).items():
            graph.tasks[tid] = PlanTask.from_dict(tdata)
        graph._update_ready_states()
        return graph
