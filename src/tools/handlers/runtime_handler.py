"""Runtime and cross-cutting tool handlers."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.context.compactor import get_context_stats
from src.core.background_manager import BG
from src.core.skill_loader import SkillLoader
from src.subagent.message_bus import BUS
from src.subagent.teammate_manager import TM
from src.tools.base import ToolResponseMixin


class RuntimeToolHandler(ToolResponseMixin):
    def __init__(self):
        self.skill_loader = SkillLoader()

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "load_skill": self.handle_load_skill,
            "compact": self.handle_compact,
            "context_stats": self.handle_context_stats,
            "background_run": self.handle_background_run,
            "background_status": self.handle_background_status,
            "team_spawn": self.handle_team_spawn,
            "team_send": self.handle_team_send,
            "team_inbox": self.handle_team_inbox,
            "team_list": self.handle_team_list,
            "team_shutdown": self.handle_team_shutdown,
        }

    def handle_load_skill(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        return self.success(self.skill_loader.get_content(name))

    def handle_compact(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.success({"ready": True, "instruction": arguments.get("instruction")})

    def handle_context_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if "context" not in arguments:
            return self.error("invalid_context", "context_stats must be called with runtime context")
        return self.success(get_context_stats(arguments["context"]))

    def handle_background_run(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        command = self.require_argument(arguments, "command")
        timeout = min(arguments.get("timeout", 300), 600)
        task_id = BG.run(command, timeout=timeout)
        return self.success({"background": True, "task_id": task_id, "command": command})

    def handle_background_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if arguments.get("list_all", False):
            tasks = BG.list_tasks()
            return self.success(tasks, count=len(tasks))
        task_id = arguments.get("task_id")
        if task_id is None:
            return self.error("validation_error", "task_id or list_all is required")
        status = BG.get_status(task_id)
        if status is None:
            return self.error("not_found", f"Task {task_id} not found")
        return self.success(status)

    def handle_team_spawn(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        role = self.require_argument(arguments, "role")
        result = TM.spawn(name=name, role=role, prompt=arguments.get("prompt"), max_rounds=arguments.get("max_rounds", 50))
        return self.success({"message": result})

    def handle_team_send(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        content = self.require_argument(arguments, "content")
        sender = arguments.get("sender", "lead")
        if arguments.get("broadcast", False):
            members = [m["name"] for m in TM.list_members()]
            return self.success({"message": BUS.broadcast(sender, content, members), "broadcast": True, "recipients": members})
        targets = [t.strip() for t in str(self.require_argument(arguments, "to")).split(",") if t.strip()]
        return self.success({"message": "\n".join(BUS.send(sender, target, content) for target in targets), "broadcast": False, "recipients": targets})

    def handle_team_inbox(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        member = arguments.get("member", "lead")
        if arguments.get("count_only", False):
            return self.success({"member": member, "unread": BUS.get_inbox_count(member)})
        inbox = BUS.read_inbox(member)
        if isinstance(inbox, str):
            try:
                inbox = json.loads(inbox)
            except json.JSONDecodeError:
                pass
        return self.success(inbox)

    def handle_team_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        members = TM.list_members()
        return self.success(members, count=len(members))

    def handle_team_shutdown(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        return self.success({"message": TM.shutdown(name)})
