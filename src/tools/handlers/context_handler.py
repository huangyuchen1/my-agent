"""Context/runtime command handlers."""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.context.compactor import get_context_stats
from src.tools.base import ToolResponseMixin


class ContextToolHandler(ToolResponseMixin):
    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "compact": self.handle_compact,
            "context_stats": self.handle_context_stats,
        }

    def handle_compact(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.success(
            {
                "ready": True,
                "instruction": arguments.get("instruction"),
                "message": "compact tool called; agent loop should execute the actual compression",
            }
        )

    def handle_context_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if "context" not in arguments:
            return self.error("invalid_context", "context_stats must be called with runtime context")
        return self.success(get_context_stats(arguments["context"]))
