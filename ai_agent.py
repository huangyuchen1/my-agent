"""
AI Agent - 对接 Moonshot AI (Kimi) 大模型的简单对话助手
支持联网搜索和控制台操作功能
"""
import json
import os
import time
import threading
import sys
from typing import *

from openai import OpenAI

from console_tools import ConsoleTools, TOOLS_DEFINITION, TOOL_HANDLERS, TODO

# -- 状态显示控制 --
_status_stop_event = threading.Event()
_status_thread = None


def _spinner_chars():
    """返回不同平台的转圈字符"""
    if sys.platform == "win32":
        return ["-", "\\", "|", "/"]
    return ["◐", "◓", "◑", "◒"]


def _show_status(message: str, delay: float = 0.15):
    """
    在后台线程中显示状态动画
    使用 \r 回到行首覆盖显示
    """
    global _status_stop_event
    spinners = _spinner_chars()
    idx = 0
    
    # 保存原始光标状态
    sys.stdout.write("\033[?25l")  # 隐藏光标
    sys.stdout.flush()
    
    while not _status_stop_event.is_set():
        spinner = spinners[idx % len(spinners)]
        sys.stdout.write(f"\r\033[36m[{spinner}]\033[0m {message}")
        sys.stdout.flush()
        time.sleep(delay)
        idx += 1
    
    # 完成后清除状态行
    sys.stdout.write("\r" + " " * (len(message) + 10) + "\r")
    sys.stdout.flush()
    sys.stdout.write("\033[?25h")  # 恢复光标
    sys.stdout.flush()


def _start_status(message: str) -> threading.Thread:
    """启动状态显示线程"""
    global _status_stop_event, _status_thread
    _status_stop_event.clear()
    _status_thread = threading.Thread(target=_show_status, args=(message,))
    _status_thread.daemon = True
    _status_thread.start()
    return _status_thread


def _stop_status(success: bool = True, final_msg: str = ""):
    """停止状态显示"""
    global _status_stop_event
    _status_stop_event.set()
    if _status_thread:
        _status_thread.join(timeout=0.5)
    
    if final_msg:
        icon = "\033[32m✓\033[0m" if success else "\033[31m✗\033[0m"
        print(f"{icon} {final_msg}")

# -- 初始化客户端 --
MODEL = "kimi-k2.5"
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY", "sk-0cJM2iDt54p4AA4qUSZCHH57mpyDNx8Gq6VkBojyN7JqEklG"),
    base_url="https://api.moonshot.cn/v1"
)

console_tools = ConsoleTools(os.getcwd())

rounds_since_todo = 0


def run_console_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    执行控制台工具的统一入口。
    工具注册在 TOOL_HANDLERS 中，扩展时只需在 console_tools.py
    加方法 + 加 schema 定义即可，无需改这里。
    """
    method_name = TOOL_HANDLERS.get(tool_name)
    if not method_name:
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

    method = getattr(console_tools, method_name, None)
    if not method:
        return json.dumps({"error": f"Tool method not found: {method_name}"}, ensure_ascii=False)

    try:
        return method(arguments)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# -- 合并工具定义：搜索 + 控制台工具 --
ALL_TOOLS = [{
    "type": "builtin_function",
    "function": {"name": "$web_search"},
}] + TOOLS_DEFINITION


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    """
    核心 Agent 循环模式:

        while stop_reason == "tool_calls":
            response = LLM(messages, tools)
            execute tools
            append results
    """
    global rounds_since_todo
    total_rounds = 0

    while True:
        total_rounds += 1
        
        # Nag reminder: 连续 3 轮以上不调用 todo 时注入提醒
        if rounds_since_todo >= 3 and messages:
            last = messages[-1]
            if last["role"] == "user":
                content = last.get("content", "")
                if isinstance(content, str) and "<reminder>" not in content:
                    last["content"] = "<reminder>Update your todos.</reminder>\n\n" + content
                elif isinstance(content, list):
                    has_reminder = any(
                        isinstance(block, dict) and block.get("type") == "text"
                        and "<reminder>" in block.get("text", "")
                        for block in content
                    )
                    if not has_reminder:
                        content.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        # 显示状态：正在思考
        thinking_msg = f"思考中 (第 {total_rounds} 轮)"
        if total_rounds == 1:
            thinking_msg = "正在思考你的问题..."
        _start_status(thinking_msg)
        
        # 构建请求参数（只传 messages，不要重复传 system）
        request_params = {
            "model": MODEL,
            "messages": messages,
            "tools": ALL_TOOLS,
            "max_tokens": 32768,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        MAX_RETRIES = 3
        RETRY_DELAY = 2.0  # 秒，初始等待时间

        # 调用模型，支持 429 限流自动重试
        api_error = None
        for attempt in range(MAX_RETRIES):
            try:
                completion = client.chat.completions.create(**request_params)
                _stop_status(success=True, final_msg="思考完成 ✓")
                break
            except Exception as e:
                api_error = e
                error_str = str(e)
                is_rate_limit = "429" in error_str or "overloaded" in error_str.lower()
                if is_rate_limit and attempt < MAX_RETRIES - 1:
                    _stop_status(success=False, final_msg="")
                    print(
                        f"\n\033[33m[限流] 请求过于频繁，{RETRY_DELAY:.1f}秒后重试... ({attempt + 1}/{MAX_RETRIES})\033[0m")
                    time.sleep(RETRY_DELAY)
                    RETRY_DELAY *= 1.5  # 递增等待时间
                    _start_status(thinking_msg)
                else:
                    _stop_status(success=False, final_msg="")
                    print(f"\n\033[31m[API错误] {e}\033[0m")
                    return

        choice = completion.choices[0]

        # 将助手响应转换为 dict 格式
        assistant_msg = {
            "role": "assistant",
            "content": choice.message.content or "",
        }
        if choice.message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in choice.message.tool_calls
            ]
        messages.append(assistant_msg)

        # 如果模型没有调用工具，循环结束
        if choice.finish_reason != "tool_calls":
            return

        # 显示状态：正在调用工具
        tool_names = [tc.function.name for tc in choice.message.tool_calls]
        tools_preview = ", ".join(tool_names[:3])
        if len(tool_names) > 3:
            tools_preview += f" (+{len(tool_names) - 3}个)"
        _start_status(f"正在调用工具: {tools_preview}")
        
        # 执行每个工具调用，收集结果
        results = []
        for tool_call in choice.message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 打印执行的命令
            print(f"\n\033[33m$ {tool_name}({json.dumps(tool_args)[:100]}...)\033[0m")

            # 执行工具
            if tool_name == "$web_search":
                output = json.dumps(tool_args)
            else:
                output = run_console_tool(tool_name, tool_args)

            # 如果调用了 todo 工具，重置计数器
            if tool_name == "todo":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            print(output[:300] if output else "(no output)")

            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": output,
            })
        
        _stop_status(success=True, final_msg=f"工具调用完成 ({len(results)}个工具)")

        # 将工具结果追加到 messages，继续循环，此处由于大模型的API不允许一次性将所有工具调用结果整合成一条消息发送，因此这个要分成多条来
        for tc, result in zip(choice.message.tool_calls, results):
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result["content"],
            })


def main():
    """主函数 - 命令行交互界面"""
    print("=" * 60)
    print("        AI Agent - Kimi 对话助手 (联网版 + 控制台)")
    print("=" * 60)
    print("\n提示:")
    print("  - 输入 'q' 或 'quit' 退出")
    print("  - 可执行命令: ls, git, python, npm 等")
    print("  - 可读写文件、查看进程等\n")

    history = [{
        "role": "system",
        "content": SYSTEM
    }]

    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        # 在历史对话中插入用户聊天记录
        history.append({"role": "user", "content": query})

        # 调用对话函数
        try:
            agent_loop(history)
        except Exception as e:
            print(f"\n\033[31m[错误] {e}\033[0m")
            continue

        # 取聊天历史中最后一次的对话作为响应结果
        response_content = history[-1]["content"]

        # 输出响应内容
        if response_content:
            if isinstance(response_content, list):
                for block in response_content:
                    if isinstance(block, dict) and "text" in block:
                        print(block["text"])
            else:
                print(response_content)

        print()


if __name__ == "__main__":
    main()
