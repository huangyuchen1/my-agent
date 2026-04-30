"""
TodoManager - 待办事项管理模块
独立管理待办事项状态，用于任务规划和进度追踪
"""


class TodoManager:
    """待办事项管理器"""

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """更新待办事项列表"""
        if len(items) > 20:
            raise ValueError("Max 20 todos allow")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        """渲染待办事项和状态给用户看"""
        if not self.items:
            return "No todos"
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


# 全局单例
TODO = TodoManager()
