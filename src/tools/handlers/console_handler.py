"""Console tool handlers."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.tools.base import ToolResponseMixin
from src.tools.console import ConsoleTools


class ConsoleToolHandler(ToolResponseMixin):
    TOOL_NAMES = {
        "bash",
        "read_file",
        "write_file",
        "list_dir",
        "glob",
        "get_processes",
        "kill_process",
        "get_system_info",
    }

    def __init__(self, workspace_path: str = "."):
        self.console_tools = ConsoleTools(workspace_path)

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {name: self._wrap(getattr(self.console_tools, name)) for name in self.TOOL_NAMES}

    def _wrap(self, fn: Callable[..., Any]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        def handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            result = fn(arguments)
            if isinstance(result, str):
                try:
                    return self.success(json.loads(result))
                except json.JSONDecodeError:
                    return self.success(result)
            return self.success(result)

        return handler
