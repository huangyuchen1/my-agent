"""
TranscriptManager - transcript 文件的读写和清理
由 context/compactor.py 调用
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

# 上下文存储目录（相对于项目根目录）
CONTEXT_DIR = Path(__file__).parent.parent.parent / "storage" / ".context"


def ensure_context_dir() -> Path:
    """确保上下文目录存在，返回 transcripts 子目录"""
    transcripts_dir = CONTEXT_DIR / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    return transcripts_dir


def save_transcript(messages: List[Dict[str, Any]]) -> Path:
    """
    保存完整对话到 .context/transcripts/ 目录。
    返回保存的文件路径。
    """
    transcripts_dir = ensure_context_dir()
    timestamp = int(time.time() * 1000)
    path = transcripts_dir / f"transcript_{timestamp}.jsonl"

    with open(path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")

    return path


def list_transcripts() -> List[Dict[str, Any]]:
    """列出所有 transcript 文件的元信息"""
    transcripts_dir = CONTEXT_DIR / "transcripts"
    if not transcripts_dir.exists():
        return []

    result = []
    for f in sorted(transcripts_dir.iterdir()):
        if f.suffix == ".jsonl":
            result.append({
                "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
            })
    return result


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


def load_transcript(path: Path) -> List[Dict[str, Any]]:
    """加载指定 transcript 文件的内容"""
    messages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages
