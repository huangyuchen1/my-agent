"""
SubAgent - 子代理框架
支持多类型子代理：探索(Explore)、执行(Execute)、研究(Research)等
每个子代理拥有独立的上下文、工具集和生命周期
"""
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type
from openai import OpenAI
import os


class SubagentType(Enum):
    """子代理类型枚举"""
    EXPLORE = "explore"      # 探索型：搜索代码、理解结构
    EXECUTE = "execute"      # 执行型：执行具体任务
    RESEARCH = "research"    # 研究型：深度分析、调研
    REVIEW = "review"        # 审查型：代码审查、审查建议
    GENERAL = "general"      # 通用型：灵活任务


@dataclass
class SubagentConfig:
    """子代理配置"""
    name: str
    subagent_type: SubagentType
    system_prompt: str
    tools: List[Dict] = field(default_factory=list)
    max_rounds: int = 10
    timeout_seconds: int = 300
    model: str = "kimi-k2.5"
    parent_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentResult:
    """子代理执行结果"""
    success: bool
    messages: List[Dict[str, Any]]
    summary: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    rounds: int = 0
    duration: float = 0.0


class BaseSubagent(ABC):
    """子代理抽象基类"""

    def __init__(self, config: SubagentConfig, client: OpenAI):
        self.config = config
        self.client = client
        self.session_id = str(uuid.uuid4())[:8]
        self.messages: List[Dict[str, Any]] = []

    @abstractmethod
    def build_system_prompt(self) -> str:
        """构建系统提示词"""
        pass

    def create_session(self) -> List[Dict[str, Any]]:
        """创建子代理会话"""
        base_system = self.build_system_prompt()
        if self.config.parent_context:
            context_info = f"\n\n[父上下文]\n{json.dumps(self.config.parent_context, ensure_ascii=False, indent=2)}"
            base_system += context_info

        self.messages = [{
            "role": "system",
            "content": base_system
        }]
        return self.messages

    def execute(self, initial_task: str) -> SubagentResult:
        """执行子代理任务"""
        start_time = time.time()
        rounds = 0

        try:
            self.create_session()
            self.messages.append({"role": "user", "content": initial_task})

            while rounds < self.config.max_rounds:
                rounds += 1

                response = self._call_model()
                if response is None:
                    return SubagentResult(
                        success=False,
                        messages=self.messages,
                        summary="API调用失败",
                        error="Failed to call model"
                    )

                choice = response.choices[0]
                assistant_msg = self._build_message(choice.message)
                self.messages.append(assistant_msg)

                if choice.finish_reason != "tool_calls":
                    summary = assistant_msg["content"] or "任务完成"
                    return SubagentResult(
                        success=True,
                        messages=self.messages,
                        summary=summary[:500],
                        rounds=rounds,
                        duration=time.time() - start_time
                    )

                # 执行工具调用
                results = self._execute_tools(choice.message.tool_calls)
                for tc, result in zip(choice.message.tool_calls, results):
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result
                    })

            return SubagentResult(
                success=True,
                messages=self.messages,
                summary="达到最大轮次限制",
                rounds=rounds,
                duration=time.time() - start_time
            )

        except Exception as e:
            return SubagentResult(
                success=False,
                messages=self.messages,
                summary="执行异常",
                error=str(e),
                rounds=rounds,
                duration=time.time() - start_time
            )

    def _call_model(self):
        """调用模型"""
        try:
            return self.client.chat.completions.create(
                model=self.config.model,
                messages=self.messages,
                tools=self.config.tools,
                max_tokens=32768,
                extra_body={"thinking": {"type": "disabled"}}
            )
        except Exception:
            return None

    def _build_message(self, message) -> Dict[str, Any]:
        """构建消息"""
        msg = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]
        return msg

    def _execute_tools(self, tool_calls) -> List[str]:
        """执行工具调用 - 子类可覆盖"""
        from tool_dispatcher import dispatcher
        results = []
        for tc in tool_calls:
            tool_name = tc.function.name
            args = json.loads(tc.function.arguments)
            result = dispatcher.run_tool(tool_name, args)
            results.append(result)
        return results


class ExploreSubagent(BaseSubagent):
    """探索型子代理 - 用于理解代码结构、搜索代码"""

    def build_system_prompt(self) -> str:
        return f"""你是一个代码探索助手(Session: {self.session_id})。
你的任务是探索和理解代码库结构。

工作原则:
1. 使用 list_dir 和 glob 探索目录结构
2. 使用 read_file 阅读关键文件
3. 使用 Grep 搜索特定代码模式
4. 使用 SemanticSearch 语义搜索
5. 保持简洁，聚焦于回答用户问题

输出格式:
- 先列出发现的关键信息
- 然后给出总结性回答
- 如需深入分析某个文件，明确说明"""


class ExecuteSubagent(BaseSubagent):
    """执行型子代理 - 用于执行具体开发任务"""

    def build_system_prompt(self) -> str:
        return f"""你是一个任务执行助手(Session: {self.session_id})。
你的任务是完成具体的编码任务。

工作原则:
1. 仔细理解任务要求
2. 先规划再执行
3. 使用 todo 工具管理任务进度
4. 完成后验证结果
5. 保持代码整洁

任务完成标准:
- 功能正确实现
- 无明显错误
- 符合项目规范"""


class ResearchSubagent(BaseSubagent):
    """研究型子代理 - 用于深度分析和调研"""

    def build_system_prompt(self) -> str:
        return f"""你是一个研究分析助手(Session: {self.session_id})。
你的任务是进行深度分析和调研。

工作原则:
1. 广泛收集相关信息
2. 使用 web_search 工具获取外部资料
3. 分析多个来源的信息
4. 提供结构化的分析报告
5. 标注信息来源

输出格式:
## 调研结论
[主要发现]

## 详细分析
[深入分析内容]

## 参考资料
[信息来源列表]"""


class ReviewSubagent(BaseSubagent):
    """审查型子代理 - 用于代码审查和审查"""

    def build_system_prompt(self) -> str:
        return f"""你是一个代码审查助手(Session: {self.session_id})。
你的任务是审查代码并提供改进建议。

审查维度:
1. 代码质量：可读性、可维护性
2. 潜在问题：bug、性能、安全
3. 最佳实践：是否符合项目规范
4. 测试覆盖：是否有必要的测试

输出格式:
## 总体评价
[代码的整体质量评价]

## 发现的问题
### 严重问题
[必须修复的问题]

### 建议改进
[可选的改进建议]

## 具体建议
[针对每个问题的具体修复建议]"""


# 子代理类型到类的映射
SUBAGENT_CLASSES: Dict[SubagentType, Type[BaseSubagent]] = {
    SubagentType.EXPLORE: ExploreSubagent,
    SubagentType.EXECUTE: ExecuteSubagent,
    SubagentType.RESEARCH: ResearchSubagent,
    SubagentType.REVIEW: ReviewSubagent,
    SubagentType.GENERAL: BaseSubagent,
}


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


# 工厂函数 - 快速创建子代理
def create_subagent(
    manager: SubagentManager,
    name: str,
    subagent_type: SubagentType,
    **kwargs
) -> str:
    """创建子代理的便捷函数"""
    return manager.create_subagent(name, subagent_type, **kwargs)


def run_parallel_tasks(
    manager: SubagentManager,
    tasks: List[tuple]
) -> Dict[str, SubagentResult]:
    """
    并行运行多个子代理任务

    Args:
        manager: 子代理管理器
        tasks: [(agent_id, task), ...] 任务列表

    Returns:
        {agent_id: result} 结果字典
    """
    results = {}
    for agent_id, task in tasks:
        results[agent_id] = manager.run_task(agent_id, task)
    return results
