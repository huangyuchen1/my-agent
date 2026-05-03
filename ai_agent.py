"""
AI Agent - 对接 Moonshot AI (Kimi) 大模型的简单对话助手
支持联网搜索和控制台操作功能
"""
import json
import os
import time
from typing import Any, Dict, List

from openai import OpenAI

from tool_dispatcher import dispatcher
from ui_utils import start_status, stop_status
from exception_handler import classify_error, format_error_for_display


MODEL = "kimi-k2.5"
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY", "sk-0cJM2iDt54p4AA4qUSZCHH57mpyDNx8Gq6VkBojyN7JqEklG"),
    base_url="https://api.moonshot.cn/v1"
)

rounds_since_todo = 0


def _format_duration(seconds: float) -> str:
    """格式化时长显示"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}分{secs:.1f}秒"


def agent_loop(messages: List[Dict[str, Any]]) -> None:
    """
    核心 Agent 循环模式:
    while stop_reason == "tool_calls":
        response = LLM(messages, tools)
        execute tools
        append results
    """
    global rounds_since_todo
    total_rounds = 0
    loop_start_time = time.time()

    while True:
        total_rounds += 1

        if rounds_since_todo >= 3 and messages:
            _inject_todo_reminder(messages)

        thinking_msg = f"思考中 (第 {total_rounds} 轮)"
        if total_rounds == 1:
            thinking_msg = "正在思考你的问题..."
        start_status(thinking_msg)

        request_params = {
            "model": MODEL,
            "messages": messages,
            "tools": dispatcher.get_all_tools(),
            "max_tokens": 32768,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        completion = _call_model_with_retry(request_params, thinking_msg)
        if completion is None:
            return

        choice = completion.choices[0]

        assistant_msg = _build_assistant_message(choice.message)
        messages.append(assistant_msg)

        if choice.finish_reason != "tool_calls":
            return

        start_status(_build_tools_preview(choice.message.tool_calls))

        results = _execute_tool_calls(choice.message.tool_calls)
        stop_status(success=True, final_msg=f"工具调用完成 ({len(results)}个工具)")

        _append_tool_results(messages, choice.message.tool_calls, results)


def _inject_todo_reminder(messages: List[Dict[str, Any]]) -> None:
    """注入待办事项提醒"""
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


def _call_model_with_retry(request_params: Dict[str, Any], thinking_msg: str):
    """调用模型，支持限流重试"""
    global rounds_since_todo
    MAX_RETRIES = 3
    BASE_DELAY = 2.0

    for attempt in range(MAX_RETRIES):
        try:
            completion = client.chat.completions.create(**request_params)
            stop_status(success=True, final_msg="思考完成 ✓")
            return completion
        except Exception as e:
            category, user_msg, can_retry, status_code = classify_error(e)
            
            if can_retry and attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (1.5 ** attempt)
                stop_status(success=False, final_msg="")
                print(f"\n\033[33m[限流] {user_msg}，{delay:.1f}秒后重试... ({attempt + 1}/{MAX_RETRIES})\033[0m")
                time.sleep(delay)
                start_status(thinking_msg)
            else:
                stop_status(success=False, final_msg="")
                error_display = format_error_for_display(e)
                print(f"\n\033[31m[API错误] {error_display}\033[0m")
                return None


def _build_assistant_message(message) -> Dict[str, Any]:
    """构建助手消息"""
    assistant_msg = {
        "role": "assistant",
        "content": message.content or "",
    }
    if message.tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            }
            for tc in message.tool_calls
        ]
    return assistant_msg


def _build_tools_preview(tool_calls) -> str:
    """构建工具预览字符串"""
    tool_names = [tc.function.name for tc in tool_calls]
    preview = ", ".join(tool_names[:3])
    if len(tool_names) > 3:
        preview += f" (+{len(tool_names) - 3}个)"
    return f"正在调用工具: {preview}"


def _execute_tool_calls(tool_calls) -> List[Dict[str, Any]]:
    """执行工具调用"""
    global rounds_since_todo
    results = []

    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        print(f"\n\033[33m$ {tool_name}({json.dumps(tool_args)[:100]}...)\033[0m")

        if tool_name == "$web_search":
            output = json.dumps(tool_args)
        else:
            output = dispatcher.run_tool(tool_name, tool_args)

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

    return results


def _append_tool_results(messages: List[Dict[str, Any]], tool_calls, results) -> None:
    """追加工具结果到消息列表"""
    for tc, result in zip(tool_calls, results):
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

        history.append({"role": "user", "content": query})

        start_time = time.time()
        try:
            agent_loop(history)
        except Exception as e:
            error_display = format_error_for_display(e, show_technical=True)
            print(f"\n\033[31m[错误] {error_display}\033[0m")
            continue

        response_content = history[-1]["content"]

        if response_content:
            if isinstance(response_content, list):
                for block in response_content:
                    if isinstance(block, dict) and "text" in block:
                        print(block["text"])
            else:
                print(response_content)

        duration = time.time() - start_time
        print(f"\n\033[35m[耗时] 本轮对话总时长: {_format_duration(duration)}\033[0m")
        print()


if __name__ == "__main__":
    main()
