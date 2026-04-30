# AI Agent - Kimi 对话助手

一个简单的 Python AI Agent 应用，对接 Moonshot AI 的 Kimi 大模型。

## 安装

```bash
pip install -r requirements.txt
```

## 配置

设置环境变量 `MOONSHOT_API_KEY`:

```bash
# Windows PowerShell
$env:MOONSHOT_API_KEY = "your_api_key_here"

# Linux/macOS
export MOONSHOT_API_KEY="your_api_key_here"
```

或在代码中直接传入 API 密钥:

```python
agent = AiAgent(api_key="your_api_key_here")
```

## 使用方法

### 命令行交互

```bash
python ai_agent.py
```

交互命令:
- 直接输入问题进行对话
- `quit` / `exit` - 退出程序
- `reset` / `重置` - 重置对话历史

### 作为模块使用

```python
from ai_agent import AiAgent

# 初始化
agent = AiAgent()

# 对话
response = agent.chat("你好，请介绍一下你自己")
print(response)

# 重置对话
agent.reset()
```

## API 参考

### AiAgent 类

#### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| api_key | str | 环境变量 MOONSHOT_API_KEY | Moonshot API密钥 |
| model | str | "kimi-k2.5" | 使用的模型名称 |

#### 方法

- `chat(query: str) -> str` - 发送对话请求
- `reset()` - 重置对话历史
- `print_history()` - 打印对话历史

## 获取 API 密钥

访问 [Moonshot AI 开放平台](https://platform.moonshot.cn/) 注册并获取 API 密钥。
