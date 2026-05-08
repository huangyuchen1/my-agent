"""
TaskManager - 持久化任务图（DAG）管理器
参考 s07-task-system 设计：每个任务一个 JSON 文件于 .tasks/ 目录
支持 blockedBy 依赖关系，pending/in_progress/completed 状态机
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class TaskManager:
    """
    磁盘持久化的任务图管理器。

    每个任务存为 storage/.tasks/task_{id}.json，字段：
      id, subject, description, status, blockedBy, createdAt, completedAt

    状态流转：pending -> in_progress -> completed
    依赖解除：任务 completed 时自动将其 ID 从其他任务的 blockedBy 中移除。
    """

    def __init__(self, tasks_dir: str = "storage/.tasks"):
        # 相对于项目根目录
        self.dir = self._resolve(tasks_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._load_next_id()

    def _resolve(self, rel_path: str) -> Path:
        """将相对路径解析为项目根目录下的绝对路径"""
        p = Path(rel_path)
        if p.is_absolute():
            return p
        return Path(__file__).parent.parent.parent / p

    # ------------------------------------------------------------------ #
    #  Core CRUD                                                          #
    # ------------------------------------------------------------------ #

    def create(self, subject: str, description: str = "", blocked_by: List[int] = None) -> str:
        """创建任务"""
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": list(blocked_by) if blocked_by else [],
            "createdAt": datetime.now().isoformat(),
            "completedAt": None,
        }
        self._save(task)
        self._next_id += 1
        self._save_next_id()
        return json.dumps(task, indent=2, ensure_ascii=False)

    def update(
        self,
        task_id: int,
        status: str = None,
        blocked_by: List[int] = None,
        add_blocked_by: List[int] = None,
        remove_blocked_by: List[int] = None,
    ) -> str:
        """更新任务状态或依赖关系"""
        task = self._load(task_id)

        if status:
            task["status"] = status
            if status == "completed":
                task["completedAt"] = datetime.now().isoformat()
                self._clear_dependency(task_id)

        if blocked_by is not None:
            task["blockedBy"] = list(blocked_by)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"] if x not in remove_blocked_by]

        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def list_all(self) -> str:
        """列出所有任务"""
        tasks = []
        for f in sorted(self.dir.glob("task_*.json"), key=lambda x: int(x.stem.split("_")[1])):
            tasks.append(json.loads(f.read_text(encoding="utf-8")))
        return json.dumps(tasks, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        """获取单个任务"""
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    def delete(self, task_id: int) -> str:
        """删除指定任务"""
        path = self._path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task {task_id} not found")
        path.unlink()

        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text(encoding="utf-8"))
            changed = False
            if task_id in task.get("blockedBy", []):
                task["blockedBy"].remove(task_id)
                changed = True
            if changed:
                self._save(task)

        return json.dumps({"deleted": task_id}, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    #  DAG 查询                                                            #
    # ------------------------------------------------------------------ #

    def is_runnable(self, task_id: int) -> bool:
        """任务是否可立即执行：pending 且 blockedBy 为空"""
        try:
            task = self._load(task_id)
            return task["status"] == "pending" and not task["blockedBy"]
        except FileNotFoundError:
            return False

    def get_runnable_tasks(self) -> List[Dict[str, Any]]:
        """返回所有可立即执行的任务列表"""
        return [t for t in self._all_tasks() if t["status"] == "pending" and not t["blockedBy"]]

    def get_blocked_tasks(self) -> List[Dict[str, Any]]:
        """返回所有被阻塞的任务列表"""
        return [t for t in self._all_tasks() if t["status"] == "pending" and t["blockedBy"]]

    def get_in_progress_tasks(self) -> List[Dict[str, Any]]:
        """返回所有进行中的任务"""
        return [t for t in self._all_tasks() if t["status"] == "in_progress"]

    def get_summary(self) -> str:
        """返回人类可读的任务状态摘要"""
        tasks = self._all_tasks()
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        pending = sum(1 for t in tasks if t["status"] == "pending")
        runnable = len(self.get_runnable_tasks())

        lines = [
            f"Total: {total}  |  completed: {completed}  |  in_progress: {in_progress}  |  "
            f"pending: {pending}  |  runnable now: {runnable}"
        ]
        for t in tasks:
            mid = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[t["status"]]
            deps = f" (blocked by {t['blockedBy']})" if t["blockedBy"] else ""
            lines.append(f"  {mid} #{t['id']}: {t['subject']}{deps}")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  私有方法                                                            #
    # ------------------------------------------------------------------ #

    def _path(self, task_id: int) -> Path:
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> Dict[str, Any]:
        path = self._path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task {task_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, task: Dict[str, Any]) -> None:
        path = self._path(task["id"])
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")

    def _all_tasks(self) -> List[Dict[str, Any]]:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json"), key=lambda x: int(x.stem.split("_")[1])):
            tasks.append(json.loads(f.read_text(encoding="utf-8")))
        return tasks

    def _clear_dependency(self, completed_id: int) -> None:
        """将已完成任务 ID 从所有任务的 blockedBy 中移除"""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text(encoding="utf-8"))
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)

    def _load_next_id(self) -> int:
        meta = self.dir / "_meta.json"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            return data.get("next_id", 1)
        return 1

    def _save_next_id(self) -> None:
        meta = self.dir / "_meta.json"
        meta.write_text(json.dumps({"next_id": self._next_id}, indent=2), encoding="utf-8")


# 全局单例
TASKS = TaskManager()
