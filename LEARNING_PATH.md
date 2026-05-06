# OpenHarness 学习路线

> 从入门到精通的完整学习路径，涵盖理论理解、代码阅读、实践项目和进阶主题。

---

## 📚 学习路径概览

```
阶段 0: 准备阶段（1-2 天）
    ↓
阶段 1: 快速上手（2-3 天）
    ↓
阶段 2: 核心架构理解（5-7 天）
    ↓
阶段 3: 关键模块深入（7-10 天）
    ↓
阶段 4: 高级主题（7-10 天）
    ↓
阶段 5: 贡献与精通（持续）
```

---

## 🎯 阶段 0: 准备阶段（1-2 天）

### 学习目标

- 了解 AI Agent 和 Agent Harness 的基本概念
- 搭建开发环境
- 熟悉项目文档结构

### 必备知识

1. **Python 基础**
   - Python 3.10+ 特性（类型注解、dataclass、async/await）
   - Pydantic v2 数据验证
   - asyncio 异步编程

2. **前端基础**（可选，如需深入 UI）
   - React 基础
   - TypeScript 基础

3. **LLM 基础**
   - 了解 LLM API 调用方式
   - 了解 Tool Use / Function Calling 概念

### 环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness

# 2. 安装依赖
uv sync --extra dev

# 3. 安装前端依赖（可选）
cd frontend/terminal
npm ci
cd ../..

# 4. 验证安装
uv run pytest -q  # 运行测试
uv run oh --help   # 查看 CLI 帮助
```

### 阅读材料

- [README.md](README.md) - 项目介绍和快速开始
- [ARCHITECTURE.md](ARCHITECTURE.md) - 完整架构文档
- [CONTRIBUTING.md](CONTRIBUTING.md) - 贡献指南

### 练习

1. 使用 `oh setup` 配置 Anthropic API
2. 运行第一个交互式会话：`oh`
3. 尝试无头模式：`oh -p "Explain this codebase" --output-format json`

---

## 🚀 阶段 1: 快速上手（2-3 天）

### 学习目标

- 理解 Agent Loop 核心概念
- 掌握基本使用方式
- 理解工具系统和技能系统

### 核心概念理解

#### 1. Agent Loop 核心流程

**阅读文件**:
- [src/openharness/engine/query_engine.py](src/openharness/engine/query_engine.py)
- [src/openharness/engine/query.py](src/openharness/engine/query.py)

**关键代码**（query.py 中的核心循环）:

```python
while True:
    # 1. 调用 LLM API
    response = await api.stream(messages, tools)

    # 2. 检查是否结束
    if response.stop_reason != "tool_use":
        break

    # 3. 执行工具调用
    for tool_call in response.tool_uses:
        # PreToolUse 钩子
        await hooks.execute(HookEvent.PRE_TOOL_USE, payload)

        # 权限检查
        if not permissions.check(tool_call):
            result = await ask_user_permission()
        else:
            # 执行工具
            result = await tool_registry.execute(tool_call)

        # PostToolUse 钩子
        await hooks.execute(HookEvent.POST_TOOL_USE, payload)

        # 收集结果
        messages.append(tool_result)
```

**理解要点**:
- 查询 → 流式响应 → 工具调用 → 循环
- 权限检查和钩子系统的介入时机
- 消息历史的累积和压缩

#### 2. 工具系统

**阅读文件**:
- [src/openharness/tools/base.py](src/openharness/tools/base.py) - 工具基类
- [src/openharness/tools/bash_tool.py](src/openharness/tools/bash_tool.py) - Shell 工具示例
- [src/openharness/tools/file_read_tool.py](src/openharness/tools/file_read_tool.py) - 文件读取示例

**关键概念**:

```python
class BaseTool(ABC):
    name: str                          # 工具名称
    description: str                    # 工具描述
    input_model: type[BaseModel]        # Pydantic 输入模型

    async def execute(self, arguments, context) -> ToolResult:
        """执行工具逻辑"""

    def is_read_only(self, arguments) -> bool:
        """判断是否为只读操作"""

    def to_api_schema(self) -> dict:
        """生成 JSON Schema 供 LLM 理解"""
```

**理解要点**:
- 工具使用 Pydantic 模型定义输入
- 每个 工具都有 `is_read_only()` 方法用于权限判断
- 工具注册表 `ToolRegistry` 管理所有工具

#### 3. 技能系统

**阅读文件**:
- [src/openharness/skills/registry.py](src/openharness/skills/registry.py)
- [src/openharness/skills/loader.py](src/openharness/skills/loader.py)
- [src/openharness/skills/bundled/commit.md](src/openharness/skills/bundled/commit.md)

**技能文件格式**:

```markdown
---
name: commit
description: Create clean git commits
---

# Git Commit Skill

## When to use
Use when the user asks to commit changes.

## Workflow
1. Run git status and git diff
2. Analyze changes
3. Draft commit message
4. Stage and commit
```

**理解要点**:
- 技能是 Markdown 文件，按需加载
- 技能注入到系统提示词中
- 兼容 anthropics/skills 格式

### 实践项目

#### 项目 1.1: 创建自定义工具

**目标**: 创建一个简单的 `HelloTool`，返回问候语

**步骤**:

```python
# 在 src/openharness/tools/hello_tool.py 创建文件

from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

class HelloInput(BaseModel):
    name: str = Field(description="Name to greet")

class HelloTool(BaseTool[HelloInput]):
    name = "hello"
    description = "Say hello to someone"
    input_model = HelloInput

    async def execute(
        self,
        arguments: HelloInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        return ToolResult(output=f"Hello, {arguments.name}!")

    def is_read_only(self, arguments: HelloInput) -> bool:
        return True  # 只读操作
```

**注册工具**（在 `src/openharness/tools/__init__.py`）:

```python
from openharness.tools.hello_tool import HelloTool

def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    registry = ToolRegistry()
    # ... 其他工具
    registry.register(HelloTool())
    return registry
```

**测试**:

```bash
# 运行交互式会话
uv run oh

# 在会话中输入
"Use the hello tool to greet Alice"
```

#### 项目 1.2: 创建自定义技能

**目标**: 创建一个代码审查技能

**步骤**:

```markdown
<!-- 在 ~/.openharness/skills/code-review.md 创建文件 -->

---
name: code-review
description: Systematic code review workflow
---

# Code Review Skill

## When to use
Use when the user asks to review code or pull requests.

## Workflow
1. **Understand context**: Read CLAUDE.md and related files
2. **Check logic**: Look for bugs, edge cases, error handling
3. **Check security**: Look for OWASP top 10 vulnerabilities
4. **Check style**: Code clarity, naming, documentation
5. **Suggest improvements**: Concrete, actionable suggestions

## Checklist
- [ ] Logic correctness
- [ ] Error handling
- [ ] Security issues
- [ ] Performance concerns
- [ ] Code style and clarity
- [ ] Documentation
```

**测试**:

```bash
uv run oh

# 在会话中输入
"Review the code in src/openharness/tools/base.py"
```

### 验收标准

- [ ] 能解释 Agent Loop 的核心流程
- [ ] 能创建并注册自定义工具
- [ ] 能创建自定义技能文件
- [ ] 理解工具和技能的区别

---

## 🧠 阶段 2: 核心架构理解（5-7 天）

### 学习目标

- 深入理解消息流和事件系统
- 掌握权限系统设计
- 理解钩子机制和生命周期
- 了解配置系统和路径管理

### 核心模块学习

#### 模块 2.1: API 客户端层

**阅读文件**:
- [src/openharness/api/client.py](src/openharness/api/client.py) - Anthropic 客户端
- [src/openharness/api/openai_client.py](src/openharness/api/openai_client.py) - OpenAI 兼容客户端
- [src/openharness/api/provider.py](src/openharness/api/provider.py) - 提供商检测

**关键接口**:

```python
class SupportsStreamingMessages(Protocol):
    """所有 API 客户端必须实现的协议"""

    async def stream_messages(
        self,
        messages: list[ConversationMessage],
        tools: list[dict],
        **kwargs
    ) -> AsyncGenerator[StreamResponse, None]:
        """流式调用 LLM API"""
```

**理解要点**:
- Protocol 定义统一接口
- 不同提供商的实现细节
- 重试机制和错误处理
- Token 计数和成本追踪

**练习**: 阅读 `tests/test_api/` 下的测试文件，理解不同客户端的测试方式

#### 模块 2.2: 权限系统

**阅读文件**:
- [src/openharness/permissions/checker.py](src/openharness/permissions/checker.py)
- [src/openharness/permissions/modes.py](src/openharness/permissions/modes.py)

**权限检查流程**:

```
1. 敏感路径检查（始终生效）
   ↓
2. 显式拒绝工具列表
   ↓
3. 显式允许工具列表
   ↓
4. 路径规则匹配
   ↓
5. 命令拒绝模式匹配
   ↓
6. 根据 PermissionMode 决定
   - default: 询问用户
   - plan: 拒绝变更操作
   - full_auto: 允许所有操作
```

**敏感路径保护**（硬编码）:

```python
SENSITIVE_PATH_PATTERNS = (
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.gnupg/*",
    "*/.openharness/credentials.json",
    "*/.env",
)
```

**理解要点**:
- 多层防御机制
- 敏感路径的硬编码保护
- 权限模式的切换场景

**练习**:

```python
# 在 settings.json 中配置权限
{
  "permission": {
    "mode": "default",
    "path_rules": [
      {"pattern": "/etc/*", "allow": false}
    ],
    "denied_commands": ["rm -rf"]
  }
}
```

#### 模块 2.3: 钩子系统

**阅读文件**:
- [src/openharness/hooks/events.py](src/openharness/hooks/events.py) - 事件枚举
- [src/openharness/hooks/executor.py](src/openharness/hooks/executor.py) - 执行器
- [src/openharness/hooks/schemas.py](src/openharness/hooks/schemas.py) - 钩子定义

**支持的事件**:

```python
class HookEvent(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_TOOL_USE = "pre_tool_use"      # 工具执行前
    POST_TOOL_USE = "post_tool_use"    # 工具执行后
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    NOTIFICATION = "notification"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
```

**钩子类型**:
- `CommandHookDefinition` - 执行 Shell 命令
- `PromptHookDefinition` - LLM 验证
- `HttpHookDefinition` - HTTP POST
- `AgentHookDefinition` - 深度验证

**练习**: 创建一个钩子，在文件写入前进行备份

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "cp ${file_path} ${file_path}.backup",
        "match": {"tool_name": "FileWriteTool"}
      }
    ]
  }
}
```

#### 模块 2.4: 配置系统

**阅读文件**:
- [src/openharness/config/settings.py](src/openharness/config/settings.py)
- [src/openharness/config/paths.py](src/openharness/config/paths.py)

**配置优先级**:

```
1. CLI 参数（最高）
   ↓
2. 环境变量（ANTHROPIC_API_KEY 等）
   ↓
3. 配置文件（~/.openharness/settings.json）
   ↓
4. 默认值（最低）
```

**关键路径**:

```python
def get_config_dir() -> Path:      # ~/.openharness/
def get_data_dir() -> Path:        # ~/.openharness/data/
def get_sessions_dir() -> Path:     # ~/.openharness/data/sessions/
def get_skills_dir() -> Path:      # ~/.openharness/skills/
def get_plugins_dir() -> Path:     # ~/.openharness/plugins/
```

**理解要点**:
- 多层配置合并策略
- 配置迁移和兼容性
- 路径解析和创建逻辑

### 实践项目

#### 项目 2.1: 实现权限日志记录器

**目标**: 创建钩子，记录所有被拒绝的工具调用

**步骤**:

```python
# 在 settings.json 中添加
{
  "hooks": {
    "post_tool_use": [
      {
        "type": "command",
        "command": "echo '[DENIED] ${tool_name}: ${reason}' >> ~/.openharness/denied.log",
        "match": {"result": "denied"}
      }
    ]
  }
}
```

**扩展**: 使用 `HttpHookDefinition` 将日志发送到远程服务器

#### 项目 2.2: 多提供商切换脚本

**目标**: 编写脚本，在 Anthropic 和 OpenAI 之间切换

```python
# scripts/switch_provider.py
import json
from pathlib import Path

def switch_provider(profile_name: str):
    settings_path = Path.home() / ".openharness" / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)

    # 激活提供商
    # ... 实现逻辑

    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

if __name__ == "__main__":
    import sys
    switch_provider(sys.argv[1])
```

### 验收标准

- [ ] 能解释不同提供商的 API 抽象方式
- [ ] 能配置和测试权限系统
- [ ] 能创建和调试钩子
- [ ] 理解配置优先级和路径管理

---

## 🔧 阶段 3: 关键模块深入（7-10 天）

### 学习目标

- 掌握提示词组装机制
- 理解记忆系统和上下文压缩
- 深入 MCP 协议客户端
- 了解多 Agent 协调机制

### 深入模块

#### 模块 3.1: 提示词系统

**阅读文件**:
- [src/openharness/prompts/system_prompt.py](src/openharness/prompts/system_prompt.py)
- [src/openharness/prompts/context.py](src/openharness/prompts/context.py)
- [src/openharness/prompts/claudemd.py](src/openharness/prompts/claudemd.py)
- [src/openharness/prompts/environment.py](src/openharness/prompts/environment.py)

**系统提示词结构**:

```
1. 基础系统提示词（身份、行为规范）
   [system_prompt.py]

2. 环境信息（OS、Shell、Git、Python）
   [environment.py]

3. 推理设置（effort、passes）

4. 可用技能列表
   [context.py]

5. 委托和子代理说明

6. CLAUDE.md 项目指令
   [claudemd.py]

7. 本地环境规则

8. Issue/PR 上下文

9. 项目记忆
```

**CLAUDE.md 发现逻辑**:

```python
def discover_claude_md_files(cwd: str | Path) -> list[Path]:
    """从当前目录向上搜索"""
    results = []
    path = Path(cwd).resolve()

    while path != path.parent:
        # CLAUDE.md
        if (path / "CLAUDE.md").exists():
            results.append(path / "CLAUDE.md")

        # .claude/CLAUDE.md
        if (path / ".claude" / "CLAUDE.md").exists():
            results.append(path / ".claude" / "CLAUDE.md")

        # .claude/rules/*.md
        rules_dir = path / ".claude" / "rules"
        if rules_dir.exists():
            results.extend(rules_dir.glob("*.md"))

        path = path.parent

    return results
```

**理解要点**:
- 提示词的层次化组装
- CLAUDE.md 的发现和注入
- 环境信息的收集方式

**练习**: 为你的项目创建 CLAUDE.md

```markdown
<!-- 在项目根目录创建 CLAUDE.md -->
# 项目说明

## 架构
这是一个 Flask Web 应用，使用 SQLAlchemy ORM。

## 代码风格
- 使用 Black 格式化
- 遵循 PEP 8
- 函数最大长度 50 行

## 测试
- 使用 pytest
- 测试覆盖率要求 > 80%
```

#### 模块 3.2: 记忆系统

**阅读文件**:
- [src/openharness/memory/manager.py](src/openharness/memory/manager.py)
- [src/openharness/memory/memdir.py](src/openharness/memory/memdir.py)
- [src/openharness/memory/paths.py](src/openharness/memory/paths.py)
- [src/openharness/services/compact/](src/openharness/services/compact/) - 压缩服务

**记忆存储结构**:

```
~/.openharness/memory/<project-name>-<hash>/
├── MEMORY.md          # 索引入口
├── preferences.md     # 用户偏好
├── architecture.md    # 架构决策
├── bugs.md           # 已知问题
└── todos.md          # 待办事项
```

**路径生成**:

```python
def get_project_memory_dir(cwd: str | Path) -> Path:
    """为每个项目生成唯一记忆目录"""
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return get_data_dir() / "memory" / f"{path.name}-{digest}"
```

**自动压缩**:

```python
async def compact_if_needed(messages, threshold=80000):
    if estimate_tokens(messages) < threshold:
        return messages

    # 微压缩：清除旧工具结果
    messages = micro_compact(messages)

    # 宏压缩：LLM 总结
    if estimate_tokens(messages) > threshold:
        summary = await summarize_with_llm(messages)
        messages = [SystemMessage(summary)] + messages[-10:]

    return messages
```

**理解要点**:
- 项目级记忆隔离
- 记忆的加载和相关性排序
- 微压缩 vs 宏压缩

**练习**:

```bash
# 创建记忆文件
mkdir -p ~/.openharness/memory/myproject-$(echo $PWD | sha1sum | cut -c1-12)

# 编辑记忆
cat > ~/.openharness/memory/myproject-abc123/preferences.md <<EOF
---
title: User Preferences
created: 2026-05-06
---

# Preferences

- 使用中文回复
- 优先使用异步代码
- 代码风格偏向函数式
EOF
```

#### 模块 3.3: MCP 协议

**阅读文件**:
- [src/openharness/mcp/client.py](src/openharness/mcp/client.py)
- [src/openharness/mcp/types.py](src/openharness/mcp/types.py)
- [src/openharness/tools/mcp_tool.py](src/openharness/tools/mcp_tool.py) - 工具适配

**MCP 服务器配置**:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["--root", "/home/user"],
      "transport": "stdio"
    },
    "http-server": {
      "url": "http://localhost:8080/mcp",
      "transport": "http"
    }
  }
}
```

**工具适配**:

```python
class MCPTool(BaseTool):
    """将 MCP 工具适配为 OpenHarness 工具"""

    def __init__(self, server_name: str, tool_info: McpToolInfo):
        self.server_name = server_name
        self.name = f"mcp_{server_name}_{tool_info.name}"
        self.description = tool_info.description
        self.input_model = self._build_input_model(tool_info)

    async def execute(self, arguments, context):
        result = await context.mcp_manager.call_tool(
            self.server_name,
            self.mcp_tool_info.name,
            arguments.model_dump()
        )
        return ToolResult(output=result.content)
```

**理解要点**:
- MCP 协议的基本概念
- stdio vs http 传输
- MCP 工具的自动适配

**练习**: 配置一个 MCP 文件系统服务器

```bash
# 安装 MCP 文件系统服务器
npm install -g @modelcontextprotocol/server-filesystem

# 在 settings.json 中配置
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-server-filesystem",
      "args": ["--root", "/home/user/projects"],
      "transport": "stdio"
    }
  }
}

# 测试
uv run oh -p "Use MCP filesystem to read README.md"
```

#### 模块 3.4: 多 Agent 协调

**阅读文件**:
- [src/openharness/coordinator/](src/openharness/coordinator/)
- [src/openharness/swarm/](src/openharness/swarm/)
- [src/openharness/tools/agent_tool.py](src/openharness/tools/agent_tool.py)

**架构**:

```
Coordinator (协调器)
    ├── TeamRegistry (团队注册表)
    ├── AgentDefinition (Agent 定义)
    └── TaskNotification (任务通知)

Swarm (多 Agent 架构)
    ├── BackendType (subprocess/in_process/tmux/iterm2)
    ├── Mailbox (文件消息队列)
    ├── SubprocessBackend (子进程后端)
    └── Worktree (Git Worktree 管理)
```

**消息队列设计**:

```
~/.openharness/teams/<team>/agents/<agent_id>/
├── inbox/
│   ├── <timestamp>_<message_id>.json
│   └── ...
├── outbox/
│   └── ...
└── state.json
```

**理解要点**:
- 协调器 vs Swarm 的职责划分
- 子进程后端的实现
- 消息队列的文件存储方式

**练习**: 派生一个子 Agent

```bash
uv run oh

# 在会话中输入
"Spawn a worker to analyze the test coverage while you review the code structure"
```

### 实践项目

#### 项目 3.1: 智能记忆管理器

**目标**: 实现自动记忆提取和总结

```python
# scripts/auto_memory.py
import json
from pathlib import Path
from openharness.memory import MemoryManager

async def extract_important_info(conversation_history):
    """从对话中提取重要信息"""
    # 使用 LLM 提取关键决策、学习到的偏好等
    summary = await summarize_conversation(conversation_history)

    # 创建记忆文件
    memory_manager = MemoryManager.get_instance()
    memory_manager.create_memory(
        title="Session Summary",
        content=summary,
        tags=["auto-generated", "session"]
    )
```

#### 项目 3.2: MCP 服务器集成

**目标**: 为 OpenHarness 添加 GitHub MCP 服务器

```json
{
  "mcpServers": {
    "github": {
      "command": "mcp-server-github",
      "args": ["--token", "${GITHUB_TOKEN}"],
      "transport": "stdio"
    }
  }
}
```

### 验收标准

- [ ] 能解释系统提示词的组装流程
- [ ] 能创建和管理项目记忆
- [ ] 能配置和调试 MCP 服务器
- [ ] 理解多 Agent 协调机制

---

## 🎨 阶段 4: 高级主题（7-10 天）

### 学习目标

- 掌握 React TUI 前后端通信
- 理解插件系统架构
- 深入消息通道和 Gateway
- 了解沙箱安全机制

### 高级模块

#### 模块 4.1: React TUI 前后端

**阅读文件**:
- [src/openharness/ui/](src/openharness/ui/) - 后端
- [frontend/terminal/src/](frontend/terminal/src/) - 前端

**前后端协议**:

```python
class FrontendRequest(BaseModel):
    type: Literal["submit_line", "permission_response", "interrupt", ...]
    line: str | None = None

class BackendEvent(BaseModel):
    type: Literal["ready", "transcript_item", "tool_started", ...]
    item: TranscriptItem | None = None
```

**通信方式**:

```
Frontend (React/Ink)
    ↓ JSON-lines (stdin/stdout)
BackendHost
    ↓ Function calls
QueryEngine
    ↓ AsyncGenerator
StreamEvent
```

**关键组件**:

| 组件 | 职责 |
|------|------|
| `App.tsx` | 主应用，管理全局状态 |
| `ConversationView` | 对话历史展示 |
| `PromptInput` | 输入框 + 命令选择器 |
| `ToolCallDisplay` | 工具调用可视化 |
| `PermissionModal` | 权限对话框 |

**理解要点**:
- JSON-lines 协议
- 事件驱动的 UI 更新
- Token 级流式渲染（30fps 缓冲）

**练习**: 添加自定义 UI 组件

```tsx
// frontend/terminal/src/components/CustomPanel.tsx
import React from 'react';
import { Box, Text } from 'ink';

export const CustomPanel: React.FC<{ data: string }> = ({ data }) => (
  <Box borderStyle="round" borderColor="cyan">
    <Text>{data}</Text>
  </Box>
);
```

#### 模块 4.2: 插件系统

**阅读文件**:
- [src/openharness/plugins/loader.py](src/openharness/plugins/loader.py)
- [src/openharness/plugins/types.py](src/openharness/plugins/types.py)
- [src/openharness/plugins/bundled/](src/openharness/plugins/bundled/) - 内置插件

**插件结构**:

```
<plugin-dir>/
├── plugin.json        # 清单
├── skills/             # 技能
│   └── skill1.md
├── agents/             # Agent 定义
│   └── agent1.md
├── hooks.json          # 钩子
├── mcp.json            # MCP 服务器
└── tools/              # Python 工具
    └── custom_tool.py
```

**插件清单**:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin",
  "skills": ["skills/*.md"],
  "agents": ["agents/*.md"],
  "hooks": "hooks.json",
  "mcp": "mcp.json"
}
```

**加载顺序**:
1. 用户插件目录（`~/.openharness/plugins/`）
2. 项目插件目录（需要 `allow_project_plugins=true`）
3. 额外根目录

**理解要点**:
- 插件 vs 技能的区别
- 插件的生命周期管理
- 安全性和隔离性

**练习**: 创建完整插件

```bash
# 创建插件目录
mkdir -p ~/.openharness/plugins/my-plugin/{skills,agents}

# 创建清单
cat > ~/.openharness/plugins/my-plugin/plugin.json <<EOF
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin"
}
EOF

# 创建技能
cat > ~/.openharness/plugins/my-plugin/skills/review.md <<EOF
---
name: review
description: Code review workflow
---

# Code Review

## When to use
Use when reviewing code changes.
EOF
```

#### 模块 4.3: 消息通道和 Gateway

**阅读文件**:
- [src/openharness/channels/](src/openharness/channels/)
- [ohmo/gateway/](ohmo/gateway/)

**支持的平台**:

| 平台 | 实现文件 |
|------|----------|
| Telegram | `impl/telegram.py` |
| Slack | `impl/slack.py` |
| Discord | `impl/discord.py` |
| Feishu | `impl/feishu.py` |

**消息流**:

```
Channel (Telegram/Slack/...)
    ↓ InboundMessage
MessageBus
    ↓ consume_inbound()
OhmoGatewayBridge
    ↓ route()
OhmoSessionRuntimePool
    ↓ get_or_create()
QueryEngine
    ↓ StreamEvent
OhmoGatewayBridge
    ↓ OutboundMessage
MessageBus
    ↓ publish_outbound()
Channel
```

**理解要点**:
- 消息总线的队列设计
- 会话路由策略
- 流式回复的收集和发送

**练习**: 配置 Telegram 通道

```bash
# 初始化 ohmo
ohmo init

# 配置 Telegram 通道
ohmo config

# 启动 Gateway
ohmo gateway start

# 查看状态
ohmo gateway status
```

#### 模块 4.4: 沙箱系统

**阅读文件**:
- [src/openharness/sandbox/](src/openharness/sandbox/)

**沙箱类型**:
- `srt` - sandbox-runtime (bwrap/sandbox-exec)
- `docker` - Docker 容器

**配置**:

```json
{
  "sandbox": {
    "enabled": true,
    "backend": "docker",
    "network": {
      "allowed_hosts": ["api.anthropic.com"]
    },
    "filesystem": {
      "read": {"allowOnly": ["/home/user/projects"]},
      "write": {"allowOnly": ["/tmp"]}
    }
  }
}
```

**路径验证**:

```python
class PathValidator:
    def validate_path(self, path: str | Path) -> Path:
        resolved = (self.sandbox_root / path).resolve()

        # 检查是否逃逸沙箱
        if not str(resolved).startswith(str(self.sandbox_root)):
            raise SandboxEscapeError(f"Path escapes sandbox: {path}")

        return resolved
```

**理解要点**:
- 两种沙箱的适用场景
- 路径验证和逃逸检测
- 网络和文件系统隔离

### 实践项目

#### 项目 4.1: 自定义消息通道

**目标**: 实现一个简单的 Email 通道

```python
# src/openharness/channels/impl/email.py
from openharness.channels.impl.base import BaseChannel

class EmailChannel(BaseChannel):
    async def start(self) -> None:
        # 连接 IMAP/SMTP
        pass

    async def send(self, msg: OutboundMessage) -> None:
        # 发送邮件
        pass

    async def _poll_messages(self) -> None:
        # 轮询新邮件
        pass
```

#### 项目 4.2: Docker 沙箱测试

**目标**: 编写 Docker 沙箱的集成测试

```bash
# 运行现有测试
python scripts/test_docker_sandbox_e2e.py

# 创建自定义测试场景
# ...
```

### 验收标准

- [ ] 能解释前后端通信协议
- [ ] 能创建和安装插件
- [ ] 理解消息通道架构
- [ ] 能配置和测试沙箱

---

## 🚢 阶段 5: 贡献与精通（持续）

### 学习目标

- 掌握测试驱动开发
- 理解 CI/CD 流程
- 参与 GitHub 协作
- 持续学习和改进

### 贡献流程

#### 1. 测试驱动开发

**测试结构**:

```
tests/
├── test_api/           # API 客户端测试
├── test_engine/        # 引擎测试
├── test_tools/         # 工具测试
├── test_permissions/   # 权限测试
├── test_hooks/         # 钩子测试
├── test_mcp/           # MCP 测试
├── test_swarm/         # 多 Agent 测试
└── test_ui/            # UI 测试
```

**编写测试**:

```python
# tests/test_tools/test_hello_tool.py
import pytest
from openharness.tools.hello_tool import HelloTool, HelloInput
from openharness.tools.base import ToolExecutionContext

@pytest.mark.asyncio
async def test_hello_tool():
    tool = HelloTool()
    args = HelloInput(name="World")
    context = ToolExecutionContext(cwd="/tmp")

    result = await tool.execute(args, context)

    assert result.output == "Hello, World!"
    assert not result.is_error

def test_hello_tool_schema():
    tool = HelloTool()
    schema = tool.to_api_schema()

    assert schema["name"] == "hello"
    assert "name" in schema["input_schema"]["properties"]
```

**运行测试**:

```bash
# 单元测试
uv run pytest -q

# E2E 测试
python scripts/test_harness_features.py
python scripts/test_real_skills_plugins.py

# 覆盖率
uv run pytest --cov=src/openharness
```

#### 2. CI/CD 流程

**本地检查**:

```bash
# 代码风格
uv run ruff check src tests scripts

# 类型检查
uv run mypy src

# 测试
uv run pytest -q
```

**GitHub Actions**:
- `.github/workflows/ci.yml` - 持续集成
- 自动运行 lint、test、coverage

#### 3. PR 贡献

**流程**:

```bash
# 1. Fork 仓库
# 2. 创建分支
git checkout -b feature/my-feature

# 3. 开发和测试
# ... 编写代码
uv run pytest -q

# 4. 提交
git commit -m "feat: add my feature"

# 5. 推送
git push origin feature/my-feature

# 6. 创建 PR
# 在 GitHub 上操作
```

**PR 要求**:
- 保持 PR 范围小而专注
- 包含问题描述、改动内容、验证方式
- 添加或更新测试
- 更新文档（如果需要）
- 在 `CHANGELOG.md` 添加条目

### 进阶学习

#### 主题 5.1: 性能优化

**关键点**:
- Token 计数优化
- 流式渲染性能
- 并行工具执行
- 上下文压缩策略

**阅读**:
- `src/openharness/services/token_estimation.py`
- `src/openharness/engine/query.py` - 并行工具执行

#### 主题 5.2: 安全加固

**关键点**:
- 敏感路径保护
- 权限检查强化
- 沙箱逃逸检测
- 输入验证

**阅读**:
- `src/openharness/permissions/checker.py`
- `src/openharness/sandbox/path_validator.py`

#### 主题 5.3: 扩展开发

**方向**:
- 新工具开发
- 新技能创建
- 新插件开发
- 新消息通道集成

### 持续学习资源

1. **官方文档**
   - [README.md](README.md)
   - [ARCHITECTURE.md](ARCHITECTURE.md)
   - [CONTRIBUTING.md](CONTRIBUTING.md)
   - [CHANGELOG.md](CHANGELOG.md)

2. **代码阅读**
   - 每天阅读一个模块的源码
   - 关注测试文件理解设计意图
   - 提交 Issue 和 PR 参与讨论

3. **社区参与**
   - GitHub Issues 和 Discussions
   - Feishu/WeChat 用户群
   - 贡献文档和示例

### 最终项目

#### 项目 5.1: 完整插件开发

**目标**: 开发一个代码质量检查插件

**功能**:
- 代码风格检查技能
- 安全漏洞扫描技能
- 复杂度分析技能
- 自动修复建议钩子

#### 项目 5.2: 企业级部署

**目标**: 在企业环境中部署 OpenHarness

**任务**:
- 配置 LDAP/SSO 认证
- 设置权限和审计
- 部署 Gateway 服务
- 监控和日志集成

---

## 📊 学习检查清单

### 阶段 0: 准备阶段
- [ ] 了解 AI Agent 基本概念
- [ ] 完成环境搭建
- [ ] 阅读 README.md 和 ARCHITECTURE.md
- [ ] 运行第一个会话

### 阶段 1: 快速上手
- [ ] 理解 Agent Loop 核心流程
- [ ] 创建自定义工具
- [ ] 创建自定义技能
- [ ] 理解工具和技能的区别

### 阶段 2: 核心架构理解
- [ ] 掌握 API 客户端抽象
- [ ] 配置和测试权限系统
- [ ] 创建和调试钩子
- [ ] 理解配置系统

### 阶段 3: 关键模块深入
- [ ] 理解提示词组装
- [ ] 创建和管理记忆
- [ ] 配置 MCP 服务器
- [ ] 理解多 Agent 协调

### 阶段 4: 高级主题
- [ ] 解释前后端通信
- [ ] 创建和安装插件
- [ ] 理解消息通道
- [ ] 配置沙箱

### 阶段 5: 贡献与精通
- [ ] 编写测试
- [ ] 通过 CI 检查
- [ ] 提交 PR
- [ ] 持续学习和贡献

---

## 🎓 学习建议

### 学习方法

1. **理论与实践结合**
   - 先读代码理解设计
   - 再动手实践验证理解
   - 最后总结归纳

2. **从整体到局部**
   - 先理解整体架构
   - 再深入具体模块
   - 最后理解细节实现

3. **主动调试**
   - 使用 `print()` 和日志
   - 单步调试理解流程
   - 编写测试验证假设

4. **社区参与**
   - 提问和讨论
   - 分享学习心得
   - 贡献文档和代码

### 常见问题

**Q: 工具和技能有什么区别？**

A: 工具是 Python 实现的功能模块，技能是 Markdown 格式的知识指导。工具提供"能力"，技能提供"知识"。

**Q: 如何调试 Agent Loop？**

A: 使用 `--debug` 标志启动，查看详细日志。在代码中添加断点，理解工具调用流程。

**Q: 如何选择沙箱类型？**

A: `srt` 适合本地开发，轻量快速；`docker` 适合生产环境，隔离性更好。

**Q: 如何贡献代码？**

A: 先在 Issues 中讨论想法，然后 Fork 仓库开发，确保测试通过后提交 PR。

---

## 📖 推荐阅读顺序

### 入门级（必读）
1. [README.md](README.md)
2. [ARCHITECTURE.md](ARCHITECTURE.md)
3. [src/openharness/cli.py](src/openharness/cli.py)
4. [src/openharness/engine/query.py](src/openharness/engine/query.py)

### 进阶级（推荐）
1. [src/openharness/tools/base.py](src/openharness/tools/base.py)
2. [src/openharness/permissions/checker.py](src/openharness/permissions/checker.py)
3. [src/openharness/hooks/executor.py](src/openharness/hooks/executor.py)
4. [src/openharness/prompts/context.py](src/openharness/prompts/context.py)

### 高级（可选）
1. [src/openharness/mcp/client.py](src/openharness/mcp/client.py)
2. [src/openharness/swarm/](src/openharness/swarm/)
3. [frontend/terminal/src/App.tsx](frontend/terminal/src/App.tsx)
4. [ohmo/gateway/](ohmo/gateway/)

---

## 🔗 有用的链接

- **项目仓库**: https://github.com/HKUDS/OpenHarness
- **Issues**: https://github.com/HKUDS/OpenHarness/issues
- **anthropics/skills**: https://github.com/anthropics/skills
- **claude-code/plugins**: https://github.com/anthropics/claude-code/tree/main/plugins
- **MCP Protocol**: https://modelcontextprotocol.io/

---

**文档版本**: 1.0
**更新日期**: 2026-05-06
**维护者**: OpenHarness Team

祝你学习愉快！如有问题，欢迎在 GitHub Issues 中提问。
