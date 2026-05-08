"""SubagentManager - 子代理管理器"""
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from src.subagent.base import (
    BaseSubagent,
    SubagentConfig,
    SubagentResult,
    SubagentType,
    SUBAGENT_CLASSES,
)


class SubagentManager:
    """
    子代理管理器
    负责创建、调度和管理多个子代理实例
    """

    def __init__(self, client: OpenAI):
        self.client = client
        self.active_subagents: Dict[str, BaseSubagent] = {}
        self.results_cache: Dict[str, SubagentResult] = {}

    def create_subagent(
        self,
        name: str,
        subagent_type: SubagentType,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        max_rounds: int = 10,
        parent_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        创建子代理实例

        Args:
            name: 子代理名称
            subagent_type: 子代理类型
            system_prompt: 自定义系统提示词
            tools: 可用工具列表
            max_rounds: 最大执行轮次
            parent_context: 父代理上下文

        Returns:
            子代理 ID
        """
        agent_class = SUBAGENT_CLASSES.get(subagent_type, BaseSubagent)

        # 构建默认系统提示词
        if system_prompt is None:
            temp_agent = object.__new__(agent_class)
            temp_agent.session_id = "temp"
            temp_agent.config = SubagentConfig(
                name=name,
                subagent_type=subagent_type,
                system_prompt=""
            )
            system_prompt = temp_agent.build_system_prompt()

        config = SubagentConfig(
            name=name,
            subagent_type=subagent_type,
            system_prompt=system_prompt,
            tools=tools or [],
            max_rounds=max_rounds,
            parent_context=parent_context or {}
        )

        subagent = agent_class(config, self.client)
        agent_id = f"{name}_{subagent.session_id}"
        self.active_subagents[agent_id] = subagent

        return agent_id

    def run_task(
        self,
        agent_id: str,
        task: str,
        callback: Optional[Callable] = None
    ) -> SubagentResult:
        """
        运行子代理任务

        Args:
            agent_id: 子代理 ID
            task: 任务描述
            callback: 可选的进度回调函数

        Returns:
            执行结果
        """
        subagent = self.active_subagents.get(agent_id)
        if not subagent:
            return SubagentResult(
                success=False,
                messages=[],
                summary="",
                error=f"Subagent {agent_id} not found"
            )

        result = subagent.execute(task)
        self.results_cache[agent_id] = result

        if callback:
            callback(result)

        return result

    def get_result(self, agent_id: str) -> Optional[SubagentResult]:
        """获取子代理执行结果"""
        return self.results_cache.get(agent_id)

    def terminate(self, agent_id: str) -> bool:
        """终止子代理"""
        if agent_id in self.active_subagents:
            del self.active_subagents[agent_id]
            return True
        return False

    def list_active(self) -> List[Dict[str, str]]:
        """列出所有活跃的子代理"""
        return [
            {"id": agent_id, "name": agent.config.name}
            for agent_id, agent in self.active_subagents.items()
        ]
