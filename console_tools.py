"""
ConsoleTools - 控制台操作工具集
提供文件操作、命令执行、进程管理等系统功能
"""
import os
import sys
import subprocess
import glob
import psutil
import json
from typing import *
from pathlib import Path


class TodoManager:
    """待办事项管理器"""

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """更新待办事项列表"""
        if len(items) > 20:
            raise ValueError("Max 20 todos allow")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        """渲染待办事项和状态给用户看"""
        if not self.items:
            return "No todos"
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


class ConsoleTools:
    """控制台工具类，提供系统操作能力"""

    def __init__(self, workspace_path: str = "."):
        """
        初始化控制台工具

        Args:
            workspace_path: 工作区路径，限制文件操作范围
        """
        self.workspace_path = os.path.abspath(workspace_path)
        self.platform = sys.platform  # win32, darwin, linux

    def _safe_path(self, file_path: str) -> str:
        """
        路径沙箱：确保路径在工作区内，防止越界访问。

        Args:
            file_path: 相对或绝对路径

        Returns:
            标准化后的绝对路径

        Raises:
            ValueError: 路径超出工作区时抛出
        """
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(self.workspace_path):
            raise ValueError(f"Access denied: path outside workspace ({self.workspace_path})")
        return abs_path

    def _run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        执行 shell 命令的内部方法

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            包含执行结果的字典
        """
        try:
            # 根据平台选择 shell
            if self.platform == "win32":
                shell = ["powershell", "-Command", command]
            else:
                shell = ["/bin/bash", "-c", command]

            result = subprocess.run(
                shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace"
            )

            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"命令执行超时（{timeout}秒）",
                "stdout": "",
                "stderr": f"Timeout after {timeout} seconds",
                "returncode": -1
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "returncode": -1
            }

    def bash(self, arguments: Dict[str, Any]) -> str:
        """
        执行 Shell 命令

        Args:
            arguments: 包含 command 参数的字典

        Returns:
            JSON 格式的执行结果
        """
        command = arguments.get("command", "")
        if not command:
            return json.dumps({"error": "No command provided"}, ensure_ascii=False)

        result = self._run_command(command)

        # 格式化输出
        output = []
        if result["stdout"]:
            output.append(result["stdout"])
        if result["stderr"] and result["returncode"] != 0:
            output.append(f"[stderr] {result['stderr']}")

        if not output:
            output = [f"[completed with exit code {result['returncode']}]"]

        return json.dumps({
            "command": command,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "returncode": result["returncode"],
            "summary": "\n".join(output) if output else "Command executed successfully"
        }, ensure_ascii=False)

    def read_file(self, arguments: Dict[str, Any]) -> str:
        """
        读取文件内容

        Args:
            arguments: 包含 path 参数的字典

        Returns:
            JSON 格式的文件内容
        """
        file_path = arguments.get("path", "")
        if not file_path:
            return json.dumps({"error": "No file path provided"}, ensure_ascii=False)

        try:
            abs_path = self._safe_path(file_path)

            if not os.path.exists(abs_path):
                return json.dumps({"error": f"File not found: {file_path}"}, ensure_ascii=False)

            if not os.path.isfile(abs_path):
                return json.dumps({"error": f"Not a file: {file_path}"}, ensure_ascii=False)

            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # 限制文件大小（最大 1MB）
            if len(content) > 1024 * 1024:
                content = content[:1024 * 1024] + "\n[... 文件过大，已截断 ...]"

            return json.dumps({
                "path": abs_path,
                "content": content,
                "size": len(content),
                "success": True
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def write_file(self, arguments: Dict[str, Any]) -> str:
        """
        写入文件内容

        Args:
            arguments: 包含 path 和 content 参数的字典

        Returns:
            JSON 格式的操作结果
        """
        file_path = arguments.get("path", "")
        content = arguments.get("content", "")

        if not file_path:
            return json.dumps({"error": "No file path provided"}, ensure_ascii=False)

        try:
            abs_path = self._safe_path(file_path)

            # 确保目录存在
            parent_dir = os.path.dirname(abs_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)

            return json.dumps({
                "path": abs_path,
                "bytes_written": len(content.encode("utf-8")),
                "success": True,
                "message": f"Successfully wrote {len(content)} characters"
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def list_dir(self, arguments: Dict[str, Any]) -> str:
        """
        列出目录内容

        Args:
            arguments: 包含 path 参数的字典

        Returns:
            JSON 格式的目录列表
        """
        dir_path = arguments.get("path", ".") or "."

        try:
            abs_path = self._safe_path(dir_path)

            if not os.path.exists(abs_path):
                return json.dumps({"error": f"Path not found: {dir_path}"}, ensure_ascii=False)

            if not os.path.isdir(abs_path):
                return json.dumps({"error": f"Not a directory: {dir_path}"}, ensure_ascii=False)

            items = []
            for item in os.listdir(abs_path):
                item_path = os.path.join(abs_path, item)
                try:
                    stat = os.stat(item_path)
                    items.append({
                        "name": item,
                        "type": "directory" if os.path.isdir(item_path) else "file",
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
                except:
                    items.append({
                        "name": item,
                        "type": "unknown",
                        "size": 0,
                        "modified": 0
                    })

            # 按类型（目录在前）和名称排序
            items.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))

            return json.dumps({
                "path": abs_path,
                "items": items,
                "count": len(items),
                "success": True
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def glob(self, arguments: Dict[str, Any]) -> str:
        """
        搜索匹配的文件

        Args:
            arguments: 包含 pattern 和 base_dir 参数的字典

        Returns:
            JSON 格式的匹配结果
        """
        pattern = arguments.get("pattern", "*")
        base_dir = arguments.get("base_dir", self.workspace_path) or self.workspace_path

        try:
            abs_base = self._safe_path(base_dir)
            full_pattern = os.path.join(abs_base, pattern)

            matches = glob.glob(full_pattern, recursive=True)
            # 限制返回数量
            max_results = 100
            matches = matches[:max_results]

            return json.dumps({
                "pattern": pattern,
                "base_dir": abs_base,
                "matches": matches,
                "count": len(matches),
                "truncated": len(matches) >= max_results,
                "success": True
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_processes(self, arguments: Dict[str, Any]) -> str:
        """
        获取运行中的进程列表

        Args:
            arguments: 可选包含 filter 参数的字典

        Returns:
            JSON 格式的进程列表
        """
        filter_name = arguments.get("filter", "")

        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'cmdline']):
                try:
                    info = proc.info
                    # 如果有过滤条件，则匹配进程名
                    if filter_name and filter_name.lower() not in info['name'].lower():
                        continue

                    processes.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu": round(info['cpu_percent'], 1),
                        "memory": round(info['memory_percent'], 2),
                        "cmdline": " ".join(info['cmdline']) if info['cmdline'] else ""
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # 按 CPU 使用率排序
            processes.sort(key=lambda x: x["cpu"], reverse=True)

            # 限制返回数量
            max_results = 50
            processes = processes[:max_results]

            return json.dumps({
                "processes": processes,
                "count": len(processes),
                "success": True
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def kill_process(self, arguments: Dict[str, Any]) -> str:
        """
        终止指定进程

        Args:
            arguments: 包含 pid 参数的字典

        Returns:
            JSON 格式的操作结果
        """
        pid = arguments.get("pid")
        if pid is None:
            return json.dumps({"error": "No pid provided"}, ensure_ascii=False)

        try:
            pid = int(pid)
            process = psutil.Process(pid)
            name = process.name()

            # 优雅终止
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                # 强制终止
                process.kill()

            return json.dumps({
                "pid": pid,
                "name": name,
                "success": True,
                "message": f"Process {pid} ({name}) terminated"
            }, ensure_ascii=False)

        except psutil.NoSuchProcess:
            return json.dumps({"error": f"Process {pid} not found"}, ensure_ascii=False)
        except psutil.AccessDenied:
            return json.dumps({"error": f"Access denied to process {pid}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def todo(self, arguments: Dict[str, Any]) -> str:
        """
        更新待办事项列表

        Args:
            arguments: 包含 items 参数的字典，每项包含 id, text, status

        Returns:
            JSON 格式的渲染结果
        """
        items = arguments.get("items", [])
        try:
            result = TODO.update(items)
            return json.dumps({
                "success": True,
                "rendered": result
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_system_info(self, arguments: Dict[str, Any]) -> str:
        """
        获取系统信息

        Args:
            arguments: 空字典

        Returns:
            JSON 格式的系统信息
        """
        try:
            cpu_count = psutil.cpu_count(logical=True)
            cpu_physical = psutil.cpu_count(logical=False)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            info = {
                "platform": sys.platform,
                "python_version": sys.version,
                "cpu": {
                    "logical": cpu_count,
                    "physical": cpu_physical,
                    "current_percent": psutil.cpu_percent(interval=0.1)
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                }
            }

            return json.dumps(info, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


# 导出所有工具定义，用于注册到 AI Agent
TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "更新待办事项列表。用于管理多步骤任务的状态，包括 pending（待处理）、in_progress（进行中）、completed（已完成）。每次更新会渲染当前所有事项的状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "待办事项列表，每项包含 id（标识）、text（描述）、status（状态 pending/in_progress/completed）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "事项唯一标识"},
                                "text": {"type": "string", "description": "事项描述"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "事项状态"}
                            },
                            "required": ["text", "status"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 Shell/PowerShell 命令。用于运行系统命令、程序、脚本等。返回命令的 stdout、stderr 和退出码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令（PowerShell on Windows, Bash on Mac/Linux）"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容。用于查看文本文件、代码文件、配置文件等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径或相对路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入或创建文件。用于创建新文件或覆盖现有文件内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径或相对路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录内容。显示指定目录下的所有文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录的绝对路径或相对路径，默认为当前目录"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "搜索匹配的文件模式。支持通配符 *、** 等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "搜索模式，如 *.py、**/*.js、src/**/*.ts"
                    },
                    "base_dir": {
                        "type": "string",
                        "description": "搜索的基础目录，默认为工作区目录"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_processes",
            "description": "获取当前运行的进程列表。可选过滤条件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "可选的进程名过滤关键词"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "终止指定进程。使用前请确认进程 ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "要终止的进程 ID"
                    }
                },
                "required": ["pid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取系统信息，包括 CPU、内存、磁盘使用情况。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# 工具分发注册表：工具名 -> 方法名
TOOL_HANDLERS = {
    "bash":           "bash",
    "read_file":      "read_file",
    "write_file":     "write_file",
    "list_dir":       "list_dir",
    "glob":           "glob",
    "get_processes":  "get_processes",
    "kill_process":   "kill_process",
    "get_system_info": "get_system_info",
    "todo":           "todo",
}

