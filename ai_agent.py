"""
AI Agent - 支持多模型配置的对话助手
支持主代理 + Subagent 架构
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import init_config, get_config, get_current_model_config
from tool_dispatcher import dispatcher
from ui_utils import start_status, stop_status
from exception_handler import classify_error, format_error_for_display
from subagent import SubagentManager, SubagentType, SubagentResult
from skill_loader import get_skill_loader
from context_compactor import (
    micro_compact,
    check_and_compact,
    manual_compact,
    get_context_stats,
    estimate_tokens,
    AUTO_COMPACT_TOKEN_THRESHOLD,
    cleanup_old_transcripts,
)


def get_client() -> OpenAI:
    """获取 OpenAI 客户端（根据当前配置）"""
    config = get_config()
    model_config = config.current_model_config
    return OpenAI(
        api_key=model_config.api_key,
        base_url=model_config.base_url
    )


def get_system_prompt() -> str:
    """获取系统提示词"""
    config = get_config()
    model_config = config.current_model_config
    prompt = model_config.system_prompt
    if "{cwd}" in prompt:
        prompt = prompt.replace("{cwd}", os.getcwd())
    
    skill_loader = get_skill_loader()
    skill_descriptions = skill_loader.get_descriptions()
    if skill_descriptions:
        prompt += "\n\nAvailable Skills:\n" + skill_descriptions
    
    return prompt


# 全局状态
rounds_since_todo = 0
subagent_manager: Optional[SubagentManager] = None
# Layer 3 挂起: compact 工具调用后，在本轮结束时执行压缩
_pending_compact_instruction: Optional[str] = None


def get_subagent_manager() -> SubagentManager:
    """获取或创建子代理管理器"""
    global subagent_manager
    if subagent_manager is None:
        subagent_manager = SubagentManager(get_client())
    return subagent_manager


def _format_duration(seconds: float) -> str:
    """格式化时长显示"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}分{secs:.1f}秒"


def agent_loop(messages: List[Dict[str, Any]], use_subagent: bool = True) -> None:
    """
    核心 Agent 循环模式:
    while stop_reason == "tool_calls":
        response = LLM(messages, tools)
        execute tools
        append results

    三层上下文压缩:
    - Layer 1 (micro_compact):   静默执行，每轮开始前将旧 tool_result 替换为占位符
    - Layer 2 (auto_compact):    token 超过阈值时自动触发，保存完整对话并摘要
    - Layer 3 (manual_compact):  compact 工具调用后触发，同 auto_compact 但由用户主动触发

    Args:
        messages: 消息历史
        use_subagent: 是否启用子代理功能
    """
    global rounds_since_todo, _pending_compact_instruction
    total_rounds = 0
    # 清理过老的 transcripts（每次会话最多清理一次）
    cleanup_done = False

    while True:
        total_rounds += 1

        if not cleanup_done:
            removed = cleanup_old_transcripts()
            if removed > 0:
                print(f"\n\033[33m[ContextCompactor] 清理了 {removed} 个过老的 transcript 文件\033[0m")
            cleanup_done = True

        # Layer 1: micro_compact — 静默执行，替换旧 tool_result 为占位符
        compacted_count = micro_compact(messages)
        if compacted_count > 0:
            print(f"\n\033[33m[Layer-1 micro_compact] 已将 {compacted_count} 个旧 tool_result 压缩为占位符\033[0m")

        # Layer 2: auto_compact — token 超过阈值时自动压缩
        if total_rounds == 1:  # 只在第一轮检查，避免重复压缩
            compact_result = check_and_compact(messages, client=get_client(), system_prompt=get_system_prompt())
            if compact_result.get("compacted"):
                messages[:] = compact_result["compressed_messages"]
                stats = get_context_stats(messages)
                print(
                    f"\n\033[35m[Layer-2 auto_compact] 上下文已自动压缩 "
                    f"(原 ~{compact_result['original_tokens']} token → 摘要 ~{compact_result['summary_tokens']} token)\033[0m"
                )
                print(f"\033[35m[Layer-2] 完整记录: {compact_result['transcript_path']}\033[0m")
                print(f"\033[35m[Layer-2] 当前上下文: ~{stats['estimated_tokens']} token\033[0m")

        if rounds_since_todo >= 3 and messages:
            _inject_todo_reminder(messages)

        thinking_msg = f"思考中 (第 {total_rounds} 轮)"
        if total_rounds == 1:
            thinking_msg = "正在思考你的问题..."
        start_status(thinking_msg)

        model_config = get_current_model_config()
        request_params = {
            "model": model_config.model_id,
            "messages": messages,
            "tools": dispatcher.get_all_tools(),
            "max_tokens": model_config.max_tokens,
        }

        # 添加 thinking 配置（如果模型支持）
        if model_config.thinking_type:
            request_params["extra_body"] = {"thinking": {"type": model_config.thinking_type}}

        completion = _call_model_with_retry(request_params, thinking_msg)
        if completion is None:
            return

        choice = completion.choices[0]

        assistant_msg = _build_assistant_message(choice.message)
        messages.append(assistant_msg)

        if choice.finish_reason != "tool_calls":
            return

        start_status(_build_tools_preview(choice.message.tool_calls))

        # 检查是否有子代理调用
        if use_subagent:
            results = _execute_with_subagent_support(choice.message.tool_calls, messages)
        else:
            results = _execute_tool_calls(choice.message.tool_calls)

        stop_status(success=True, final_msg=f"工具调用完成 ({len(results)}个工具)")

        _append_tool_results(messages, choice.message.tool_calls, results)

        # Layer 3: 执行挂起的手动压缩（compact 工具被调用）
        if _pending_compact_instruction is not None or any(
            tc.function.name == "compact" for tc in choice.message.tool_calls
        ):
            instruction = _pending_compact_instruction
            _pending_compact_instruction = None
            compact_result = manual_compact(
                messages,
                client=get_client(),
                system_prompt=get_system_prompt(),
                instruction=instruction,
            )
            messages[:] = compact_result["compressed_messages"]
            stats = get_context_stats(messages)
            print(
                f"\n\033[35m[Layer-3 manual_compact] 上下文已压缩 "
                f"(原 ~{compact_result['original_tokens']} token → 摘要 ~{compact_result['summary_tokens']} token)\033[0m"
            )
            print(f"\033[35m[Layer-3] 完整记录: {compact_result['transcript_path']}\033[0m")
            print(f"\033[35m[Layer-3] 当前上下文: ~{stats['estimated_tokens']} token\033[0m")
            print("\033[36m压缩完成，Agent 将在下一轮使用压缩后的上下文继续工作\033[0m")


def _execute_with_subagent_support(tool_calls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    执行工具调用，支持子代理能力
    当检测到 spawn_subagent 工具调用时，创建并运行子代理
    """
    global rounds_since_todo, _pending_compact_instruction
    results = []

    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        # Layer 3 挂起: 检测到 compact 工具调用，记录指令但不立即执行
        if tool_name == "compact":
            _pending_compact_instruction = tool_args.get("instruction")
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps({"status": "compact queued", "instruction": _pending_compact_instruction}, ensure_ascii=False),
            })
            print(f"\n\033[33m$ compact(instruction={_pending_compact_instruction})\033[0m")
            print("压缩已加入队列，将在当前轮次结束后执行...")
            rounds_since_todo += 1
            continue

        print(f"\n\033[33m$ {tool_name}({json.dumps(tool_args)[:100]}...)\033[0m")

        # Layer 3 挂起: context_stats 工具
        if tool_name == "context_stats":
            stats = get_context_stats(messages)
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps(stats, ensure_ascii=False, indent=2),
            })
            print(f"\n\033[33m$ context_stats()\033[0m")
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            rounds_since_todo += 1
            continue

        # 处理 spawn_subagent 工具
        if tool_name == "spawn_subagent":
            output = _handle_spawn_subagent(tool_args)
        elif tool_name == "$web_search":
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


def _handle_spawn_subagent(args: Dict[str, Any]) -> str:
    """
    处理子代理创建和执行

    期望参数格式:
    {
        "name": "代码审查",
        "type": "review",  // explore, execute, research, review, general
        "task": "审查 src/main.py 的代码质量",
        "max_rounds": 10,
        "parent_context": {...}  // 可选，父代理上下文
    }
    """
    manager = get_subagent_manager()

    name = args.get("name", f"subagent_{int(time.time())}")
    subagent_type_str = args.get("type", "general")
    task = args.get("task", "")
    #最大循环对话循环数，防止子agent任务卡死
    max_rounds = args.get("max_rounds", 10)
    parent_context = args.get("parent_context", {})

    # 转换类型字符串到枚举
    try:
        subagent_type = SubagentType(subagent_type_str.lower())
    except ValueError:
        subagent_type = SubagentType.GENERAL

    # 获取工具列表，但过滤掉 spawn_subagent 防止子代理创建孙代理
    all_tools = dispatcher.get_all_tools()
    tools = [t for t in all_tools if t.get("function", {}).get("name") != "spawn_subagent"]

    # 创建子代理（不包含 spawn_subagent 工具）
    agent_id = manager.create_subagent(
        name=name,
        subagent_type=subagent_type,
        tools=tools,
        max_rounds=max_rounds,
        parent_context=parent_context
    )

    print(f"\n\033[36m[Subagent] 创建子代理: {name} ({agent_id})\033[0m")

    # 运行子代理任务
    start_time = time.time()
    result = manager.run_task(agent_id, task)
    duration = time.time() - start_time

    # 构建结果摘要
    status = "成功" if result.success else "失败"
    summary = {
        "agent_id": agent_id,
        "name": name,
        "type": subagent_type.value,
        "status": status,
        "success": result.success,
        "rounds": result.rounds,
        "duration": _format_duration(result.duration),
        "summary": result.summary,
        "error": result.error
    }

    print(f"\n\033[36m[Subagent] {name} 执行完成: {status} (轮次: {result.rounds}, 耗时: {_format_duration(result.duration)})\033[0m")

    return json.dumps(summary, ensure_ascii=False, indent=2)


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
            client = get_client()
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
    # 初始化配置
    config = init_config()

    model_name = config.current_model_config.name
    model_id = config.current_model_config.model_id

    print("=" * 60)
    print("        AI Agent - 多模型对话助手")
    print(f"        当前模型: {model_name} ({model_id})")
    print("=" * 60)
    print("\n功能:")
    print("  - 基础工具: ls, git, python, 文件读写等")
    print("  - 子代理: spawn_subagent 工具可创建专门的子代理")
    print("\n子代理类型:")
    print("  - explore: 代码探索")
    print("  - execute: 任务执行")
    print("  - research: 深度研究")
    print("  - review: 代码审查")
    print("\n提示:")
    print("  - 输入 'q' 或 'quit' 退出")
    print("  - 输入 'agents' 查看活跃子代理")
    print("  - 输入 'models' 查看可用模型")
    print("  - 输入 'switch <model>' 切换模型\n")

    history = [{
        "role": "system",
        "content": get_system_prompt()
    }]

    # 设置 dispatcher 的 LLM client 用于摘要生成（Layer 2/3）
    dispatcher.set_compact_client(get_client())

    manager = get_subagent_manager()

    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        if query.strip().lower() == "agents":
            active = manager.list_active()
            if active:
                print("\n[活跃子代理]")
                for agent in active:
                    print(f"  - {agent['id']}: {agent['name']}")
            else:
                print("\n[无活跃子代理]")
            print()
            continue

        if query.strip().lower() == "models":
            print("\n[可用模型]")
            for name in config.available_models:
                current = " (当前)" if name == config.current_model_config.name else ""
                print(f"  - {name}{current}")
            print()
            continue

        if query.strip().lower().startswith("switch "):
            target_model = query.strip()[7:].strip()
            if config.set_model(target_model):
                # 重置子代理管理器以使用新配置
                global subagent_manager
                subagent_manager = None
                # 重新获取 manager 以使用新配置
                manager = get_subagent_manager()
                # 更新系统提示词
                history = [{
                    "role": "system",
                    "content": get_system_prompt()
                }]
                model_name = config.current_model_config.name
                model_id = config.current_model_config.model_id
                print(f"\n\033[32m[切换] 已切换到模型: {model_name} ({model_id})\033[0m\n")
            else:
                print(f"\n\033[31m[错误] 未知的模型: {target_model}\033[0m")
                print(f"可用模型: {', '.join(config.available_models)}\n")
            continue

        history.append({"role": "user", "content": query})

        start_time = time.time()
        try:
            agent_loop(history, use_subagent=True)
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
