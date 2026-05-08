"""
MessageBus - 基于 JSONL 的 Agent 间消息总线
参考 s09-agent-teams 设计：append-only 收件箱，drain-on-read 机制
"""
import json
import threading
import time
from pathlib import Path
from typing import Optional


class MessageBus:
    """
    基于 append-only JSONL 的消息总线。
    每个 Agent 有独立的 inbox 文件（inbox/{name}.jsonl）。
    """

    _instance: Optional["MessageBus"] = None

    def __new__(cls, team_dir: Path = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, team_dir: Path = None):
        if self._initialized:
            return
        self.team_dir = team_dir or (Path("D:/new desk/myAgent/storage") / ".team")
        self.inbox_dir = self.team_dir / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialized = True

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict = None,
    ) -> str:
        """向指定 Agent 的收件箱追加一条消息"""
        msg = {
            "type": msg_type,
            "from": sender,
            "to": to,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        inbox_path = self.inbox_dir / f"{to}.jsonl"
        with self._lock:
            with open(inbox_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return f"Message sent from {sender} to {to}"

    def broadcast(self, sender: str, content: str, members: list[str]) -> str:
        """向多个成员广播同一条消息"""
        count = 0
        for member in members:
            if member != sender:
                self.send(sender, member, content, msg_type="broadcast")
                count += 1
        return f"Broadcast from {sender} to {count} members"

    def read_inbox(self, name: str) -> str:
        """
        读取并清空指定 Agent 的收件箱（drain-on-read）。
        返回 JSON 字符串。
        """
        inbox_path = self.inbox_dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return "[]"
        with self._lock:
            content = inbox_path.read_text(encoding="utf-8").strip()
            inbox_path.write_text("", encoding="utf-8")
        if not content:
            return "[]"
        lines = [l for l in content.splitlines() if l]
        return json.dumps([json.loads(l) for l in lines], ensure_ascii=False, indent=2)

    def peek_inbox(self, name: str) -> str:
        """
        只读取收件箱内容（不删除），用于查询未读消息。
        """
        inbox_path = self.inbox_dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return "[]"
        with self._lock:
            content = inbox_path.read_text(encoding="utf-8").strip()
        if not content:
            return "[]"
        lines = [l for l in content.splitlines() if l]
        return json.dumps([json.loads(l) for l in lines], ensure_ascii=False, indent=2)

    def get_inbox_count(self, name: str) -> int:
        """获取收件箱未读消息数"""
        inbox_path = self.inbox_dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return 0
        with self._lock:
            content = inbox_path.read_text(encoding="utf-8").strip()
        if not content:
            return 0
        return len([l for l in content.splitlines() if l])


# 全局单例
BUS = MessageBus()
