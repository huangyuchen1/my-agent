"""Background task handlers."""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.runtime import RuntimeServices
from src.tools.base import ToolResponseMixin


class BackgroundToolHandler(ToolResponseMixin):
    def __init__(self, services: RuntimeServices):
        self.services = services

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "background_run": self.handle_background_run,
            "background_status": self.handle_background_status,
        }

    def handle_background_run(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        command = self.require_argument(arguments, "command")
        timeout = min(arguments.get("timeout", 300), 600)
        task_id = self.services.background_manager.run(command, timeout=timeout)
        return self.success({"background": True, "task_id": task_id, "command": command})

    def handle_background_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if arguments.get("list_all", False):
            tasks = self.services.background_manager.list_tasks()
            return self.success(tasks, count=len(tasks))
        task_id = arguments.get("task_id")
        if task_id is None:
            return self.error("validation_error", "task_id or list_all is required")
        status = self.services.background_manager.get_status(task_id)
        if status is None:
            return self.error("not_found", f"Task {task_id} not found")
        return self.success(status)
