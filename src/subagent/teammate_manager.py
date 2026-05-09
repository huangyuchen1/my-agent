"""
TeammateManager - 持久化队友生命周期管理器
参考 s09-agent-teams 设计：daemon thread 运行 agent_loop，config.json 持久化团队名册
s10 增强：支持 shutdown_request / plan_response 握手协议
"""
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.subagent.message_bus import BUS


# s10: 导入协议管理器
try:
    from src.subagent.protocols import PROTOCOLS
except ImportError:
    PROTOCOLS = None


class TeammateManager:
    """
    队友管理器：持久化团队名册（config.json），维护每个队友的 daemon thread。
    状态流转: spawn(working) -> idle -> shutdown
    """

    _instance: Optional["TeammateManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, team_dir: Path = None):
        if self._initialized:
            return
        self.team_dir = team_dir or (Path("D:/new desk/myAgent/storage") / ".team")
        self.team_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.team_dir / "config.json"
        self.threads: Dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()
        self.config = self._load_config()
        self._initialized = True

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        default = {
            "members": [],
            "lead": {"name": "lead", "role": "coordinator"}
        }
        self._save_config(default)
        return default

    def _save_config(self, config: dict = None):
        config = config or self.config
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _find_member(self, name: str) -> Optional[dict]:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _update_member_status(self, name: str, status: str):
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    def spawn(
        self,
        name: str,
        role: str,
        prompt: Optional[str] = None,
        max_rounds: int = 50,
        model: Optional[str] = None,
    ) -> str:
        """创建并启动一个队友（在 daemon thread 中运行 agent_loop）"""
        if self._find_member(name):
            return f"Teammate '{name}' already exists"

        member = {
            "name": name,
            "role": role,
            "status": "working",
            "spawned_at": time.time(),
        }
        self.config["members"].append(member)
        self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt, max_rounds, model),
            daemon=True,
            name=f"teammate-{name}",
        )
        with self._threads_lock:
            self.threads[name] = thread
        thread.start()
        return f"Spawned teammate '{name}' (role: {role})"

    # s11: 空闲轮询配置
    IDLE_TIMEOUT = 60  # 空闲超时秒数
    IDLE_POLL_INTERVAL = 5  # 轮询间隔秒数

    def _teammate_loop(
        self,
        name: str,
        role: str,
        prompt: Optional[str],
        max_rounds: int,
        model: Optional[str],
    ):
        """
        s11: 队友在独立线程中运行的双阶段循环。
        
        WORK 阶段: 执行任务直到停止 (stop_reason != tool_use 或 idle)
        IDLE 阶段: 轮询收件箱和任务看板，等待新任务或超时关闭
        """
        from src.core.agent import get_client, get_system_prompt, get_current_model_config
        from src.tools.dispatcher import dispatcher

        try:
            client = get_client()
            model_id = model or get_current_model_config().model_id

            system_content = prompt or (
                f"You are {name}, a {role} teammate in the team.\n"
                "Your teammates communicate with you via inbox messages.\n"
                "Check your inbox at the start of each turn and respond accordingly.\n"
                "When you receive a task, use your tools to complete it.\n"
                "After completing your work, you may respond back to the sender via team_send.\n"
                "When you have no more work and are waiting for new tasks, use the idle tool to enter idle mode."
            )

            # s11: 初始消息列表
            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_content},
            ]

            all_tools = dispatcher.get_all_tools()
            # 队友不暴露 spawn/shutdown_req 相关工具，避免嵌套或滥用
            excluded = {"spawn_subagent", "team_spawn", "team_shutdown_req", "team_plan_review"}
            tools = [t for t in all_tools if t.get("function", {}).get("name") not in excluded]

            # s11: 外层 WORK/IDLE 循环
            while True:
                # === WORK PHASE ===
                # s11: 身份重注入 - 防止上下文压缩后失忆
                self._inject_identity(messages, name, role)

                work_rounds = 0
                idle_requested = False

                while work_rounds < max_rounds:
                    work_rounds += 1

                    # s11: 检查收件箱 (每轮开始时)
                    self._process_inbox(name, messages)

                    try:
                        response = client.chat.completions.create(
                            model=model_id,
                            messages=messages,
                            tools=tools,
                            max_tokens=32768,
                            extra_body={"thinking": {"type": "disabled"}}
                        )
                    except Exception as e:
                        print(f"[Teammate {name}] API error: {e}")
                        break

                    choice = response.choices[0]
                    assistant_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": choice.message.content or ""
                    }
                    if choice.message.tool_calls:
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in choice.message.tool_calls
                        ]
                    messages.append(assistant_msg)

                    if choice.finish_reason != "tool_calls":
                        # 对话自然结束，进入 IDLE
                        break

                    # 执行工具调用
                    tool_results = []
                    idle_requested = False
                    for tc in choice.message.tool_calls:
                        tool_name = tc.function.name
                        tool_args = json.loads(tc.function.arguments)
                        dispatcher._current_sender = name

                        # s11: 识别 idle 工具调用
                        if tool_name == "idle":
                            idle_requested = True
                            tool_results.append(json.dumps({"status": "idle requested"}))
                            continue

                        result = dispatcher.run_tool(tool_name, tool_args)
                        tool_results.append(result)

                    for tc, result in zip(choice.message.tool_calls, tool_results):
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    # 如果请求了 idle，退出工作循环
                    if idle_requested:
                        break

                # === IDLE PHASE ===
                self._update_member_status(name, "idle")
                resume = self._idle_poll(name, messages, system_content, tools, model_id, client)
                if not resume:
                    self._update_member_status(name, "shutdown")
                    return
                self._update_member_status(name, "working")

        except Exception as e:
            print(f"[Teammate {name}] Unhandled error: {e}")
            self._update_member_status(name, "idle")

    def _inject_identity(self, messages: List[Dict[str, Any]], name: str, role: str) -> None:
        """
        s11: 身份重注入 - 上下文过短时插入身份块，防止压缩后失忆。
        """
        if len(messages) <= 3:
            identity_block = {
                "role": "user",
                "content": f"<identity>You are '{name}', role: {role}, team: lead. Continue your work.</identity>"
            }
            response_block = {
                "role": "assistant",
                "content": f"I am {name}. Continuing."
            }
            messages.insert(0, identity_block)
            messages.insert(1, response_block)

    def _process_inbox(self, name: str, messages: List[Dict[str, Any]]) -> None:
        """
        s10/s11: 处理收件箱消息，区分协议消息和普通消息。
        """
        inbox_raw = BUS.read_inbox(name)
        if inbox_raw == "[]":
            return

        inbox_messages = json.loads(inbox_raw)
        for msg in inbox_messages:
            msg_type = msg.get("type", "message")
            if msg_type == "shutdown_request":
                # s10: 自动响应关机请求
                req_id = msg.get("request_id", "")
                if PROTOCOLS and req_id:
                    PROTOCOLS.respond_shutdown(req_id, approve=True, reason="Graceful shutdown approved.")
                BUS.send(name, "lead", "Shutting down gracefully as requested.", "shutdown_response")
                # 清空消息并返回，让上层知道要关闭
                messages.clear()
                messages.append({"role": "system", "content": "<system>Shutting down...</system>"})
                return
            elif msg_type == "plan_response":
                # s10: 处理计划审批响应
                req_id = msg.get("request_id", "")
                approve = msg.get("approve", False)
                feedback = msg.get("feedback", "")
                if approve:
                    inbox_content = f"\n<plan_approved request_id={req_id}>\n{msg.get('content', '')}\nFeedback: {feedback}\n</plan_approved>\n"
                else:
                    inbox_content = f"\n<plan_rejected request_id={req_id}>\n{msg.get('content', '')}\nFeedback: {feedback}\n</plan_rejected>\n"
                messages.append({
                    "role": "user",
                    "content": inbox_content
                })
            else:
                # 普通消息
                messages.append({
                    "role": "user",
                    "content": f"<inbox>\n{json.dumps(msg, ensure_ascii=False)}\n</inbox>"
                })

    def _idle_poll(
        self,
        name: str,
        messages: List[Dict[str, Any]],
        system_content: str,
        tools: list,
        model_id: str,
        client,
    ) -> bool:
        """
        s11: 空闲轮询 - 检查收件箱和任务看板，超时则关闭。
        
        Returns:
            True: 有新任务，继续工作
            False: 超时，进入 shutdown
        """
        from src.tools.task_manager import TASKS

        poll_count = self.IDLE_TIMEOUT // self.IDLE_POLL_INTERVAL
        
        for _ in range(poll_count):
            time.sleep(self.IDLE_POLL_INTERVAL)

            # 1. 检查收件箱
            inbox_raw = BUS.read_inbox(name)
            if inbox_raw != "[]":
                inbox_messages = json.loads(inbox_raw)
                # 检查是否有非协议消息
                has_work = False
                for msg in inbox_messages:
                    if msg.get("type") not in ("shutdown_request", "shutdown_response", "plan_response"):
                        has_work = True
                        messages.append({
                            "role": "user",
                            "content": f"<inbox>\n{json.dumps(msg, ensure_ascii=False)}\n</inbox>"
                        })
                    elif msg.get("type") == "shutdown_request":
                        # 处理关机请求
                        self._process_inbox(name, messages)
                        if "<system>Shutting down...</system>" in messages[-1].get("content", ""):
                            return False
                if has_work:
                    print(f"[Teammate {name}] Resuming from inbox message")
                    return True

            # 2. s11: 扫描任务看板，认领无人负责的任务
            try:
                unclaimed = TASKS.get_runnable_tasks_unowned()
                if unclaimed:
                    task = unclaimed[0]
                    # 认领任务
                    TASKS.update(task["id"], status="in_progress", owner=name)
                    print(f"[Teammate {name}] Auto-claimed task #{task['id']}: {task['subject']}")
                    # 重置消息列表，注入新任务
                    messages.clear()
                    messages.append({"role": "system", "content": system_content})
                    self._inject_identity(messages, name, name.split("_")[0] if "_" in name else name)
                    messages.append({
                        "role": "user",
                        "content": f"<auto-claimed>Task #{task['id']}: {task['subject']}\n\nDescription: {task.get('description', 'N/A')}</auto-claimed>"
                    })
                    return True
            except Exception as e:
                print(f"[Teammate {name}] Error scanning tasks: {e}")

        # 超时，返回 False 让上层关闭
        print(f"[Teammate {name}] Idle timeout, shutting down")
        return False

    def shutdown(self, name: str) -> str:
        """关闭指定队友（标记状态，实际线程为 daemon 会自然终止）"""
        member = self._find_member(name)
        if not member:
            return f"Teammate '{name}' not found"
        member["status"] = "shutdown"
        self._save_config()
        with self._threads_lock:
            if name in self.threads:
                del self.threads[name]
        return f"Teammate '{name}' shutdown"

    def list_members(self) -> List[dict]:
        """列出所有队友"""
        return list(self.config["members"])

    def get_manager(self) -> "TeammateManager":
        """获取全局 TeammateManager 单例"""
        return TeammateManager()

    def get_active_threads(self) -> List[str]:
        """获取当前活跃的线程名称"""
        with self._threads_lock:
            return list(self.threads.keys())


# 全局单例
TM = TeammateManager()
