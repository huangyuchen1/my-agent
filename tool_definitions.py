"""
ToolDefinitions - 工具 schema 定义模块
包含所有控制台工具的 JSON Schema 定义
"""

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "创建并运行子代理来执行专门任务。当任务需要独立的执行上下文、专门的工具集或并行处理时使用。适用于代码探索、深度研究、代码审查等场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "子代理的名称，用于标识和追踪"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["explore", "execute", "research", "review", "general"],
                        "description": "子代理类型: explore(代码探索), execute(任务执行), research(深度研究), review(代码审查), general(通用)"
                    },
                    "task": {
                        "type": "string",
                        "description": "子代理要执行的具体任务描述"
                    },
                    "max_rounds": {
                        "type": "integer",
                        "description": "子代理最大执行轮次，默认10"
                    },
                    "parent_context": {
                        "type": "object",
                        "description": "传递给子代理的父上下文信息，可选"
                    }
                },
                "required": ["name", "type", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "更新待办事项列表。用于管理多步骤任务的状态，包括 pending（待处理）、in_progress（进行中）、completed（已完成）。每次更新会渲染当前所有事项的状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "待办事项列表，每项包含 id（标识）、text（描述）、status（状态 pending/in_progress/completed）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "事项唯一标识"},
                                "text": {"type": "string", "description": "事项描述"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "事项状态"}
                            },
                            "required": ["text", "status"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 Shell/PowerShell 命令。用于运行系统命令、程序、脚本等。返回命令的 stdout、stderr 和退出码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令（PowerShell on Windows, Bash on Mac/Linux）"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容。用于查看文本文件、代码文件、配置文件等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径或相对路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入或创建文件。用于创建新文件或覆盖现有文件内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径或相对路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录内容。显示指定目录下的所有文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录的绝对路径或相对路径，默认为当前目录"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "搜索匹配的文件模式。支持通配符 *、** 等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "搜索模式，如 *.py、**/*.js、src/**/*.ts"
                    },
                    "base_dir": {
                        "type": "string",
                        "description": "搜索的基础目录，默认为工作区目录"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_processes",
            "description": "获取当前运行的进程列表。可选过滤条件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "可选的进程名过滤关键词"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "终止指定进程。使用前请确认进程 ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "要终止的进程 ID"
                    }
                },
                "required": ["pid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取系统信息，包括 CPU、内存、磁盘使用情况。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]
