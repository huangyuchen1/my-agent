# myAgent - 多模型 AI Agent 对话助手

一个原生实现的智能对话代理系统，支持多模型切换、工具调用、团队协作等高级特性。项目采用主代理 + 子代理架构，实现了完整的 Agent 循环模式（LLM 调用 → 工具执行 → 结果处理），并提供命令行和 Web 两种交互界面。

## 核心特性

- **多模型动态切换** - 支持 Kimi、DeepSeek 等多种 LLM，可通过配置文件或命令实时切换
- **完整工具调用系统** - 20+ 内置工具：文件读写、Bash 命令、进程管理、任务调度等
- **多 Agent 团队协作** - 创建独立线程运行的队友 Agent，支持消息传递与任务协作
- **三层上下文压缩** - 智能压缩对话历史，支持超长对话场景
- **会话持久化** - 保存/加载历史会话，支持搜索与管理
- **实时 Web UI** - WebSocket 流式输出，可视化展示 Agent 运行状态

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | Python 3.x + OpenAI SDK（原生实现） |
| LLM 集成 | OpenAI 兼容接口（Kimi/Moonshot、DeepSeek 等） |
| Web 服务 | FastAPI + Uvicorn + WebSocket |
| 异步处理 | aiohttp + threading 多线程并发 |
| 数据存储 | JSON 文件持久化 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

在 `config/config.json` 中配置模型信息：

```json
{
  "current_model": "deepseekV4",
  "models": {
    "kimi": {
      "api_key": "your_api_key",
      "base_url": "https://api.moonshot.cn/v1",
      "model_id": "kimi-k2.5",
      "max_tokens": 32768,
      "system_prompt": "You are a coding agent"
    },
    "deepseekV4": {
      "api_key": "your_api_key",
      "base_url": "https://api.example.com/v1",
      "model_id": "deepseek-v4-flash",
      "max_tokens": 32768,
      "system_prompt": "你是一个代码助手"
    }
  }
}
```

## 使用方法

### 命令行模式

```bash
python -m src.core.agent
```

交互命令：
- 直接输入问题进行对话
- `exit` / `q` - 退出程序
- `models` - 查看可用模型列表
- `switch <模型名>` - 切换模型
- `team` - 查看团队成员状态

会话管理命令：
- `/新建会话` - 创建新的对话会话
- `/会话列表` - 列出所有保存的会话
- `/加载会话 <id>` - 加载指定会话
- `/删除会话 <id>` - 删除指定会话
- `/搜索会话 <关键词>` - 搜索历史会话

### Web 模式

```bash
python -m src.web.server
```

浏览器将自动打开 `http://127.0.0.1:8000`，提供图形化交互界面。

## 架构设计

```
src/
├── core/               # 核心引擎
│   ├── agent.py        # Agent 主循环
│   ├── config.py       # 配置管理
│   ├── session_manager.py  # 会话持久化
│   └── skill_loader.py # 技能加载器
├── tools/              # 工具系统
│   ├── definitions.py  # 工具 Schema 定义
│   ├── dispatcher.py   # 工具调度器
│   ├── task_manager.py # 任务管理
│   └── worktree_manager.py # Git Worktree 管理
├── subagent/           # 子代理系统
│   ├── teammate_manager.py # 队友生命周期管理
│   ├── message_bus.py  # 消息总线
│   └── protocols.py    # 协作协议
├── context/            # 上下文管理
│   ├── compactor.py    # 三层压缩系统
│   └── transcript.py   # 对话记录存储
├── web/                # Web 前端
│   ├── server.py       # FastAPI 服务
│   └── event_bus.py    # 事件总线
└── ui/                 # 终端 UI
    └── spinner.py      # 状态动画
```

## 功能亮点

### 1. 原生 Agent Loop 实现

自主实现的 Agent 循环，深入理解工具调用原理：

```python
while True:
    response = LLM(messages, tools)
    if not response.tool_calls:
        return
    results = execute_tools(response.tool_calls)
    messages.append(tool_results)
```

### 2. 三层上下文压缩

- **Layer 1 (micro_compact)**：静默压缩旧 tool_result 为占位符
- **Layer 2 (auto_compact)**：Token 超阈值自动摘要，保存完整记录
- **Layer 3 (manual_compact)**：用户主动触发的上下文压缩

### 3. 多 Agent 团队协作

```python
# 创建队友
team_spawn(name="coder", role="代码专家")

# 发送任务
team_send(to="coder", content="实现用户认证模块")

# 查看团队状态
team_list()
```

### 4. 后台任务执行

```python
# 启动后台任务
background_run(command="npm run build", timeout=300)

# 完成后自动注入结果到对话
```

## 扩展开发

### 添加自定义工具

在 `src/tools/definitions.py` 中定义工具 Schema：

```python
{
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "参数描述"}
            },
            "required": ["param1"]
        }
    }
}
```

在 `src/tools/dispatcher.py` 中注册处理函数：

```python
def _handle_my_tool(self, arguments: Dict[str, Any]) -> str:
    # 实现工具逻辑
    return json.dumps({"result": "success"})
```

### 添加自定义 Skill

在 `skills/` 目录下创建技能包，包含 `SKILL.md` 和参考文档，系统会自动加载。

## 获取 API 密钥

- **Kimi/Moonshot**: [Moonshot AI 开放平台](https://platform.moonshot.cn/)
- **DeepSeek**: [DeepSeek 开放平台](https://platform.deepseek.com/)

## License

MIT
