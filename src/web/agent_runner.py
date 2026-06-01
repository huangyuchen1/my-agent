"""
AgentRunner - Web 模式下的 Agent 运行器
在后台线程中运行 agent_loop_with_events，通过 EventBus 发出所有事件
"""
import threading
import json
from typing import List, Dict, Any, Optional

from src.web.event_bus import EventBus, EventType, get_event_bus, reset_event_bus
from src.core.config import init_config, get_config
from src.core.agent import get_system_prompt


class AgentRunner:
    """
    在后台线程中运行 agent_loop，通过 EventBus 发出所有事件。

    使用方式：
    runner = AgentRunner()
    runner.start(messages)  # 启动 agent_loop
    # EventBus 会自动将事件推送到 WebSocket
    """

    def __init__(self):
        self.bus: EventBus = get_event_bus()
        self._thread: Optional[threading.Thread] = None
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def start(self, user_message: str) -> None:
        """
        启动 agent_loop 处理用户消息。

        Args:
            user_message: 用户输入的文本
        """
        with self._lock:
            # 如果已有线程在运行，等待其结束
            if self._thread is not None and self._thread.is_alive():
                return

            # 重置事件总线
            self.bus = reset_event_bus()

            # 初始化配置
            config = init_config()

            # 构建消息历史
            self._history = [{
                "role": "system",
                "content": get_system_prompt()
            }]
            self._history.append({"role": "user", "content": user_message})

            # 发送用户消息事件
            self.bus.publish(EventType.USER_MESSAGE, {"content": user_message})

            # 启动 daemon 线程
            self._thread = threading.Thread(
                target=self._run_agent_loop,
                daemon=True,
                name="agent-web-runner"
            )
            self._thread.start()

    def _run_agent_loop(self) -> None:
        """在 daemon 纨程中运行 agent_loop_with_events"""
        try:
            from src.core.agent import agent_loop_with_events
            agent_loop_with_events(self._history, self.bus, use_subagent=True)
        except Exception as e:
            self.bus.publish(EventType.ERROR, {
                "message": str(e),
                "type": type(e).__name__
            })
            self.bus.publish(EventType.AGENT_DONE, {"error": True})

    def is_running(self) -> bool:
        """检查 agent_loop 是否正在运行"""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def get_history(self) -> List[Dict[str, Any]]:
        """获取当前消息历史"""
        with self._lock:
            return self._history.copy()

    def continue_conversation(self, user_message: str) -> None:
        """
        继续对话（追加用户消息到现有历史）。

        Args:
            user_message: 用户输入的文本
        """
        with self._lock:
            if not self._history:
                self.start(user_message)
                return

            # 如果线程正在运行，等待结束
            if self._thread is not None and self._thread.is_alive():
                return

            # 追加用户消息
            self._history.append({"role": "user", "content": user_message})

            # 重置事件总线
            self.bus = reset_event_bus()
            self.bus.publish(EventType.USER_MESSAGE, {"content": user_message})

            # 启动新线程
            self._thread = threading.Thread(
                target=self._run_agent_loop,
                daemon=True,
                name="agent-web-runner"
            )
            self._thread.start()


# 全局单例
_runner: Optional[AgentRunner] = None


def get_runner() -> AgentRunner:
    """获取全局 AgentRunner 单例"""
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner