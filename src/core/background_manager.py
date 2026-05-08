"""
BackgroundManager - 后台任务核心引擎
基于守护线程实现，参考 s08-background-tasks 设计
"""
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional


class BackgroundManager:
    """
    线程安全的后台任务管理器。
    使用 daemon thread 执行命令，完成后结果进入 notification queue，
    由 agent_loop 每次 LLM 调用前排空并注入消息。
    """

    _instance: Optional["BackgroundManager"] = None
    _lock_for_singleton = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock_for_singleton:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.tasks: Dict[str, dict] = {}
        self._notification_queue: List[dict] = []
        self._queue_lock = threading.Lock()
        self._tasks_lock = threading.Lock()
        self._initialized = True

    def run(self, command: str, timeout: int = 300) -> str:
        """
        启动后台任务，立即返回 task_id。
        实际执行在工作线程中进行，完成后结果进入通知队列。
        """
        task_id = str(uuid.uuid4())[:8]

        with self._tasks_lock:
            self.tasks[task_id] = {
                "status": "running",
                "command": command,
                "started_at": time.time(),
                "result": None,
                "stdout": "",
                "stderr": "",
                "returncode": None,
                "error": None,
                "completed_at": None,
            }

        thread = threading.Thread(
            target=self._execute,
            args=(task_id, command, timeout),
            daemon=True,
            name=f"bg-{task_id}",
        )
        thread.start()
        return task_id

    def _execute(self, task_id: str, command: str, timeout: int):
        """在工作线程中执行命令，完成后将结果写入通知队列"""
        try:
            result = self._run_command(command, timeout)
            output = (result.get("stdout", "") + result.get("stderr", "")).strip()
            output = output[:50000]
            returncode = result.get("returncode", -1)
        except subprocess.TimeoutExpired:
            output = f"Error: Timeout after {timeout} seconds"
            returncode = -1
        except Exception as e:
            output = f"Exception: {e}"
            returncode = -1

        with self._tasks_lock:
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["result"] = output
            self.tasks[task_id]["returncode"] = returncode
            self.tasks[task_id]["completed_at"] = time.time()

        with self._queue_lock:
            self._notification_queue.append({
                "task_id": task_id,
                "status": "completed",
                "command": command,
                "result": output[:500],
                "full_result": output,
                "returncode": returncode,
            })

    def _run_command(self, command: str, timeout: int) -> dict:
        """底层 subprocess 调用"""
        if sys.platform == "win32":
            shell = ["powershell", "-Command", command]
        else:
            shell = ["/bin/bash", "-c", command]

        r = subprocess.run(
            shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}

    def get_status(self, task_id: str) -> Optional[dict]:
        """查询指定任务的状态"""
        with self._tasks_lock:
            task = self.tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task_id,
                "status": task["status"],
                "command": task["command"],
                "result": task["result"],
                "returncode": task["returncode"],
                "error": task["error"],
                "started_at": task["started_at"],
                "completed_at": task["completed_at"],
                "duration": (
                    (task["completed_at"] - task["started_at"])
                    if task["completed_at"]
                    else time.time() - task["started_at"]
                ),
            }

    def list_tasks(self) -> List[dict]:
        """列出所有任务状态"""
        with self._tasks_lock:
            return [
                {
                    "task_id": tid,
                    "status": t["status"],
                    "command": t["command"],
                    "returncode": t["returncode"],
                    "started_at": t["started_at"],
                    "completed_at": t["completed_at"],
                    "duration": (
                        (t["completed_at"] - t["started_at"])
                        if t["completed_at"]
                        else time.time() - t["started_at"]
                    ),
                }
                for tid, t in self.tasks.items()
            ]

    def drain_notifications(self) -> List[dict]:
        """
        排空通知队列。
        由 agent_loop 每次 LLM 调用前调用。
        """
        with self._queue_lock:
            notifications = list(self._notification_queue)
            self._notification_queue.clear()
            return notifications

    def cancel_task(self, task_id: str) -> bool:
        """尝试取消正在运行的任务（通过终止其子进程）"""
        with self._tasks_lock:
            task = self.tasks.get(task_id)
            if task is None or task["status"] != "running":
                return False
            task["status"] = "cancelled"
            task["result"] = "Cancelled by user"
            task["completed_at"] = time.time()
        return True


# 全局单例
BG = BackgroundManager()
