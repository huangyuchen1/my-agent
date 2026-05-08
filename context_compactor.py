"""
ContextCompactor - 三层上下文压缩系统
Layer 1 (micro_compact):   静默执行，每轮都触发，将旧 tool_result 替换为占位符
Layer 2 (auto_compact):    token 超过阈值时自动触发，保存完整对话到磁盘并摘要
Layer 3 (manual_compact):  通过 compact 工具手动触发，执行与 auto_compact 相同的摘要
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_current_model_config


def _get_compact_client():
    """从 dispatcher 获取摘要用 LLM client"""
    try:
        from tool_dispatcher import dispatcher
        return dispatcher._compact_client
    except Exception:
        return None


# ======================
# 配置常量
# ======================
CONTEXT_DIR = Path(".context")                    # 上下文存储目录
AUTO_COMPACT_TOKEN_THRESHOLD = 60000              # 自动压缩的 token 阈值
MICRO_COMPACT_KEEP_RECENT = 3                    # micro_compact 保留最近 N 个 tool_result
MAX_TOOL_RESULT_PREVIEW = 120                    # tool_result 替换时的最大预览字符数
SUMMARY_MAX_TOKENS = 3000                         # 摘要模型输出的最大 token 数
TRANSCRIPT_MAX_SIZE_MB = 50                       # 单个 transcript 文件最大体积（MB），超过则拆分


# ======================
# Layer 1: Micro Compact
# ======================

def micro_compact(messages: List[Dict[str, Any]]) -> int:
    """
    Layer 1 - 微压缩：每次 LLM 调用前静默执行。
    将超过 KEEP_RECENT 数量的旧 tool_result 替换为占位符。

    返回值: 被压缩的 tool_result 数量
    """
    # 收集所有 tool_result 及其位置
    tool_result_positions = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_PREVIEW:
            tool_result_positions.append(i)

    if len(tool_result_positions) <= MICRO_COMPACT_KEEP_RECENT:
        return 0

    # 保留最近 KEEP_RECENT 个，压缩更旧的
    to_compact = tool_result_positions[:len(tool_result_positions) - MICRO_COMPACT_KEEP_RECENT]
    count = 0
    for i in to_compact:
        msg = messages[i]
        content = msg.get("content", "")
        # 提取工具名（如果消息有 name 字段）
        tool_name = msg.get("name", "tool")
        # 生成占位符：保留前 80 字符预览 + 信息摘要
        preview = content[:80].replace("\n", " ").strip()
        truncated_content = f"[Previous: used {tool_name}] {preview}... (truncated, {len(content)} chars)"

        # 对于超长内容，尝试进一步压缩
        if len(content) > 2000:
            msg["content"] = truncated_content
        else:
            msg["content"] = content[:MAX_TOOL_RESULT_PREVIEW]
        msg["_compacted"] = True
        count += 1

    return count


# ======================
# Token 估算
# ======================

def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """
    估算消息列表的 token 数量。
    使用粗略估算：中文 ≈ 2 chars/token，英文/代码 ≈ 4 chars/token。
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += _estimate_str_tokens(part.get("text", ""))
                elif isinstance(part, str):
                    total += _estimate_str_tokens(part)
        elif isinstance(content, str):
            total += _estimate_str_tokens(content)

        # tool_calls 也占 token
        if msg.get("tool_calls"):
            total += _estimate_str_tokens(json.dumps(msg["tool_calls"]))

    return total


def _estimate_str_tokens(s: str) -> int:
    """估算单个字符串的 token 数量"""
    chinese = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
    other = len(s) - chinese
    return chinese // 2 + other // 4


# ======================
# Layer 2 & 3: Auto / Manual Compact
# ======================

def auto_compact(
    messages: List[Dict[str, Any]],
    client=None,
    system_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Layer 2 - 自动压缩：token 超过阈值时触发。
    Layer 3 - 手动压缩：compact 工具触发，逻辑相同。

    保存完整对话到 .context/transcripts/，
    然后调用 LLM 摘要，替换消息列表为摘要消息。

    返回: {
        "compacted": bool,
        "original_tokens": int,
        "summary_tokens": int,
        "transcript_path": str,
        "method": "auto" | "manual",
    }
    """
    original_tokens = estimate_tokens(messages)
    method = "auto"

    # 1. 保存完整对话到磁盘
    transcript_path = _save_transcript(messages)

    # 2. 构建摘要请求
    summary_prompt = _build_summary_prompt(messages, system_prompt)

    # 3. 调用 LLM 摘要（优先用传入的 client，否则从 dispatcher 获取）
    effective_client = client if client is not None else _get_compact_client()
    summary_text, summary_tokens = _summarize_with_llm(summary_prompt, effective_client)

    # 4. 构建压缩后的消息列表：只保留 system + 摘要
    summary_msg = {
        "role": "user",
        "content": (
            f"[Context Compressed — {method}]\n\n"
            f"--- Original conversation summary ---\n"
            f"{summary_text}\n\n"
            f"--- End of summary ---\n\n"
            f"Full transcript saved at: {transcript_path}\n"
            f"Original tokens: ~{original_tokens}"
        ),
        "_context_compacted": True,
        "_transcript_path": transcript_path,
    }

    compressed_messages = [summary_msg]

    return {
        "compacted": True,
        "original_tokens": original_tokens,
        "summary_tokens": summary_tokens,
        "transcript_path": str(transcript_path),
        "method": method,
        "compressed_messages": compressed_messages,
    }


def manual_compact(
    messages: List[Dict[str, Any]],
    client=None,
    system_prompt: Optional[str] = None,
    instruction: Optional[str] = None
) -> Dict[str, Any]:
    """
    Layer 3 - 手动压缩：由 compact 工具触发。
    与 auto_compact 相同，但支持额外的用户指令来指导摘要方向。
    """
    original_tokens = estimate_tokens(messages)
    method = "manual"

    transcript_path = _save_transcript(messages)

    summary_prompt = _build_summary_prompt(messages, system_prompt, instruction=instruction)

    effective_client = client if client is not None else _get_compact_client()
    summary_text, summary_tokens = _summarize_with_llm(summary_prompt, effective_client)

    summary_msg = {
        "role": "user",
        "content": (
            f"[Context Compressed — {method}]\n\n"
            f"--- Original conversation summary ---\n"
            f"{summary_text}\n\n"
            f"--- End of summary ---\n\n"
            f"Full transcript saved at: {transcript_path}\n"
            f"Original tokens: ~{original_tokens}"
        ),
        "_context_compacted": True,
        "_transcript_path": transcript_path,
    }

    return {
        "compacted": True,
        "original_tokens": original_tokens,
        "summary_tokens": summary_tokens,
        "transcript_path": str(transcript_path),
        "method": method,
        "compressed_messages": [summary_msg],
    }


# ======================
# 辅助函数
# ======================

def _save_transcript(messages: List[Dict[str, Any]]) -> Path:
    """保存完整对话到 .context/transcripts/ 目录"""
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    transcripts_dir = CONTEXT_DIR / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time() * 1000)
    path = transcripts_dir / f"transcript_{timestamp}.jsonl"

    with open(path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")

    return path


def _build_summary_prompt(
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    instruction: Optional[str] = None
) -> str:
    """
    构建摘要提示词。
    要求 LLM 用中文输出一个结构化的对话摘要。
    """
    # 过滤掉已被 micro_compact 压缩过的消息的 _compacted 标记内容（但保留原始内容用于摘要）
    # 我们使用原始内容，所以不过滤
    pass

    instruction_part = (
        f"\n\n额外指导: {instruction}" if instruction else ""
    )

    # 构造摘要用的消息摘要文本（不含 tool_calls 详情，减少 token 消耗）
    msg_summaries = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
            content = f"[tool_calls: {', '.join(tc_names)}] {content}"

        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content = f"[tool result for {tool_call_id}]: {str(content)[:200]}"
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                content = f"[used tools: {', '.join(tc_names)}] {content}"

        msg_summaries.append(f"[{role}] {content}")

    # 限制输入 token，避免超过模型限制
    combined = "\n".join(msg_summaries)
    max_chars = 60000  # 约 15k-20k token
    if len(combined) > max_chars:
        combined = combined[:max_chars] + f"\n... [truncated, total {len(combined)} chars]"

    prompt = (
        "你是一个对话摘要助手。请用中文将以下对话历史压缩为一个结构化摘要。\n"
        "摘要应该包含：\n"
        "1. 对话的整体主题和目标\n"
        "2. 已完成的关键操作和结果\n"
        "3. 当前的进行状态\n"
        "4. 任何重要的决策、发现或结论\n"
        "5. 未完成的事项或下一步计划\n\n"
        "要求：简洁、有条理，保留关键信息，删除冗余细节。\n"
        f"{instruction_part}\n\n"
        "--- 对话历史 ---\n"
        f"{combined}\n"
        "--- 摘要 ---\n"
    )
    return prompt


def _summarize_with_llm(
    prompt: str,
    client=None,
    fallback_to_simple: bool = True
) -> tuple[str, int]:
    """
    使用 LLM 生成摘要。
    如果 client 为 None，尝试从 dispatcher 获取。
    如果调用失败，使用简单提取作为降级方案。
    返回: (summary_text, estimated_tokens)
    """
    effective_client = client if client is not None else _get_compact_client()
    if effective_client is not None:
        try:
            model_config = get_current_model_config()
            response = effective_client.chat.completions.create(
                model=model_config.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=SUMMARY_MAX_TOKENS,
                temperature=0.3,
            )
            summary_text = response.choices[0].message.content or ""
            summary_tokens = _estimate_str_tokens(summary_text)
            return summary_text, summary_tokens
        except Exception as e:
            print(f"\033[33m[ContextCompactor] LLM 摘要失败: {e}，使用简单摘要\033[0m")

    if fallback_to_simple:
        return _simple_summary(prompt)

    return "[摘要生成失败]", 5


def _simple_summary(prompt: str) -> tuple[str, int]:
    """
    降级方案：从 prompt 中提取关键信息生成简单摘要。
    """
    lines = prompt.split("\n")
    # 提取有意义的行（排除提示词指令）
    meaningful = [
        line.strip() for line in lines
        if line.strip()
        and not line.strip().startswith("你是一个")
        and not line.strip().startswith("摘要应该")
        and not line.strip().startswith("要求：")
        and not line.strip().startswith("---")
        and len(line.strip()) > 10
    ]

    summary = "[简单摘要] 对话历史较长，关键信息请参考原始 transcript。"
    if meaningful:
        # 取中间有意义的部分（前20行）
        core = meaningful[:20]
        summary = "\n".join(core)

    return summary, _estimate_str_tokens(summary)


# ======================
# 压缩检查与执行入口
# ======================

def check_and_compact(
    messages: List[Dict[str, Any]],
    client=None,
    system_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    检查是否需要自动压缩，并在需要时执行。
    返回压缩结果（未压缩时 compacted=False）。

    调用时机: 每次 agent_loop 循环开始时调用。
    """
    current_tokens = estimate_tokens(messages)

    if current_tokens > AUTO_COMPACT_TOKEN_THRESHOLD:
        result = auto_compact(messages, client, system_prompt)
        return result

    return {"compacted": False, "tokens": current_tokens}


# ======================
# 统计与调试
# ======================

def get_context_stats(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """获取当前上下文统计信息"""
    tokens = estimate_tokens(messages)
    msg_count = len(messages)
    tool_result_count = sum(1 for m in messages if m.get("role") == "tool")
    compacted_count = sum(1 for m in messages if m.get("_context_compacted"))

    transcripts = []
    transcripts_dir = CONTEXT_DIR / "transcripts"
    if transcripts_dir.exists():
        for f in sorted(transcripts_dir.iterdir()):
            if f.suffix == ".jsonl":
                transcripts.append({
                    "path": str(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
                })

    return {
        "estimated_tokens": tokens,
        "message_count": msg_count,
        "tool_result_count": tool_result_count,
        "compacted_messages": compacted_count,
        "threshold": AUTO_COMPACT_TOKEN_THRESHOLD,
        "over_threshold": tokens > AUTO_COMPACT_TOKEN_THRESHOLD,
        "transcripts": transcripts,
    }


def cleanup_old_transcripts(max_count: int = 50, max_age_days: int = 7) -> int:
    """
    清理过老或过多的 transcript 文件。
    返回清理的文件数量。
    """
    transcripts_dir = CONTEXT_DIR / "transcripts"
    if not transcripts_dir.exists():
        return 0

    now = time.time()
    removed = 0

    for f in sorted(transcripts_dir.iterdir()):
        if f.suffix != ".jsonl":
            continue
        age_days = (now - f.stat().st_mtime) / 86400
        # 超过 max_age_days 或文件总数超过 max_count 时删除最老的
        if age_days > max_age_days:
            f.unlink()
            removed += 1

    # 按修改时间排序，保留最新的 max_count 个
    all_files = sorted(transcripts_dir.glob("transcript_*.jsonl"), key=lambda f: f.stat().st_mtime)
    if len(all_files) > max_count:
        for f in all_files[:-max_count]:
            f.unlink()
            removed += 1

    return removed
