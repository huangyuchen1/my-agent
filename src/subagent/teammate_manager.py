"""
TeammateManager - 持久化队友生命周期管理器
参考 s09-agent-teams 设计：daemon thread 运行 agent_loop，config.json 持久化团队名册
"""
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.subagent.message_bus import BUS


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

    def _teammate_loop(
        self,
        name: str,
        role: str,
        prompt: Optional[str],
        max_rounds: int,
        model: Optional[str],
    ):
        """队友在独立线程中运行的 agent_loop"""
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
                "After completing your work, you may respond back to the sender via team_send."
            )

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_content},
            ]

            all_tools = dispatcher.get_all_tools()
            # 队友不暴露 spawn 相关工具，避免嵌套
            excluded = {"spawn_subagent", "team_spawn"}
            tools = [t for t in all_tools if t.get("function", {}).get("name") not in excluded]

            for round_num in range(max_rounds):
                # 检查收件箱
                inbox_raw = BUS.read_inbox(name)
                if inbox_raw != "[]":
                    messages.append({
                        "role": "user",
                        "content": f"<inbox>\n{inbox_raw}\n</inbox>"
                    })

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
                    # 对话自然结束，可以回复发件人
                    break

                # 执行工具调用
                tool_results = []
                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    tool_args = json.loads(tc.function.arguments)
                    dispatcher._current_sender = name
                    result = dispatcher.run_tool(tool_name, tool_args)
                    tool_results.append(result)

                for tc, result in zip(choice.message.tool_calls, tool_results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            # 循环正常结束，标记 idle
            self._update_member_status(name, "idle")

        except Exception as e:
            print(f"[Teammate {name}] Unhandled error: {e}")
            self._update_member_status(name, "idle")

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
