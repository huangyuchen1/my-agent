"""
SkillLoader - Skill 加载器
按需加载领域专长知识，实现两层知识注入机制
"""
import re
from pathlib import Path
from typing import Dict, Optional, Tuple


class SkillLoader:
    """
    Skill 加载器 - 递归扫描 skills 目录下的 SKILL.md 文件

    两层知识注入:
    - 第一层: 系统提示中放 Skill 名称和描述 (~100 tokens/skill)
    - 第二层: tool_result 中按需放完整内容 (~2000 tokens)
    """

    def __init__(self, skills_dir: str = "skills"):
        # skills_dir 相对于项目根目录
        self.skills_dir = self._resolve_path(skills_dir)
        self.skills: Dict[str, Dict] = {}
        self._scan_skills()

    def _resolve_path(self, rel_path: str) -> Path:
        """将相对路径解析为相对于项目根目录的绝对路径"""
        p = Path(rel_path)
        if p.is_absolute():
            return p
        # 项目根目录 = src/core/ 的 parent.parent
        return Path(__file__).parent.parent.parent / p

    def _parse_frontmatter(self, text: str) -> Tuple[Dict, str]:
        """解析 YAML frontmatter"""
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(frontmatter_pattern, text, re.DOTALL)

        if match:
            meta_text = match.group(1)
            body = match.group(2)
            meta = {}
            for line in meta_text.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    meta[key.strip()] = value.strip()
            return meta, body.strip()

        return {}, text.strip()

    def _scan_skills(self) -> None:
        """递归扫描所有 SKILL.md 文件"""
        if not self.skills_dir.exists():
            return

        for skill_file in self.skills_dir.rglob("SKILL.md"):
            try:
                text = skill_file.read_text(encoding="utf-8")
                meta, body = self._parse_frontmatter(text)
                name = meta.get("name", skill_file.parent.name)

                self.skills[name] = {
                    "meta": meta,
                    "body": body,
                    "path": str(skill_file),
                    "category": skill_file.parent.name
                }
            except Exception as e:
                print(f"\033[33m[SkillLoader] 加载 Skill 文件失败: {skill_file} - {e}\033[0m")

    def reload(self) -> None:
        """重新扫描 skills 目录"""
        self.skills.clear()
        self._scan_skills()

    def get_descriptions(self) -> str:
        """获取 Skill 描述列表，用于系统提示（第一层注入）"""
        if not self.skills:
            return ""

        lines = []
        for name, skill in sorted(self.skills.items()):
            desc = skill["meta"].get("description", "")
            lines.append(f"  - {name}: {desc}")

        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """获取指定 Skill 的完整内容，用于 tool_result（第二层注入）"""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills.keys())) if self.skills else "无"
            return f"Error: Unknown skill '{name}'. Available skills: {available}"

        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'

    def list_skills(self) -> list:
        """获取所有可用 Skill 的列表"""
        result = []
        for name, skill in sorted(self.skills.items()):
            result.append({
                "name": name,
                "description": skill["meta"].get("description", ""),
                "category": skill.get("category", ""),
                "path": skill.get("path", "")
            })
        return result

    def has_skill(self, name: str) -> bool:
        """检查指定 Skill 是否存在"""
        return name in self.skills

    def get_skill_info(self, name: str) -> Optional[Dict]:
        """获取指定 Skill 的完整信息"""
        return self.skills.get(name)


# 全局单例（延迟初始化）
_skill_loader: Optional[SkillLoader] = None


def get_skill_loader(skills_dir: str = "skills") -> SkillLoader:
    """获取全局 SkillLoader 单例"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader(skills_dir)
    return _skill_loader


def reset_skill_loader() -> None:
    """重置全局 SkillLoader（用于测试或重新加载）"""
    global _skill_loader
    _skill_loader = None
