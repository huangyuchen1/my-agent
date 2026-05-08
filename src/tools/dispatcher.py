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
from src.core.config import get_current_model_config
from src.core.background_manager import BG
from src.subagent.message_bus import BUS
from src.subagent.teammate_manager import TM
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
            "background_run": self._handle_background_run,
            "background_status": self._handle_background_status,
            "team_spawn": self._handle_team_spawn,
            "team_send": self._handle_team_send,
            "team_inbox": self._handle_team_inbox,
            "team_list": self._handle_team_list,
            "team_shutdown": self._handle_team_shutdown,
        }

    def set_compact_client(self, client) -> None:
        """设置用于摘要生成的 LLM client"""
        self._compact_client = client

    def _handle_background_run(self, arguments: Dict[str, Any]) -> str:
        """处理 background_run 工具 - 启动后台命令"""
        command = arguments.get("command", "")
        if not command:
            return json.dumps({"error": "No command provided"}, ensure_ascii=False)
        timeout = arguments.get("timeout", 300)
        timeout = min(timeout, 600)
        task_id = BG.run(command, timeout=timeout)
        return json.dumps({
            "background": True,
            "task_id": task_id,
            "command": command,
            "message": f"后台任务已启动，task_id={task_id}。完成后结果会自动注入。"
        }, ensure_ascii=False)

    def _handle_background_status(self, arguments: Dict[str, Any]) -> str:
        """处理 background_status 工具 - 查询后台任务状态"""
        list_all = arguments.get("list_all", False)
        task_id = arguments.get("task_id", None)

        if list_all:
            tasks = BG.list_tasks()
            return json.dumps({
                "success": True,
                "tasks": tasks,
                "count": len(tasks)
            }, ensure_ascii=False)

        if task_id:
            status = BG.get_status(task_id)
            if status is None:
                return json.dumps({"error": f"Task {task_id} not found"}, ensure_ascii=False)
            return json.dumps({"success": True, "task": status}, ensure_ascii=False)

        return json.dumps({"error": "task_id or list_all is required"}, ensure_ascii=False)

    def _handle_team_spawn(self, arguments: Dict[str, Any]) -> str:
        """处理 team_spawn 工具 - 创建持久化队友"""
        name = arguments.get("name", "")
        role = arguments.get("role", "")
        if not name or not role:
            return json.dumps({"error": "name and role are required"}, ensure_ascii=False)
        prompt = arguments.get("prompt")
        max_rounds = arguments.get("max_rounds", 50)
        result = TM.spawn(name=name, role=role, prompt=prompt, max_rounds=max_rounds)
        return json.dumps({"success": True, "message": result})

    def _handle_team_send(self, arguments: Dict[str, Any]) -> str:
        """处理 team_send 工具 - 向队友发送消息"""
        to = arguments.get("to", "")
        content = arguments.get("content", "")
        broadcast = arguments.get("broadcast", False)
        if not content:
            return json.dumps({"error": "content is required"}, ensure_ascii=False)
        if broadcast:
            members = [m["name"] for m in TM.list_members()]
            result = BUS.broadcast("lead", content, members)
        elif to:
            targets = [t.strip() for t in to.split(",")]
            results = []
            for target in targets:
                if target:
                    results.append(BUS.send("lead", target, content))
            result = "\n".join(results) if results else "No recipients specified"
        else:
            result = "No recipients specified"
        return json.dumps({"success": True, "message": result})

    def _handle_team_inbox(self, arguments: Dict[str, Any]) -> str:
        """处理 team_inbox 工具 - 读取收件箱"""
        member = arguments.get("member", "lead")
        count_only = arguments.get("count_only", False)
        if count_only:
            count = BUS.get_inbox_count(member)
            return json.dumps({"member": member, "unread": count})
        inbox = BUS.read_inbox(member)
        return inbox

    def _handle_team_list(self, arguments: Dict[str, Any]) -> str:
        """处理 team_list 工具 - 列出所有队友"""
        members = TM.list_members()
        return json.dumps({"members": members, "count": len(members)}, ensure_ascii=False)

    def _handle_team_shutdown(self, arguments: Dict[str, Any]) -> str:
        """处理 team_shutdown 工具 - 关闭队友"""
        name = arguments.get("name", "")
        if not name:
            return json.dumps({"error": "name is required"}, ensure_ascii=False)
        result = TM.shutdown(name)
        return json.dumps({"success": True, "message": result})

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
        """获取所有可用工具定义（根据当前模型配置决定是否包含联网搜索工具）"""
        tools = list(TOOLS_DEFINITION)
        if get_current_model_config().enable_web_search:
            tools.insert(0, {"type": "builtin_function", "function": {"name": "$web_search"}})
        return tools


# 全局单例
dispatcher = ToolDispatcher()
