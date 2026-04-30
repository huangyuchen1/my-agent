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
from typing import Any, Dict


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

            processes.sort(key=lambda x: x["cpu"], reverse=True)
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

            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
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
