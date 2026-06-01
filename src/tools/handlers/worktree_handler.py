"""Worktree tool handlers - s12 worktree isolation."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.tools.worktree_manager import WORKTREES


class WorktreeToolHandler:
    """Handler for worktree management tools."""

    def get_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], str]]:
        return {
            "worktree_create": self.handle_worktree_create,
            "worktree_remove": self.handle_worktree_remove,
            "worktree_list": self.handle_worktree_list,
            "worktree_execute": self.handle_worktree_execute,
        }

    def handle_worktree_create(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """创建 worktree 并可选绑定任务"""
        name = arguments.get("name", "")
        task_id = arguments.get("task_id")
        
        if not name:
            return {"error": "name is required"}
        
        try:
            if task_id is not None:
                task_id = int(task_id)
            entry = WORKTREES.create(name, task_id)
            return {
                "success": True,
                "message": f"Worktree '{name}' created",
                "worktree": entry
            }
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}

    def handle_worktree_remove(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """删除 worktree"""
        name = arguments.get("name", "")
        force = arguments.get("force", False)
        complete_task = arguments.get("complete_task", False)
        
        if not name:
            return {"error": "name is required"}
        
        try:
            result = WORKTREES.remove(name, force=force, complete_task=complete_task)
            return {
                "success": True,
                "message": f"Worktree '{name}' removed",
                **result
            }
        except (KeyError, RuntimeError) as e:
            return {"error": str(e)}

    def handle_worktree_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有 worktree"""
        worktrees = WORKTREES.list()
        events = WORKTREES.get_events() if arguments.get("include_events", False) else []
        
        return {
            "success": True,
            "worktrees": worktrees,
            "count": len(worktrees),
            "events": events[-10:] if events else []
        }

    def handle_worktree_execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """在 worktree 中执行命令"""
        name = arguments.get("name", "")
        command = arguments.get("command", "")
        timeout = arguments.get("timeout", 300)
        
        if not name:
            return {"error": "name is required"}
        if not command:
            return {"error": "command is required"}
        
        try:
            result = WORKTREES.execute_in_worktree(name, command, timeout=timeout)
            return {
                "success": True,
                "worktree": name,
                "command": command,
                "returncode": result["returncode"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            }
        except (KeyError, RuntimeError) as e:
            return {"error": str(e)}


# 全局处理器实例
worktree_handler = WorktreeToolHandler()
