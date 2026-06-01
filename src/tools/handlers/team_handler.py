"""Team/subagent tool handlers."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.core.runtime import RuntimeServices
from src.tools.base import ToolResponseMixin, ToolValidationError


class TeamToolHandler(ToolResponseMixin):
    def __init__(self, services: RuntimeServices):
        self.services = services

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "team_spawn": self.handle_team_spawn,
            "team_send": self.handle_team_send,
            "team_inbox": self.handle_team_inbox,
            "team_list": self.handle_team_list,
            "team_shutdown": self.handle_team_shutdown,
        }

    def handle_team_spawn(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        role = self.require_argument(arguments, "role")
        result = self.services.teammate_manager.spawn(
            name=name,
            role=role,
            prompt=arguments.get("prompt"),
            max_rounds=arguments.get("max_rounds", 50),
        )
        return self.success({"message": result})

    def handle_team_send(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        content = self.require_argument(arguments, "content")
        sender = arguments.get("sender", "lead")

        if arguments.get("broadcast", False):
            members = [m["name"] for m in self.services.teammate_manager.list_members()]
            message = self.services.message_bus.broadcast(sender, content, members)
            return self.success({"message": message, "broadcast": True, "recipients": members})

        raw_to = self.require_argument(arguments, "to")
        targets = [t.strip() for t in str(raw_to).split(",") if t.strip()]
        if not targets:
            raise ToolValidationError("to must contain at least one recipient")

        results = [self.services.message_bus.send(sender, target, content) for target in targets]
        return self.success({"message": "\n".join(results), "broadcast": False, "recipients": targets})

    def handle_team_inbox(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        member = arguments.get("member", "lead")
        if arguments.get("count_only", False):
            unread = self.services.message_bus.get_inbox_count(member)
            return self.success({"member": member, "unread": unread})

        inbox = self.services.message_bus.read_inbox(member)
        if isinstance(inbox, str):
            try:
                inbox = json.loads(inbox)
            except json.JSONDecodeError:
                pass
        return self.success(inbox)

    def handle_team_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        members = self.services.teammate_manager.list_members()
        return self.success(members, count=len(members))

    def handle_team_shutdown(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        result = self.services.teammate_manager.shutdown(name)
        return self.success({"message": result})
