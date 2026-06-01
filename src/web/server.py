"""
FastAPI Web Server - myAgent 前端服务
提供 WebSocket 双向通信和 REST API 状态查询
"""
import asyncio
import json
import threading
import webbrowser
from pathlib import Path
from typing import Dict, Any, List, Optional
from queue import Queue

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

from src.web.event_bus import EventBus, EventType
from src.core.config import init_config, get_config
from src.subagent.teammate_manager import TM
from src.tools.task_manager import TASKS
from src.core.background_manager import BG


app = FastAPI(title="myAgent Web UI")

# 全局状态
_event_bus: Optional[EventBus] = None
_agent_thread: Optional[threading.Thread] = None
_history: List[Dict[str, Any]] = []


def get_event_bus() -> EventBus:
    """获取事件总线"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def get_index_html() -> str:
    """读取前端页面 HTML"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")


def get_status_data() -> Dict[str, Any]:
    """聚合所有系统状态"""
    config = get_config()

    # 获取任务摘要
    task_summary = {}
    try:
        all_tasks = TASKS._all_tasks()
        for task in all_tasks:
            status = task.get("status", "unknown")
            task_summary[status] = task_summary.get(status, 0) + 1
    except Exception:
        pass

    # 获取团队成员
    team_members = []
    try:
        team_members = TM.list_members()
    except Exception:
        pass

    # 获取后台任务
    bg_tasks = []
    try:
        bg_tasks = BG.list_tasks()
    except Exception:
        pass

    # 检查 agent 是否运行
    is_running = _agent_thread is not None and _agent_thread.is_alive()

    return {
        "model": {
            "name": config.current_model_config.name,
            "id": config.current_model_config.model_id
        },
        "available_models": config.available_models,
        "tasks": {
            "summary": task_summary,
            "count": len(task_summary)
        },
        "team": {
            "members": team_members,
            "active_threads": len([m for m in team_members if m.get("status") == "WORK"])
        },
        "background": {
            "tasks": bg_tasks
        },
        "agent_running": is_running
    }


def run_agent_loop(user_message: str, event_bus: EventBus):
    """在后台线程运行 agent_loop"""
    global _history

    from src.core.agent import agent_loop_with_events, get_system_prompt

    # 初始化消息历史
    if not _history:
        _history = [{
            "role": "system",
            "content": get_system_prompt()
        }]

    # 追加用户消息
    _history.append({"role": "user", "content": user_message})
    event_bus.publish(EventType.USER_MESSAGE, {"content": user_message})

    try:
        agent_loop_with_events(_history, event_bus, use_subagent=True)
    except Exception as e:
        event_bus.publish(EventType.ERROR, {"message": str(e)})
        event_bus.publish(EventType.AGENT_DONE, {"error": True})


@app.get("/", response_class=HTMLResponse)
async def index():
    """服务前端页面"""
    return HTMLResponse(content=get_index_html())


@app.get("/api/status")
async def api_status():
    """REST API: 获取系统状态"""
    return get_status_data()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket 端点:
    - 接收用户消息
    - 推送 Agent 事件（流式输出、工具调用等）
    """
    global _agent_thread

    await ws.accept()

    # 发送连接成功消息
    await ws.send_json({
        "type": "connected",
        "data": {"message": "已连接到 myAgent"}
    })

    # 发送初始状态
    await ws.send_json({
        "type": "status",
        "data": get_status_data()
    })

    # 获取事件总线
    bus = get_event_bus()

    # 定义事件回调：将事件发送到 WebSocket
    async def send_event(event: Dict[str, Any]):
        try:
            await ws.send_json(event)
        except Exception:
            pass

    def on_event(event: Dict[str, Any]):
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(send_event(event), loop)
        except Exception:
            pass

    bus.subscribe(on_event)

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "user_message":
                content = msg.get("content", "")
                if content and (_agent_thread is None or not _agent_thread.is_alive()):
                    # 先发送用户消息到前端显示
                    await ws.send_json({
                        "type": "user_message",
                        "data": {"content": content}
                    })
                    # 启动新的 agent 线程
                    bus.drain()  # 清空旧事件，但不重置订阅者
                    _agent_thread = threading.Thread(
                        target=run_agent_loop,
                        args=(content, bus),
                        daemon=True,
                        name="agent-web-runner"
                    )
                    _agent_thread.start()
                    await ws.send_json({
                        "type": "status",
                        "data": {"agent_running": True}
                    })

            elif msg.get("type") == "get_status":
                await ws.send_json({
                    "type": "status",
                    "data": get_status_data()
                })

            elif msg.get("type") == "switch_model":
                target = msg.get("model", "")
                config = get_config()
                if config.set_model(target):
                    # 重置历史
                    from src.core.agent import get_system_prompt
                    global _history
                    _history = [{
                        "role": "system",
                        "content": get_system_prompt()
                    }]
                    await ws.send_json({
                        "type": "status",
                        "data": get_status_data()
                    })
                else:
                    await ws.send_json({
                        "type": "error",
                        "data": {"message": f"未知的模型: {target}"}
                    })

    except WebSocketDisconnect:
        bus.unsubscribe(on_event)
    except Exception as e:
        bus.unsubscribe(on_event)
        try:
            await ws.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except Exception:
            pass


def run_web_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True):
    """
    启动 Web 服务器

    Args:
        host: 监听地址
        port: 监听端口
        open_browser: 是否自动打开浏览器
    """
    # 初始化配置
    init_config()

    url = f"http://{host}:{port}"
    print(f"\n{'='*60}")
    print("        myAgent Web UI")
    print(f"        地址: {url}")
    print(f"{'='*60}")
    print("\n提示:")
    print("  - 浏览器将自动打开")
    print("  - 按 Ctrl+C 停止服务器\n")

    if open_browser:
        def open_browser_delayed():
            import time
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=open_browser_delayed, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_web_server()