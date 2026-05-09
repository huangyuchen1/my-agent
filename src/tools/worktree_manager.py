"""
WorktreeManager - Git Worktree 任务隔离管理器
参考 s12-worktree-task-isolation 设计：
每个任务拥有独立的 git worktree 目录，通过 task_id 双向绑定
"""
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class WorktreeManager:
    """
    Git Worktree 管理器。
    
    功能：
    - 创建 worktree 并绑定任务
    - 在 worktree 中执行命令（隔离的 cwd）
    - 保留或删除 worktree
    - 事件日志追踪生命周期
    
    控制层: .tasks/task_*.json (worktree 字段)
    执行层: .worktrees/{name}/
    """

    _instance: Optional["WorktreeManager"] = None

    def __new__(cls, root: Path = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, root: Path = None):
        if self._initialized:
            return
        
        # 解析根目录（相对于项目根目录）
        self.root = root or self._resolve(".worktrees")
        self.root.mkdir(parents=True, exist_ok=True)
        
        # 索引和事件文件
        self.index_path = self.root / "index.json"
        self.events_path = self.root / "events.jsonl"
        
        # 加载索引
        self.index = self._load_index()
        self._initialized = True

    def _resolve(self, rel_path: str) -> Path:
        """将相对路径解析为项目根目录下的绝对路径"""
        p = Path(rel_path)
        if p.is_absolute():
            return p
        return Path(__file__).parent.parent.parent / p

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        """加载 worktree 索引"""
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        return {}

    def _save_index(self):
        """保存 worktree 索引"""
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    def _emit(self, event: str, data: Dict[str, Any]):
        """写入事件日志"""
        entry = {
            "event": event,
            **data,
            "ts": int(time.time()),
        }
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ #
    #  Core Operations                                                     #
    # ------------------------------------------------------------------ #

    def create(self, name: str, task_id: int = None) -> Dict[str, Any]:
        """
        创建 worktree 并绑定任务。
        
        执行: git worktree add -b wt/{name} {path} HEAD
        """
        if name in self.index:
            raise ValueError(f"Worktree '{name}' already exists")
        
        wt_path = self.root / name
        branch = f"wt/{name}"
        
        # 创建 worktree
        try:
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch, str(wt_path), "HEAD"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git worktree add failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git worktree add timed out")
        except FileNotFoundError:
            raise RuntimeError("git not found in PATH")
        
        # 记录到索引
        entry = {
            "name": name,
            "path": str(wt_path),
            "branch": branch,
            "task_id": task_id,
            "created_at": time.time(),
            "status": "active",
        }
        self.index[name] = entry
        self._save_index()
        
        # 绑定任务（如果指定了 task_id）
        if task_id is not None:
            self._bind_task(task_id, name)
        
        self._emit("worktree.create.after", {"worktree": entry})
        return entry

    def remove(self, name: str, force: bool = False, complete_task: bool = False) -> Dict[str, Any]:
        """
        删除 worktree。
        
        Args:
            name: worktree 名称
            force: 是否强制删除（忽略未合并的更改）
            complete_task: 是否同时完成任务
        """
        if name not in self.index:
            raise KeyError(f"Worktree '{name}' not found")
        
        wt = self.index[name]
        wt_path = Path(wt["path"])
        
        # 删除 worktree
        cmd = ["git", "worktree", "remove", wt_path]
        if force:
            cmd.append("--force")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError(f"git worktree remove failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git worktree remove timed out")
        
        # 解除任务绑定
        task_id = wt.get("task_id")
        if task_id and complete_task:
            self._complete_task(task_id)
        
        # 从索引移除
        del self.index[name]
        self._save_index()
        
        self._emit("worktree.remove.after", {
            "worktree": wt,
            "task": {"id": task_id, "status": "completed" if complete_task else "in_progress"}
        })
        
        return {"removed": name, "task_completed": complete_task}

    def keep(self, name: str) -> Dict[str, Any]:
        """
        保留 worktree（不清除），但解绑任务。
        """
        if name not in self.index:
            raise KeyError(f"Worktree '{name}' not found")
        
        wt = self.index[name]
        wt["status"] = "kept"
        self._save_index()
        
        # 解绑任务
        task_id = wt.get("task_id")
        if task_id:
            self._unbind_task(task_id)
        
        self._emit("worktree.keep", {"worktree": wt})
        return {"kept": name}

    def execute_in_worktree(self, name: str, command: str, timeout: int = 300) -> Dict[str, Any]:
        """
        在指定的 worktree 中执行命令。
        
        Args:
            name: worktree 名称
            command: 要执行的命令
            timeout: 超时时间（秒）
        
        Returns:
            {"returncode": int, "stdout": str, "stderr": str}
        """
        if name not in self.index:
            raise KeyError(f"Worktree '{name}' not found")
        
        wt = self.index[name]
        wt_path = Path(wt["path"])
        
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(wt_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # ------------------------------------------------------------------ #
    #  Task Binding                                                       #
    # ------------------------------------------------------------------ #

    def _bind_task(self, task_id: int, worktree_name: str):
        """绑定任务到 worktree"""
        from src.tools.task_manager import TASKS
        try:
            TASKS.update(task_id, worktree=worktree_name)
        except FileNotFoundError:
            pass  # 任务可能不存在

    def _unbind_task(self, task_id: int):
        """解绑任务"""
        from src.tools.task_manager import TASKS
        try:
            TASKS.unbind_worktree(task_id)
        except FileNotFoundError:
            pass

    def _complete_task(self, task_id: int):
        """完成任务"""
        from src.tools.task_manager import TASKS
        try:
            TASKS.update(task_id, status="completed")
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------ #
    #  Query                                                              #
    # ------------------------------------------------------------------ #

    def list(self) -> List[Dict[str, Any]]:
        """列出所有 worktree"""
        return list(self.index.values())

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """获取指定 worktree 信息"""
        return self.index.get(name)

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的事件日志"""
        if not self.events_path.exists():
            return []
        
        events = []
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        
        return events[-limit:]


# 全局单例
WORKTREES = WorktreeManager()
