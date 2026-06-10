"""
EventBus - 线程安全的事件发布/订阅系统
用于 agent_loop 与 WebSocket handler 之间的通信
"""
import queue
import threading
from enum import Enum
from typing import Any, Dict, List, Callable, Optional


class EventType(str, Enum):
    """所有事件类型定义"""
    # LLM 流式输出
    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"

    # 工具调用
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_END = "tool_end"

    # 系统通知
    BACKGROUND_NOTIFICATION = "background_notification"
    TEAM_INBOX = "team_inbox"
    COMPACT_EVENT = "compact_event"
    ERROR = "error"

    # 生命周期
    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_MESSAGE_COMPLETE = "agent_message_complete"

    # 用户交互
    USER_MESSAGE = "user_message"

    # 指标统计
    TOOL_METRICS = "tool_metrics"       # 单个工具执行指标
    ROUND_METRICS = "round_metrics"    # 单轮模型调用指标
    SESSION_METRICS = "session_metrics"  # 会话结束汇总


class EventBus:
    """
    线程安全的事件总线。
    agent_loop 向它发布事件，WebSocket handler 订阅消费。

    使用生产者-消费者模式：
    - agent_loop (daemon thread) 作为生产者，调用 publish()
    - WebSocket handler (asyncio) 作为消费者，调用 drain()
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._subscribers: List[Callable] = []
        self._lock = threading.Lock()
        self._running = True

    def publish(self, event_type: EventType, data: Optional[Dict[str, Any]] = None) -> None:
        """发布事件（agent_loop 调用）"""
        if not self._running:
            return
        event = {
            "type": event_type.value,
            "data": data or {},
            "timestamp": threading.Event()
        }
        self._queue.put(event)

        # 同步通知所有订阅者
        with self._lock:
            for callback in self._subscribers:
                try:
                    callback(event)
                except Exception:
                    pass  # 忽略订阅者错误

    def subscribe(self, callback: Callable) -> None:
        """注册订阅者（WebSocket handler 调用）"""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """取消订阅"""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def drain(self) -> List[Dict[str, Any]]:
        """排空事件队列（由 WebSocket 发送循环调用）"""
        events = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def stop(self) -> None:
        """停止事件总线"""
        self._running = False

    def reset(self) -> None:
        """重置事件总线（清空队列）"""
        self.drain()  # 清空队列
        self._running = True


# 全局单例
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局事件总线单例"""
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> EventBus:
    """重置并获取新的全局事件总线"""
    global _global_bus
    if _global_bus is not None:
        _global_bus.stop()
    _global_bus = EventBus()
    return _global_bus