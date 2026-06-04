"""
SessionManager - 用户对话会话的本地持久化管理
支持会话的创建、保存、加载、搜索和删除
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionManager:
    """用户会话管理器"""

    def __init__(self, sessions_dir: Optional[Path] = None):
        if sessions_dir is None:
            project_root = Path(__file__).parent.parent.parent
            sessions_dir = project_root / "storage" / "sessions"
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, sid: str) -> Path:
        return self.sessions_dir / f"{sid}.json"

    # ------------------------------------------------------------------
    # 核心 CRUD
    # ------------------------------------------------------------------

    def create_session(
        self,
        title: str,
        messages: List[Dict[str, Any]],
        model: str = "",
    ) -> Dict[str, Any]:
        """
        创建新会话并保存到文件。

        Returns:
            包含 id, path, title, created_at 的字典
        """
        sid = str(int(time.time() * 1000))
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        data = {
            "id": sid,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "model": model,
            "messages": messages,
        }
        path = self._get_path(sid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {
            "id": sid,
            "path": str(path),
            "title": title,
            "created_at": now,
        }

    def save_session(
        self,
        sid: str,
        messages: List[Dict[str, Any]],
        title: Optional[str] = None,
        model: Optional[str] = None,
    ) -> bool:
        """
        更新已有会话文件（完整覆盖）。

        Returns:
            True if session existed and was updated, False if not found.
        """
        path = self._get_path(sid)
        if not path.exists():
            return False

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        data["messages"] = messages
        data["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if title is not None:
            data["title"] = title
        if model is not None:
            data["model"] = model

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def load_session(self, sid: str) -> Optional[List[Dict[str, Any]]]:
        """
        加载指定会话的 messages 列表。

        Returns:
            messages 列表（不含 session 元信息），不存在时返回 None。
        """
        path = self._get_path(sid)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])

    def get_session_meta(self, sid: str) -> Optional[Dict[str, Any]]:
        """获取会话元信息（不含 messages，用于列表展示）"""
        path = self._get_path(sid)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "id": data["id"],
            "title": data["title"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "model": data.get("model", ""),
            "message_count": len(data.get("messages", [])),
        }

    def delete_session(self, sid: str) -> bool:
        """删除指定会话文件"""
        path = self._get_path(sid)
        if not path.exists():
            return False
        path.unlink()
        return True

    def rename_session(self, sid: str, new_title: str) -> bool:
        """重命名会话标题"""
        path = self._get_path(sid)
        if not path.exists():
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["title"] = new_title
        data["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        列出所有会话元信息，按 updated_at 倒序。

        Returns:
            [{id, title, created_at, updated_at, model, message_count}, ...]
        """
        sessions = []
        for path in sorted(self.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "id": data["id"],
                    "title": data["title"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "model": data.get("model", ""),
                    "message_count": len(data.get("messages", [])),
                })
                if len(sessions) >= limit:
                    break
            except (json.JSONDecodeError, KeyError):
                continue
        return list(reversed(sessions))  # newest last for display

    def search_sessions(self, keyword: str) -> List[Dict[str, Any]]:
        """
        在会话标题和首条用户消息中搜索关键词（不区分大小写）。
        """
        keyword = keyword.lower()
        results = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                title = data.get("title", "").lower()
                # 搜索首条用户消息
                first_user = ""
                for msg in data.get("messages", []):
                    if msg.get("role") == "user":
                        first_user = msg.get("content", "")[:100].lower()
                        break
                if keyword in title or keyword in first_user:
                    results.append({
                        "id": data["id"],
                        "title": data["title"],
                        "created_at": data["created_at"],
                        "updated_at": data["updated_at"],
                        "model": data.get("model", ""),
                        "message_count": len(data.get("messages", [])),
                    })
            except (json.JSONDecodeError, KeyError):
                continue
        return results


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_sm: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _sm
    if _sm is None:
        _sm = SessionManager()
    return _sm


def _get_path(sid: str) -> Path:
    """获取会话文件路径"""
    sm = get_session_manager()
    return sm.sessions_dir / f"{sid}.json"
