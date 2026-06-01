"""
AI Agent - 支持多模型配置的对话助手
支持主代理 + Subagent 架构
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.core.config import init_config, get_config, get_current_model_config
from src.tools.dispatcher import dispatcher
from src.ui.spinner import start_status, stop_status
from src.core.exception_handler import classify_error, format_error_for_display
from src.core.skill_loader import get_skill_loader
from src.core.background_manager import BG
from src.subagent.message_bus import BUS
from src.subagent.teammate_manager import TM
from src.context.compactor import (
    micro_compact,
    check_and_compact,
    manual_compact,
    get_context_stats,
    estimate_tokens,
    AUTO_COMPACT_TOKEN_THRESHOLD,
)
from src.context.transcript import cleanup_old_transcripts
from src.web.event_bus import EventType


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
_pending_compact_instruction: Optional[str] = None


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
    global _pending_compact_instruction
    total_rounds = 0
    cleanup_done = False

    while True:
        total_rounds += 1

        # === 新增：排空后台任务通知队列 ===
        notifs = BG.drain_notifications()
        if notifs:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] command={n['command'][:60]}... "
                f"completed with exit code {n['returncode']}\n"
                f"result: {n['result']}"
                for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{notif_text}\n</background-results>"
            })
            print(f"\n\033[32m[后台任务] {len(notifs)} 个任务已完成，已注入通知\033[0m")
        # ==================================

        # === 新增：检查队友收件箱 ===
        inbox = BUS.read_inbox("lead")
        if inbox != "[]":
            messages.append({
                "role": "user",
                "content": f"<inbox>\n{inbox}\n</inbox>"
            })
            count = BUS.get_inbox_count("lead")
            print(f"\n\033[32m[Team] 收到 {count} 条队友消息\033[0m")
        # ==================================

        if not cleanup_done:
            removed = cleanup_old_transcripts()
            if removed > 0:
                print(f"\n\033[33m[ContextCompactor] 清理了 {removed} 个过老的 transcript 文件\033[0m")
            cleanup_done = True

        compacted_count = micro_compact(messages)
        if compacted_count > 0:
            print(f"\n\033[33m[Layer-1 micro_compact] 已将 {compacted_count} 个旧 tool_result 压缩为占位符\033[0m")

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

        if model_config.thinking_type:
            request_params["extra_body"] = {"thinking": {"type": model_config.thinking_type}}
        
        request_params["stream"] = True
        completion = _call_model_with_retry(request_params, thinking_msg)
        if completion is None:
            return

        # 先收集所有 chunks，再处理
        chunks_list = []

        # 流式打印文字内容
        for chunk in completion:
            chunks_list.append(chunk)
            delta = chunk.choices[0].delta
            if delta.content:
                print(delta.content, end="", flush=True)
        print()  # 流结束后换行

        # 从 chunks 重建完整响应对象
        assistant_msg, tool_calls = _rebuild_response_from_chunks(chunks_list)
        messages.append(assistant_msg)

        if not tool_calls:
            return

        start_status(_build_tools_preview(tool_calls))

        if use_subagent:
            results = _execute_with_subagent_support(tool_calls, messages)
        else:
            results = _execute_tool_calls(tool_calls)

        stop_status(success=True, final_msg=f"工具调用完成 ({len(results)}个工具)")

        _append_tool_results(messages, tool_calls, results)

        if _pending_compact_instruction is not None or any(
            tc["function"]["name"] == "compact" for tc in tool_calls
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


def _execute_with_subagent_support(tool_calls: List[Dict], messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """执行工具调用，支持子代理能力"""
    global _pending_compact_instruction
    results = []
    dispatcher._current_sender = "lead"

    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        if tool_name == "compact":
            _pending_compact_instruction = tool_args.get("instruction")
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": json.dumps({"status": "compact queued", "instruction": _pending_compact_instruction}, ensure_ascii=False),
            })
            print(f"\n\033[33m$ compact(instruction={_pending_compact_instruction})\033[0m")
            print("压缩已加入队列，将在当前轮次结束后执行...")
            continue

        print(f"\n\033[33m$ {tool_name}({json.dumps(tool_args)[:100]}...)\033[0m")

        if tool_name == "context_stats":
            stats = get_context_stats(messages)
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps(stats, ensure_ascii=False, indent=2),
            })
            print(f"\n\033[33m$ context_stats()\033[0m")
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            continue

        if tool_name == "spawn_subagent":
            output = json.dumps({"error": "spawn_subagent 已废弃，请使用 team_spawn"})
        elif tool_name == "$web_search":
            output = json.dumps(tool_args)
        else:
            output = dispatcher.run_tool(tool_name, tool_args)

        print(output[:300] if output else "(no output)")

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_call["id"],
            "content": output,
        })

    return results


def _call_model_with_retry(request_params: Dict[str, Any], thinking_msg: str):
    """调用模型，支持限流重试"""
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


def _rebuild_response_from_chunks(chunks_list):
    """
    从流式 chunks 重建完整响应
    返回: (assistant_msg_dict, tool_calls_list)
    """
    full_content = ""
    collected_tool_calls = {}  # index -> data

    for chunk in chunks_list:
        delta = chunk.choices[0].delta

        # 收集文字内容
        if delta.content:
            full_content += delta.content

        # 收集 tool_calls（流式传输时需要拼接）
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in collected_tool_calls:
                    collected_tool_calls[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""}
                    }
                tc = collected_tool_calls[idx]
                if tc_delta.id:
                    tc["id"] += tc_delta.id
                if tc_delta.function.name:
                    tc["function"]["name"] += tc_delta.function.name
                if tc_delta.function.arguments:
                    tc["function"]["arguments"] += tc_delta.function.arguments

    # 构建 assistant 消息
    assistant_msg = {"role": "assistant", "content": full_content}

    # 构建 tool_calls 列表（按 index 排序）
    tool_calls_list = []
    if collected_tool_calls:
        for idx in sorted(collected_tool_calls.keys()):
            tc_data = collected_tool_calls[idx]
            # 创建模拟的 tool_call 对象，带有 id 属性
            tool_calls_list.append(tc_data)

    if tool_calls_list:
        assistant_msg["tool_calls"] = tool_calls_list

    return assistant_msg, tool_calls_list


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
    tool_names = [tc['function']['name'] for tc in tool_calls]
    preview = ", ".join(tool_names[:3])
    if len(tool_names) > 3:
        preview += f" (+{len(tool_names) - 3}个)"
    return f"正在调用工具: {preview}"


def _execute_tool_calls(tool_calls: List[Dict]) -> List[Dict[str, Any]]:
    """执行工具调用（无子代理支持）"""
    results = []
    dispatcher._current_sender = "lead"

    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        print(f"\n\033[33m$ {tool_name}({json.dumps(tool_args)[:100]}...)\033[0m")

        if tool_name == "$web_search":
            output = json.dumps(tool_args)
        else:
            output = dispatcher.run_tool(tool_name, tool_args)

        print(output[:300] if output else "(no output)")

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_call["id"],
            "content": output,
        })

    return results


def _append_tool_results(messages: List[Dict[str, Any]], tool_calls: List[Dict], results: List[Dict[str, Any]]) -> None:
    """追加工具结果到消息列表"""
    for tc, result in zip(tool_calls, results):
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result["content"],
        })


def main():
    """主函数 - 命令行交互界面"""
    config = init_config()

    model_name = config.current_model_config.name
    model_id = config.current_model_config.model_id

    print("=" * 60)
    print("        AI Agent - 多模型对话助手")
    print(f"        当前模型: {model_name} ({model_id})")
    print("=" * 60)
    print("\n功能:")
    print("  - 基础工具: bash, read_file, write_file, list_dir, glob 等")
    print("  - 任务系统: task_create / task_update / task_list / task_get")
    print("  - 后台任务: background_run / background_status")
    print("  - Agent Team: team_spawn / team_send / team_inbox / team_list / team_shutdown")
    print("\n任务系统:")
    print("  - task_create: 创建任务，支持 blocked_by 指定前置依赖")
    print("  - task_update: 更新状态（pending -> in_progress -> completed）")
    print("  - task_list:   查看所有任务及 DAG 状态")
    print("  - task_get:    查看单个任务详情")
    print("  - 任务持久化到 storage/.tasks/，跨压缩和重启存活")
    print("\n提示:")
    print("  - 输入 'q' 或 'quit' 退出")
    print("  - 输入 'team' 查看团队成员状态")
    print("  - 输入 'models' 查看可用模型")
    print("  - 输入 'switch <model>' 切换模型\n")

    history = [{
        "role": "system",
        "content": get_system_prompt()
    }]

    dispatcher.set_compact_client(get_client())

    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        if query.strip().lower() == "team":
            members = TM.list_members()
            if members:
                print("\n[团队成员]")
                for m in members:
                    print(f"  - {m['name']} ({m['role']}): {m['status']}")
            else:
                print("\n[无团队成员]")
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


# ============================================================
# Web 模式：带事件发射的 agent_loop 版本
# ============================================================

def agent_loop_with_events(
    messages: List[Dict[str, Any]],
    event_bus,
    use_subagent: bool = True
) -> None:
    """
    Web 模式的 Agent 循环，通过 EventBus 发送所有事件到前端。

    与 agent_loop() 逻辑相同，但在关键节点插入事件发射：
    - 流式 chunk -> STREAM_CHUNK
    - 工具调用 -> TOOL_START / TOOL_RESULT
    - 系统通知 -> BACKGROUND_NOTIFICATION / TEAM_INBOX

    Args:
        messages: 消息历史
        event_bus: EventBus 实例
        use_subagent: 是否启用子代理功能
    """
    global _pending_compact_instruction
    total_rounds = 0
    cleanup_done = False

    # 发送启动事件
    event_bus.publish(EventType.AGENT_START, {"rounds": 0})

    while True:
        total_rounds += 1

        # === 排空后台任务通知队列 ===
        notifs = BG.drain_notifications()
        if notifs:
            for n in notifs:
                event_bus.publish(EventType.BACKGROUND_NOTIFICATION, {
                    "task_id": n.get("task_id"),
                    "command": n.get("command", "")[:60],
                    "returncode": n.get("returncode"),
                    "result": n.get("result", "")[:200]
                })
            # 也注入到 messages
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] command={n['command'][:60]}... "
                f"completed with exit code {n['returncode']}\n"
                f"result: {n['result']}"
                for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{notif_text}\n</background-results>"
            })
        # ==================================

        # === 检查队友收件箱 ===
        inbox = BUS.read_inbox("lead")
        if inbox != "[]":
            count = BUS.get_inbox_count("lead")
            event_bus.publish(EventType.TEAM_INBOX, {
                "count": count,
                "messages": inbox[:500]
            })
            messages.append({
                "role": "user",
                "content": f"<inbox>\n{inbox}\n</inbox>"
            })
        # ==================================

        if not cleanup_done:
            removed = cleanup_old_transcripts()
            if removed > 0:
                event_bus.publish(EventType.COMPACT_EVENT, {
                    "layer": 0,
                    "action": "cleanup_old_transcripts",
                    "removed": removed
                })
            cleanup_done = True

        compacted_count = micro_compact(messages)
        if compacted_count > 0:
            event_bus.publish(EventType.COMPACT_EVENT, {
                "layer": 1,
                "action": "micro_compact",
                "count": compacted_count
            })

        compact_result = check_and_compact(messages, client=get_client(), system_prompt=get_system_prompt())
        if compact_result.get("compacted"):
            messages[:] = compact_result["compressed_messages"]
            stats = get_context_stats(messages)
            event_bus.publish(EventType.COMPACT_EVENT, {
                "layer": 2,
                "action": "auto_compact",
                "original_tokens": compact_result["original_tokens"],
                "summary_tokens": compact_result["summary_tokens"],
                "transcript_path": compact_result["transcript_path"],
                "current_tokens": stats["estimated_tokens"]
            })

        # 发送思考开始事件
        event_bus.publish(EventType.THINKING_START, {"round": total_rounds})

        model_config = get_current_model_config()
        request_params = {
            "model": model_config.model_id,
            "messages": messages,
            "tools": dispatcher.get_all_tools(),
            "max_tokens": model_config.max_tokens,
        }

        if model_config.thinking_type:
            request_params["extra_body"] = {"thinking": {"type": model_config.thinking_type}}

        request_params["stream"] = True
        completion = _call_model_with_retry(request_params, f"思考中 (第 {total_rounds} 轮)")
        if completion is None:
            event_bus.publish(EventType.ERROR, {"message": "API 调用失败"})
            event_bus.publish(EventType.AGENT_DONE, {"error": True})
            return

        # 发送思考结束事件
        event_bus.publish(EventType.THINKING_END, {"round": total_rounds})

        # 收集所有 chunks
        chunks_list = []

        # 流式处理：每个 chunk 发送事件
        for chunk in completion:
            chunks_list.append(chunk)
            delta = chunk.choices[0].delta
            if delta.content:
                event_bus.publish(EventType.STREAM_CHUNK, {"content": delta.content})

        # 发送流结束事件
        event_bus.publish(EventType.STREAM_END)

        # 从 chunks 重建完整响应
        assistant_msg, tool_calls = _rebuild_response_from_chunks(chunks_list)
        messages.append(assistant_msg)

        if not tool_calls:
            event_bus.publish(EventType.AGENT_MESSAGE_COMPLETE, {
                "content": assistant_msg.get("content", "")
            })
            event_bus.publish(EventType.AGENT_DONE, {"rounds": total_rounds})
            return

        # 工具调用阶段
        event_bus.publish(EventType.TOOL_START, {
            "count": len(tool_calls),
            "names": [tc["function"]["name"] for tc in tool_calls]
        })

        if use_subagent:
            results = _execute_with_subagent_support_events(tool_calls, messages, event_bus)
        else:
            results = _execute_tool_calls_events(tool_calls, event_bus)

        _append_tool_results(messages, tool_calls, results)

        # 发送工具结束事件
        for tc, result in zip(tool_calls, results):
            event_bus.publish(EventType.TOOL_END, {
                "name": tc["function"]["name"],
                "success": not result.get("error")
            })

        # 处理 compact 工具调用
        if _pending_compact_instruction is not None or any(
            tc["function"]["name"] == "compact" for tc in tool_calls
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
            event_bus.publish(EventType.COMPACT_EVENT, {
                "layer": 3,
                "action": "manual_compact",
                "instruction": instruction,
                "original_tokens": compact_result["original_tokens"],
                "summary_tokens": compact_result["summary_tokens"],
                "transcript_path": compact_result["transcript_path"],
                "current_tokens": stats["estimated_tokens"]
            })


def _execute_with_subagent_support_events(
    tool_calls: List[Dict],
    messages: List[Dict[str, Any]],
    event_bus
) -> List[Dict[str, Any]]:
    """执行工具调用（带事件发射）"""
    global _pending_compact_instruction
    results = []
    dispatcher._current_sender = "lead"

    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        # 发送单个工具开始事件
        event_bus.publish(EventType.TOOL_START, {
            "name": tool_name,
            "arguments": tool_args,
            "id": tool_call["id"]
        })

        if tool_name == "compact":
            _pending_compact_instruction = tool_args.get("instruction")
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": json.dumps({"status": "compact queued", "instruction": _pending_compact_instruction}, ensure_ascii=False),
            })
            event_bus.publish(EventType.TOOL_RESULT, {
                "name": tool_name,
                "result": {"status": "compact queued"}
            })
            continue

        if tool_name == "context_stats":
            stats = get_context_stats(messages)
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": json.dumps(stats, ensure_ascii=False, indent=2),
            })
            event_bus.publish(EventType.TOOL_RESULT, {
                "name": tool_name,
                "result": stats
            })
            continue

        if tool_name == "spawn_subagent":
            output = json.dumps({"error": "spawn_subagent 已废弃，请使用 team_spawn"})
        elif tool_name == "$web_search":
            output = json.dumps(tool_args)
        else:
            output = dispatcher.run_tool(tool_name, tool_args)

        # 发送工具结果事件
        event_bus.publish(EventType.TOOL_RESULT, {
            "name": tool_name,
            "result": output[:500] if output else "(no output)"
        })

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_call["id"],
            "content": output,
        })

    return results


def _execute_tool_calls_events(tool_calls: List[Dict], event_bus) -> List[Dict[str, Any]]:
    """执行工具调用（无子代理支持，带事件发射）"""
    results = []
    dispatcher._current_sender = "lead"

    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        event_bus.publish(EventType.TOOL_START, {
            "name": tool_name,
            "arguments": tool_args,
            "id": tool_call["id"]
        })

        if tool_name == "$web_search":
            output = json.dumps(tool_args)
        else:
            output = dispatcher.run_tool(tool_name, tool_args)

        event_bus.publish(EventType.TOOL_RESULT, {
            "name": tool_name,
            "result": output[:500] if output else "(no output)"
        })

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_call["id"],
            "content": output,
        })

    return results
