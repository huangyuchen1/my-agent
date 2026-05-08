"""
ToolDispatcher - 工具调度层
整合所有工具，提供统一的工具执行入口
"""
import json
from typing import Any, Dict

from src.tools.definitions import TOOLS_DEFINITION
from src.tools.task_manager import TASKS
from src.tools.console import ConsoleTools
from src.core.skill_loader import SkillLoader
from src.context.compactor import (
    check_and_compact,
    manual_compact,
    get_context_stats,
    estimate_tokens,
    AUTO_COMPACT_TOKEN_THRESHOLD,
)


class ToolDispatcher:
    """工具调度器 - 统一入口执行所有工具"""

    def __init__(self, workspace_path: str = "."):
        self.console_tools = ConsoleTools(workspace_path)
        self.skill_loader = SkillLoader()
        self._compact_client = None  # LLM client for summarization, set via set_compact_client
        self._handlers = {
            "bash": self.console_tools.bash,
            "read_file": self.console_tools.read_file,
            "write_file": self.console_tools.write_file,
            "list_dir": self.console_tools.list_dir,
            "glob": self.console_tools.glob,
            "get_processes": self.console_tools.get_processes,
            "kill_process": self.console_tools.kill_process,
            "get_system_info": self.console_tools.get_system_info,
            "load_skill": self._handle_load_skill,
            "compact": self._handle_compact,
            "context_stats": self._handle_context_stats,
            "task_create": self._handle_task_create,
            "task_update": self._handle_task_update,
            "task_list": self._handle_task_list,
            "task_get": self._handle_task_get,
        }

    def set_compact_client(self, client) -> None:
        """设置用于摘要生成的 LLM client"""
        self._compact_client = client

    def _handle_load_skill(self, arguments: Dict[str, Any]) -> str:
        """处理 Skill 加载工具"""
        name = arguments.get("name", "")
        return self.skill_loader.get_content(name)

    def _handle_task_create(self, arguments: Dict[str, Any]) -> str:
        """处理 task_create 工具"""
        subject = arguments.get("subject", "")
        description = arguments.get("description", "")
        blocked_by = arguments.get("blocked_by")
        try:
            result = TASKS.create(subject, description, blocked_by)
            return json.dumps({"success": True, "task": json.loads(result)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _handle_task_update(self, arguments: Dict[str, Any]) -> str:
        """处理 task_update 工具"""
        task_id = arguments.get("task_id")
        if task_id is None:
            return json.dumps({"error": "task_id is required"}, ensure_ascii=False)
        try:
            result = TASKS.update(
                task_id,
                status=arguments.get("status"),
                blocked_by=arguments.get("blocked_by"),
                add_blocked_by=arguments.get("add_blocked_by"),
                remove_blocked_by=arguments.get("remove_blocked_by"),
            )
            return json.dumps({"success": True, "task": json.loads(result)}, ensure_ascii=False)
        except FileNotFoundError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _handle_task_list(self, arguments: Dict[str, Any]) -> str:
        """处理 task_list 工具"""
        try:
            result = TASKS.list_all()
            summary = TASKS.get_summary()
            return json.dumps({"success": True, "tasks": json.loads(result), "summary": summary}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _handle_task_get(self, arguments: Dict[str, Any]) -> str:
        """处理 task_get 工具"""
        task_id = arguments.get("task_id")
        if task_id is None:
            return json.dumps({"error": "task_id is required"}, ensure_ascii=False)
        try:
            result = TASKS.get(task_id)
            return json.dumps({"success": True, "task": json.loads(result)}, ensure_ascii=False)
        except FileNotFoundError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _handle_compact(self, arguments: Dict[str, Any]) -> str:
        """处理手动压缩工具 - 返回压缩结果信息，实际压缩在 agent_loop 中执行"""
        instruction = arguments.get("instruction", None)
        return json.dumps({
            "ready": True,
            "instruction": instruction,
            "message": "compact tool called — agent_loop will execute the actual compression",
        }, ensure_ascii=False)

    def _handle_context_stats(self, arguments: Dict[str, Any]) -> str:
        """处理上下文统计工具"""
        return json.dumps({"error": "context_stats must be called from agent context"}, ensure_ascii=False)

    def run_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行工具的统一入口"""
        handler = self._handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

        try:
            return handler(arguments)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_all_tools(self) -> list:
        """获取所有可用工具定义（包括内置搜索工具）"""
        builtin_tools = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
        return builtin_tools + TOOLS_DEFINITION


# 全局单例
dispatcher = ToolDispatcher()
