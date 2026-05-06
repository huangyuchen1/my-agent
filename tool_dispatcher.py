"""
ToolDispatcher - 工具调度层
整合所有工具，提供统一的工具执行入口
"""
import json
from typing import Any, Dict

from tool_definitions import TOOLS_DEFINITION
from todo_manager import TODO
from console_tools import ConsoleTools
from skill_loader import SkillLoader


class ToolDispatcher:
    """工具调度器 - 统一入口执行所有工具"""

    def __init__(self, workspace_path: str = "."):
        self.console_tools = ConsoleTools(workspace_path)
        self.skill_loader = SkillLoader()
        self._handlers = {
            "bash": self.console_tools.bash,
            "read_file": self.console_tools.read_file,
            "write_file": self.console_tools.write_file,
            "list_dir": self.console_tools.list_dir,
            "glob": self.console_tools.glob,
            "get_processes": self.console_tools.get_processes,
            "kill_process": self.console_tools.kill_process,
            "get_system_info": self.console_tools.get_system_info,
            "todo": self._handle_todo,
            "load_skill": self._handle_load_skill,
        }

    def _handle_load_skill(self, arguments: Dict[str, Any]) -> str:
        """处理 Skill 加载工具"""
        name = arguments.get("name", "")
        return self.skill_loader.get_content(name)

    def _handle_todo(self, arguments: Dict[str, Any]) -> str:
        """处理待办事项工具"""
        items = arguments.get("items", [])
        try:
            result = TODO.update(items)
            return json.dumps({
                "success": True,
                "rendered": result
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def run_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具的统一入口

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            JSON 格式的执行结果
        """
        handler = self._handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

        try:
            return handler(arguments)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_all_tools(self) -> list:
        """
        获取所有可用工具定义（包括内置搜索工具）

        Returns:
            合并后的工具列表
        """
        builtin_tools = [{
            "type": "builtin_function",
            "function": {"name": "$web_search"},
        }]
        return builtin_tools + TOOLS_DEFINITION


# 全局单例
dispatcher = ToolDispatcher()
