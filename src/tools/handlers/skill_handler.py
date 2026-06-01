"""Skill tool handlers."""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.runtime import RuntimeServices
from src.tools.base import ToolResponseMixin


class SkillToolHandler(ToolResponseMixin):
    def __init__(self, services: RuntimeServices):
        self.services = services

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {"load_skill": self.handle_load_skill}

    def handle_load_skill(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = self.require_argument(arguments, "name")
        return self.success(self.services.skill_loader.get_content(name))
