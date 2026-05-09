"""
Protocols - Request-Response 握手协议追踪器
参考 s10-team-protocols 设计：shutdown + plan approval 两种握手协议
"""
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class Protocols:
    """
    结构化协议管理器。
    
    提供两种请求-响应协议：
    1. Shutdown Protocol: 领导请求队友关机，队友批准/拒绝
    2. Plan Approval Protocol: 队友提交计划，领导审批/拒绝
    
    每个请求带唯一 request_id，状态机: pending -> approved | rejected
    """

    _instance: Optional["Protocols"] = None

    def __new__(cls, team_dir: Path = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, team_dir: Path = None):
        if self._initialized:
            return
        self.team_dir = team_dir or (Path("D:/new desk/myAgent/storage") / ".team")
        self.team_dir.mkdir(parents=True, exist_ok=True)
        
        # 请求追踪器
        self._shutdown_requests: Dict[str, Dict[str, Any]] = {}
        self._plan_requests: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        # 持久化路径
        self._shutdown_path = self.team_dir / "shutdown_requests.json"
        self._plan_path = self.team_dir / "plan_requests.json"
        
        # 加载持久化数据
        self._load()
        self._initialized = True

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def _load(self):
        """从磁盘加载请求状态"""
        if self._shutdown_path.exists():
            with open(self._shutdown_path, "r", encoding="utf-8") as f:
                self._shutdown_requests = {k: v for k, v in json.loads(f.read()).items()}
        if self._plan_path.exists():
            with open(self._plan_path, "r", encoding="utf-8") as f:
                self._plan_requests = {k: v for k, v in json.loads(f.read()).items()}

    def _save_shutdown(self):
        with self._lock:
            with open(self._shutdown_path, "w", encoding="utf-8") as f:
                json.dump(self._shutdown_requests, f, ensure_ascii=False, indent=2)

    def _save_plan(self):
        with self._lock:
            with open(self._plan_path, "w", encoding="utf-8") as f:
                json.dump(self._plan_requests, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ #
    #  Shutdown Protocol                                                   #
    # ------------------------------------------------------------------ #

    def create_shutdown_request(self, target: str) -> str:
        """
        创建关机请求，返回 request_id。
        """
        req_id = str(uuid.uuid4())[:8]
        self._shutdown_requests[req_id] = {
            "type": "shutdown_request",
            "target": target,
            "status": "pending",
            "created_at": time.time(),
        }
        self._save_shutdown()
        return req_id

    def get_shutdown_request(self, req_id: str) -> Optional[Dict[str, Any]]:
        return self._shutdown_requests.get(req_id)

    def respond_shutdown(self, req_id: str, approve: bool, reason: str = "") -> Dict[str, Any]:
        """
        队友响应关机请求。
        """
        req = self._shutdown_requests.get(req_id)
        if not req:
            return {"error": f"Request {req_id} not found"}
        
        req["status"] = "approved" if approve else "rejected"
        req["responded_at"] = time.time()
        req["reason"] = reason
        self._save_shutdown()
        return req

    def get_pending_shutdown_for_target(self, target: str) -> Dict[str, Dict[str, Any]]:
        """获取目标所有待处理的关机请求"""
        return {
            req_id: req
            for req_id, req in self._shutdown_requests.items()
            if req.get("target") == target and req.get("status") == "pending"
        }

    # ------------------------------------------------------------------ #
    #  Plan Approval Protocol                                              #
    # ------------------------------------------------------------------ #

    def create_plan_request(self, from_name: str, plan: str) -> str:
        """
        队友提交计划申请，返回 request_id。
        """
        req_id = str(uuid.uuid4())[:8]
        self._plan_requests[req_id] = {
            "type": "plan_request",
            "from": from_name,
            "plan": plan,
            "status": "pending",
            "created_at": time.time(),
        }
        self._save_plan()
        return req_id

    def get_plan_request(self, req_id: str) -> Optional[Dict[str, Any]]:
        return self._plan_requests.get(req_id)

    def respond_plan(self, req_id: str, approve: bool, feedback: str = "") -> Dict[str, Any]:
        """
        领导审批计划请求。
        """
        req = self._plan_requests.get(req_id)
        if not req:
            return {"error": f"Request {req_id} not found"}
        
        req["status"] = "approved" if approve else "rejected"
        req["responded_at"] = time.time()
        req["feedback"] = feedback
        self._save_plan()
        return req

    def get_pending_plans_for_lead(self) -> Dict[str, Dict[str, Any]]:
        """获取所有待审批的计划请求"""
        return {
            req_id: req
            for req_id, req in self._plan_requests.items()
            if req.get("status") == "pending"
        }

    # ------------------------------------------------------------------ #
    #  Query                                                               #
    # ------------------------------------------------------------------ #

    def get_all_pending_requests(self) -> Dict[str, Any]:
        """获取所有待处理的请求（用于调试）"""
        return {
            "shutdown_requests": {
                req_id: req for req_id, req in self._shutdown_requests.items()
                if req.get("status") == "pending"
            },
            "plan_requests": {
                req_id: req for req_id, req in self._plan_requests.items()
                if req.get("status") == "pending"
            },
        }

    def clear_resolved(self, older_than_seconds: int = 3600):
        """清理超过指定时间的已解决请求"""
        now = time.time()
        cutoff = now - older_than_seconds
        
        # 清理 shutdown
        to_remove = [
            req_id for req_id, req in self._shutdown_requests.items()
            if req.get("status") in ("approved", "rejected") and req.get("responded_at", 0) < cutoff
        ]
        for req_id in to_remove:
            del self._shutdown_requests[req_id]
        if to_remove:
            self._save_shutdown()
        
        # 清理 plan
        to_remove = [
            req_id for req_id, req in self._plan_requests.items()
            if req.get("status") in ("approved", "rejected") and req.get("responded_at", 0) < cutoff
        ]
        for req_id in to_remove:
            del self._plan_requests[req_id]
        if to_remove:
            self._save_plan()


# 全局单例
import json
PROTOCOLS = Protocols()
