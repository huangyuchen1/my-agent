"""Task tool handlers."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.core.runtime import RuntimeServices
from src.tools.base import ToolResponseMixin


class TaskToolHandler(ToolResponseMixin):
    def __init__(self, services: RuntimeServices):
        self.services = services

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "task_create": self.handle_create,
            "task_update": self.handle_update,
            "task_list": self.handle_list,
            "task_get": self.handle_get,
        }

    def handle_create(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        subject = self.require_argument(arguments, "subject")
        description = arguments.get("description", "")
        blocked_by = arguments.get("blocked_by")
        return self.success(json.loads(self.services.task_manager.create(subject, description, blocked_by)))

    def handle_update(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        task_id = self.require_argument(arguments, "task_id")
        return self.success(
            json.loads(
                self.services.task_manager.update(
                    task_id,
                    status=arguments.get("status"),
                    blocked_by=arguments.get("blocked_by"),
                    add_blocked_by=arguments.get("add_blocked_by"),
                    remove_blocked_by=arguments.get("remove_blocked_by"),
                )
            )
        )

    def handle_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.success(
            json.loads(self.services.task_manager.list_all()),
            summary=self.services.task_manager.get_summary(),
        )

    def handle_get(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        task_id = self.require_argument(arguments, "task_id")
        return self.success(json.loads(self.services.task_manager.get(task_id)))
