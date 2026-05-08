"""
ToolDefinitions - 工具 schema 定义模块
包含所有控制台工具的 JSON Schema 定义
"""

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "team_spawn",
            "description": "在团队中创建一个新的持久化队友。队友会在独立线程中运行，拥有自己的 agent_loop 和收件箱，可以跨多轮对话保持记忆。与队友通信使用 team_send。适用于需要并行处理、相互协作的复杂任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "队友名称（唯一标识）"},
                    "role": {"type": "string", "description": "队友角色描述，如 coder、tester、researcher"},
                    "prompt": {"type": "string", "description": "可选的自定义系统提示词"},
                    "max_rounds": {"type": "integer", "description": "最大执行轮次，默认50"}
                },
                "required": ["name", "role"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "team_send",
            "description": "向指定队友发送消息。消息会追加到队友的收件箱，队友在下一轮 loop 开始时会读取并响应。支持发送给一个或多个队友（逗号分隔）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "接收消息的队友名称（多个用逗号分隔）"},
                    "content": {"type": "string", "description": "消息内容"},
                    "broadcast": {"type": "boolean", "description": "是否为广播消息（发给所有队友）"}
                },
                "required": ["to", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "team_inbox",
            "description": "读取并清空自己的收件箱，或者查询指定队友的收件箱状态。返回所有未读消息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "description": "可选，指定要查询的队友名称，不填则读取自己的收件箱"},
                    "count_only": {"type": "boolean", "description": "如果为 true，仅返回未读消息数量"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "team_list",
            "description": "列出团队中所有队友的状态（working / idle / shutdown）。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "team_shutdown",
            "description": "关闭指定队友，释放其资源。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "要关闭的队友名称"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_create",
            "description": "创建新任务。任务会持久化到磁盘（.tasks/ 目录），跨上下文压缩和重启存活。可选指定 blocked_by 依赖列表，表示此任务必须等待这些前置任务全部完成后才能开始。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "任务主题/标题，简洁描述任务内容"},
                    "description": {"type": "string", "description": "任务详细描述，说明具体要做什么（可选）"},
                    "blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "前置依赖任务 ID 列表。例如 [1, 2] 表示必须等任务 #1 和 #2 都完成后才能开始此任务"
                    }
                },
                "required": ["subject"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_update",
            "description": "更新任务状态或依赖关系。status 流转：pending -> in_progress -> completed。completed 会自动将该任务 ID 从所有下游任务的 blockedBy 中移除（解锁下游）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "要更新的任务 ID"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "任务新状态"},
                    "blocked_by": {"type": "array", "items": {"type": "integer"}, "description": "直接覆盖替换 blockedBy 列表"},
                    "add_blocked_by": {"type": "array", "items": {"type": "integer"}, "description": "向 blockedBy 中追加前置依赖任务 ID"},
                    "remove_blocked_by": {"type": "array", "items": {"type": "integer"}, "description": "从 blockedBy 中移除前置依赖任务 ID"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "列出所有任务，显示每个任务的状态、blockedBy 依赖关系、以及哪些任务是当前可执行的（pending 且无阻塞）。返回 JSON 数组。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_get",
            "description": "获取指定任务的完整详细信息。",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "要查询的任务 ID"}},
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 Shell/PowerShell 命令。用于运行系统命令、程序、脚本等。返回命令的 stdout、stderr 和退出码。对于耗时长且可并行的任务（如 npm install、pytest），可设置 background=true 将命令放入后台执行，Agent 可以继续其他工作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令（PowerShell on Windows, Bash on Mac/Linux）"},
                    "background": {"type": "boolean", "description": "是否在后台执行（不阻塞 Agent，可并行处理其他任务）。适用于耗时操作。默认 false。"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "background_run",
            "description": "在后台启动一个耗时的 shell 命令，立即返回 task_id。Agent 可以继续执行其他工作。当命令完成时，结果会自动注入下一轮 LLM 上下文。适用于 npm install、docker build、pytest 等耗时操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令（PowerShell on Windows, Bash on Mac/Linux）"},
                    "timeout": {"type": "integer", "description": "超时时间（秒），默认300秒，最大600秒"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "background_status",
            "description": "查询后台任务的状态。如果任务已完成，返回完整结果；如果仍在运行，返回当前状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID（background_run 返回的 task_id）"},
                    "list_all": {"type": "boolean", "description": "如果为 true，列出所有后台任务状态"}
                }
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
                "properties": {"path": {"type": "string", "description": "文件的绝对路径或相对路径"}},
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
                    "path": {"type": "string", "description": "文件的绝对路径或相对路径"},
                    "content": {"type": "string", "description": "文件内容"}
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
                "properties": {"path": {"type": "string", "description": "目录的绝对路径或相对路径，默认为当前目录"}}
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
                    "pattern": {"type": "string", "description": "搜索模式，如 *.py、**/*.js、src/**/*.ts"},
                    "base_dir": {"type": "string", "description": "搜索的基础目录，默认为工作区目录"}
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
                "properties": {"filter": {"type": "string", "description": "可选的进程名过滤关键词"}}
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
                "properties": {"pid": {"type": "integer", "description": "要终止的进程 ID"}},
                "required": ["pid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取系统信息，包括 CPU、内存、磁盘使用情况。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "按需加载指定 Skill 的完整内容。当需要特定领域的工作流、约定或最佳实践时使用。返回 <skill name=\"xxx\">...</skill> 格式的内容。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "要加载的 Skill 名称（如 git, code-review, test 等）"}},
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compact",
            "description": "手动压缩当前对话上下文。当上下文变长导致模型响应变慢或质量下降时使用。此工具会保存完整对话历史到磁盘，调用 LLM 生成摘要，然后将压缩后的摘要替换当前上下文。压缩后的完整记录保存在 storage/.context/transcripts/ 目录中。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {"type": "string", "description": "可选的压缩指导，说明本次对话的重点任务和方向，帮助 LLM 生成更有针对性的摘要。"}
                    }
                }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "context_stats",
            "description": "获取当前对话上下文的统计信息，包括估算 token 数量、消息数量、压缩状态、以及已保存的 transcript 文件列表。",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]
