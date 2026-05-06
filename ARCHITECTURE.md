# OpenHarness 架构分析文档

> 本文档详细分析了 OpenHarness 项目的整体架构设计、核心模块实现以及技术栈。

---

## 目录

- [概述](#概述)
- [核心架构](#核心架构)
- [技术栈](#技术栈)
- [模块详解](#模块详解)
  - [1. Engine - Agent Loop 引擎](#1-engine---agent-loop-引擎)
  - [2. Tools - 43+ 工具系统](#2-tools---43-工具系统)
  - [3. API - 多提供商客户端层](#3-api---多提供商客户端层)
  - [4. Permissions - 权限系统](#4-permissions---权限系统)
  - [5. Hooks - 生命周期钩子](#5-hooks---生命周期钩子)
  - [6. MCP - Model Context Protocol](#6-mcp---model-context-protocol)
  - [7. Memory - 记忆系统](#7-memory---记忆系统)
  - [8. Coordinator & Swarm - 多 Agent 协调](#8-coordinator--swarm---多-agent-协调)
  - [9. Prompts - 上下文组装](#9-prompts---上下文组装)
  - [10. Config - 多层配置](#10-config---多层配置)
  - [11. UI - React TUI 前后端](#11-ui---react-tui-前后端)
  - [12. Skills - 技能系统](#12-skills---技能系统)
  - [13. Plugins - 插件系统](#13-plugins---插件系统)
  - [14. Tasks - 后台任务管理](#14-tasks---后台任务管理)
  - [15. Sandbox - 沙箱系统](#15-sandbox---沙箱系统)
  - [16. Channels - 消息通道](#16-channels---消息通道)
  - [17. Auth - 认证系统](#17-auth---认证系统)
  - [18. Services - 核心服务](#18-services---核心服务)
- [ohmo - 个人代理应用](#ohmo---个人代理应用)
- [前后端架构](#前后端架构)
- [测试体系](#测试体系)
- [依赖关系图](#依赖关系图)
- [扩展机制](#扩展机制)
- [部署架构](#部署架构)

---

## 概述

**OpenHarness** 是一个功能完备的开源 AI Agent CLI 框架，采用 Python 实现。它不是简单的聊天机器人，而是一个完整的 **Agent Harness（智能体框架）**，为 LLM 提供工具、记忆、安全边界和多 Agent 协调能力。

### 核心特性

- 🧠 **Agent Loop** - 完整的查询→流式→工具调用→循环机制
- 🔧 **43+ 工具** - 文件 I/O、Shell、搜索、网络、MCP 等
- 🔌 **插件生态** - Skills、Hooks、Agents、MCP Servers
- 🛡️ **权限系统** - 多级权限模式、路径规则、命令过滤
- 🤝 **多 Agent 协调** - 子 Agent 派生、团队注册、任务管理
- 📡 **多通道集成** - Telegram、Slack、Discord、Feishu 等 10+ 平台
- 🎨 **React TUI** - 基于 Ink 的终端用户界面

### 设计哲学

```
Agent = LLM + Harness
Harness = Tools + Knowledge + Memory + Permissions + Coordination
```

模型提供**智能**，框架提供**手脚、眼睛、记忆和安全边界**。

---

## 核心架构

### 系统分层

```
┌─────────────────────────────────────────────────────────┐
│                     用户界面层                           │
│          React TUI (Ink) / CLI / Gateway                │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                   会话管理层                             │
│     Session Storage / Backend Host / Runtime            │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                   Agent Loop 引擎                        │
│          QueryEngine / Stream Processing                │
└───┬──────────┬─────────┬──────────┬──────────┬─────────┘
    │          │         │          │          │
┌───▼──┐  ┌────▼───┐ ┌────▼───┐ ┌────▼────┐ ┌────▼────┐
│Tools │  │  API   │ │ Hooks  │ │Perms    │ │ Prompts │
└───┬──┘  └────┬───┘ └────┬───┘ └────┬────┘ └────┬────┘
    │          │         │          │           │
┌───▼──┐  ┌────▼───┐ ┌────▼───┐ ┌────▼────┐ ┌────▼────┐
│ MCP  │  │  Auth  │ │  MC    │ │ Memory  │ │ Config  │
└──────┘  └────────┘ └────────┘ └─────────┘ └─────────┘

MCP = Model Context Protocol
MC  = Multi-Agent Coordinator
```

### Agent Loop 核心流程

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

    # 4. 循环继续 - 模型看到结果，决定下一步
```

---

## 技术栈

### 后端核心

| 类别 | 技术 | 版本要求 |
|------|------|----------|
| **语言** | Python | ≥ 3.10 |
| **框架** | Typer | ≥ 0.12.0 |
| **验证** | Pydantic | ≥ 2.0.0 |
| **异步** | asyncio | 内置 |
| **API 客户端** | Anthropic SDK | ≥ 0.40.0 |
|  | OpenAI SDK | ≥ 1.0.0 |
| **网络** | httpx | ≥ 0.27.0 |
|  | websockets | ≥ 12.0 |

### 前端 UI

| 类别 | 技术 |
|------|------|
| **框架** | React 18 + Ink 5 |
| **渲染** | Markdown (marked) |
| **主题** | 自定义 ThemeContext |
| **构建** | TypeScript |

### 消息通道

| 平台 | SDK |
|------|-----|
| Telegram | python-telegram-bot ≥ 21.0.0 |
| Slack | slack-sdk ≥ 3.0.0 |
| Discord | discord.py ≥ 2.0.0 |
| Feishu | lark-oapi ≥ 1.5.0 |

### 工具与测试

| 类别 | 工具 |
|------|------|
| **测试框架** | pytest + pytest-asyncio |
| **代码质量** | ruff, mypy |
| **自动化** | croniter |
| **监控** | watchfiles |

---

## 模块详解

### 1. Engine - Agent Loop 引擎

**路径**: `src/openharness/engine/`

**核心文件**:
- `query_engine.py` - 高级对话引擎
- `query.py` - 核心工具感知查询循环
- `stream_events.py` - 流式事件定义
- `messages.py` - 对话消息模型
- `cost_tracker.py` - Token 用量追踪

**关键类**:

```python
class QueryEngine:
    """顶层引擎，管理完整对话生命周期"""

    def __init__(
        self,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        hook_executor: HookExecutor,
        ...
    ):
        self.messages: list[ConversationMessage] = []
        self.cost_tracker = CostTracker()

    async def run_query(
        self,
        prompt: str,
        max_turns: int = 50
    ) -> AsyncGenerator[StreamEvent, None]:
        """执行一次完整的查询循环"""
```

**消息类型**:

```python
@dataclass
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: list[ContentBlock]  # TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock
```

**流式事件**:

```python
StreamEvent = Union[
    AssistantTextDelta,      # 文本增量
    ToolExecutionStarted,    # 工具开始执行
    ToolExecutionCompleted,  # 工具执行完成
    CompactProgressEvent,    # 上下文压缩进度
    ErrorEvent,              # 错误事件
]
```

**设计亮点**:
- 完全异步，支持流式处理
- 自动重试机制（指数退避）
- Token 计数和成本追踪
- 支持并行工具执行

---

### 2. Tools - 43+ 工具系统

**路径**: `src/openharness/tools/`

**工具基类**:

```python
class BaseTool(ABC, Generic[T]):
    """所有工具的抽象基类"""

    name: str                          # 工具名称
    description: str                    # 工具描述
    input_model: type[T]               # Pydantic 输入模型

    @abstractmethod
    async def execute(
        self,
        arguments: T,
        context: ToolExecutionContext
    ) -> ToolResult:
        """执行工具逻辑"""

    def is_read_only(self, arguments: T) -> bool:
        """判断是否为只读操作"""
        return False

    def to_api_schema(self) -> dict:
        """生成 LLM API 所需的 JSON Schema"""
```

**工具注册表**:

```python
class ToolRegistry:
    """管理所有已注册工具"""

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def to_api_schema(self) -> list[dict]:
        """返回所有工具的 API Schema"""
        return [tool.to_api_schema() for tool in self._tools.values()]
```

**工具分类**:

| 类别 | 工具 | 数量 |
|------|------|------|
| **文件 I/O** | Bash, Read, Write, Edit, Glob, Grep | 6 |
| **搜索** | WebFetch, WebSearch, ToolSearch | 3 |
| **Notebook** | NotebookEdit | 1 |
| **Agent** | Agent, SendMessage, TeamCreate/Delete | 4 |
| **Task** | TaskCreate/Get/List/Update/Stop/Output | 6 |
| **MCP** | MCPTool, ListMcpResources, ReadMcpResource | 3 |
| **Mode** | EnterPlanMode, ExitPlanMode, Worktree | 3 |
| **Schedule** | CronCreate/List/Delete, RemoteTrigger | 4 |
| **Meta** | Skill, Config, Brief, Sleep, AskUser | 5+ |

**示例工具实现**:

```python
class BashInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=120000, description="Timeout in ms")

class BashTool(BaseTool[BashInput]):
    name = "bash"
    description = "Execute a shell command"
    input_model = BashInput

    async def execute(
        self,
        arguments: BashInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        result = await run_shell_command(arguments.command)
        return ToolResult(output=result.stdout, is_error=result.returncode != 0)
```

---

### 3. API - 多提供商客户端层

**路径**: `src/openharness/api/`

**核心接口**:

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

**提供商实现**:

```python
class AnthropicApiClient(SupportsStreamingMessages):
    """Anthropic 原生 API 客户端"""

    async def stream_messages(self, messages, tools, **kwargs):
        async with anthropic.AsyncAnthropic() as client:
            async for event in client.messages.stream(...):
                yield self._convert_event(event)

class OpenAICompatibleClient(SupportsStreamingMessages):
    """OpenAI 兼容 API 客户端"""

    async def stream_messages(self, messages, tools, **kwargs):
        async with openai.AsyncOpenAI() as client:
            response = await client.chat.completions.create(...)
            yield self._convert_response(response)
```

**支持的提供商**:

| 提供商 | 类型 | 认证方式 |
|--------|------|----------|
| Anthropic | 原生 SDK | API Key |
| OpenAI | 兼容 API | API Key |
| GitHub Copilot | OAuth | Device Flow |
| Codex Subscription | 订阅桥接 | 本地凭证 |
| Claude Subscription | 订阅桥接 | 本地凭证 |
| OpenRouter | Gateway | API Key |
| Moonshot/Kimi | 兼容 API | API Key |
| GLM/Zhipu | 兼容 API | API Key |
| DashScope | 兼容 API | API Key |
| Ollama | 本地模型 | 无需认证 |

**重试机制**:

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1.0,
    "max_delay": 30.0,
    "exponential_base": 2,
}
```

---

### 4. Permissions - 权限系统

**路径**: `src/openharness/permissions/`

**权限模式**:

```python
class PermissionMode(str, Enum):
    DEFAULT = "default"      # 变更操作需确认
    PLAN = "plan"            # 阻止所有变更
    FULL_AUTO = "full_auto"  # 允许所有操作
```

**权限检查器**:

```python
class PermissionChecker:
    def __init__(self, settings: PermissionSettings):
        self.settings = settings

    async def check_tool_permission(
        self,
        tool_name: str,
        arguments: BaseModel,
        context: ToolExecutionContext
    ) -> PermissionDecision:
        """检查工具执行权限"""

        # 1. 敏感路径检查（始终生效）
        if self._is_sensitive_path(arguments):
            return PermissionDecision(action="deny", reason="Sensitive path")

        # 2. 显式拒绝列表
        if tool_name in self.settings.denied_tools:
            return PermissionDecision(action="deny")

        # 3. 显式允许列表
        if tool_name in self.settings.allowed_tools:
            return PermissionDecision(action="allow")

        # 4. 路径规则
        if self._matches_path_rule(arguments, self.settings.path_rules):
            return PermissionDecision(action="deny")

        # 5. 命令拒绝模式
        if self._matches_denied_command(arguments):
            return PermissionDecision(action="deny")

        # 6. 根据模式决定
        if self.settings.mode == PermissionMode.PLAN:
            if not tool_is_read_only(tool_name, arguments):
                return PermissionDecision(action="deny")

        return PermissionDecision(action="ask")
```

**敏感路径保护**:

```python
SENSITIVE_PATH_PATTERNS = (
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.gnupg/*",
    "*/.openharness/credentials.json",
    "*/.env",
    "*/credentials.json",
)
```

**配置示例**:

```json
{
  "permission": {
    "mode": "default",
    "path_rules": [
      {"pattern": "/etc/*", "allow": false},
      {"pattern": "~/.config/*", "allow": false}
    ],
    "denied_commands": ["rm -rf /", "DROP TABLE *"],
    "denied_tools": ["BashTool"],
    "allowed_tools": ["FileReadTool"]
  }
}
```

---

### 5. Hooks - 生命周期钩子

**路径**: `src/openharness/hooks/`

**支持的事件**:

```python
class HookEvent(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    NOTIFICATION = "notification"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
```

**钩子类型**:

```python
class CommandHookDefinition(BaseModel):
    """执行 Shell 命令"""
    type: Literal["command"]
    command: str
    timeout: int = 30000

class PromptHookDefinition(BaseModel):
    """调用 LLM 验证"""
    type: Literal["prompt"]
    prompt: str
    model: str = "claude-haiku-4-5"

class HttpHookDefinition(BaseModel):
    """POST 到 HTTP 端点"""
    type: Literal["http"]
    url: str
    headers: dict = {}

class AgentHookDefinition(BaseModel):
    """深度模型验证"""
    type: Literal["agent"]
    agent: str
    prompt: str
```

**执行流程**:

```python
class HookExecutor:
    async def execute(
        self,
        event: HookEvent,
        payload: dict
    ) -> AggregatedHookResult:
        results = []

        for hook in self._registry.get(event):
            if not self._matches_hook(hook, payload):
                continue

            if isinstance(hook, CommandHookDefinition):
                result = await self._run_command_hook(hook, payload)
            elif isinstance(hook, PromptHookDefinition):
                result = await self._run_prompt_hook(hook, payload)
            elif isinstance(hook, HttpHookDefinition):
                result = await self._run_http_hook(hook, payload)
            elif isinstance(hook, AgentHookDefinition):
                result = await self._run_agent_hook(hook, payload)

            results.append(result)

            # 如果钩子返回 block，停止执行
            if result.action == "block":
                break

        return AggregatedHookResult(results=results)
```

**配置示例**:

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "echo 'Tool ${tool_name} about to execute'",
        "match": {"tool_name": "BashTool"}
      }
    ],
    "post_tool_use": [
      {
        "type": "prompt",
        "prompt": "Review the tool result and verify it's safe",
        "match": {"tool_name": "FileWriteTool"}
      }
    ]
  }
}
```

---

### 6. MCP - Model Context Protocol

**路径**: `src/openharness/mcp/`

**核心类**:

```python
class McpClientManager:
    """管理所有 MCP 服务器连接"""

    async def connect_all(self) -> None:
        for name, config in self._server_configs.items():
            if isinstance(config, McpStdioServerConfig):
                await self._connect_stdio(name, config)
            elif isinstance(config, McpHttpServerConfig):
                await self._connect_http(name, config)

    async def list_tools(self) -> list[McpToolInfo]:
        """列出所有 MCP 工具"""
        tools = []
        for server_name, session in self._sessions.items():
            tools.extend(await session.list_tools())
        return tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict
    ) -> McpToolResult:
        """调用 MCP 工具"""
        session = self._sessions[server_name]
        return await session.call_tool(tool_name, arguments)
```

**配置格式**:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["--root", "/home/user/projects"],
      "transport": "stdio"
    },
    "http-server": {
      "url": "http://localhost:8080/mcp",
      "transport": "http"
    }
  }
}
```

**传输协议**:
- **stdio** - 通过标准输入输出通信
- **http** - HTTP WebSocket 通信

**工具适配**:

```python
class MCPTool(BaseTool):
    """将 MCP 工具适配为 OpenHarness 工具"""

    def __init__(self, server_name: str, tool_info: McpToolInfo):
        self.server_name = server_name
        self.mcp_tool_info = tool_info
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

---

### 7. Memory - 记忆系统

**路径**: `src/openharness/memory/`

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
    """生成项目专属记忆目录"""
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return get_data_dir() / "memory" / f"{path.name}-{digest}"
```

**记忆管理器**:

```python
class MemoryManager:
    """管理跨会话持久化记忆"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir

    async def load_relevant_memories(
        self,
        query: str,
        max_memories: int = 10
    ) -> list[MemoryEntry]:
        """加载与查询相关的记忆"""
        all_memories = self._scan_memories()

        # 使用 LLM 进行相关性排序
        scored = []
        for memory in all_memories:
            score = await self._score_relevance(query, memory)
            scored.append((memory, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, s in scored[:max_memories]]

    def create_memory(
        self,
        title: str,
        content: str,
        tags: list[str] = None
    ) -> Path:
        """创建新的记忆文件"""
        filename = self._sanitize_filename(title) + ".md"
        path = self.memory_dir / filename

        frontmatter = {
            "title": title,
            "created": datetime.now().isoformat(),
            "tags": tags or [],
        }

        path.write_text(self._format_memory(frontmatter, content))
        self._update_memory_index()

        return path
```

**自动压缩**:

```python
async def compact_conversation(
    messages: list[ConversationMessage],
    model: str = "claude-haiku-4-5"
) -> list[ConversationMessage]:
    """压缩对话历史"""

    # 微压缩：清除旧工具结果
    messages = micro_compact(messages)

    # 宏压缩：LLM 总结
    if estimate_tokens(messages) > THRESHOLD:
        summary = await summarize_with_llm(messages, model)
        messages = [SystemMessage(summary)] + messages[-N:]

    return messages
```

---

### 8. Coordinator & Swarm - 多 Agent 协调

**路径**:
- `src/openharness/coordinator/` - 协调器
- `src/openharness/swarm/` - Swarm 架构

**协调器模式**:

```python
class TeamRegistry:
    """内存中的团队注册表"""

    def __init__(self):
        self._teams: dict[str, TeamRecord] = {}

    def register_team(self, team: TeamRecord) -> None:
        self._teams[team.team_id] = team

    def get_team(self, team_id: str) -> TeamRecord:
        return self._teams[team_id]

    def list_teams(self) -> list[TeamRecord]:
        return list(self._teams.values())
```

**Agent 定义**:

```python
class AgentDefinition(BaseModel):
    """完整的 Agent 配置"""

    name: str
    prompt: str
    tools: list[str]              # 允许的工具
    skills: list[str]             # 加载的技能
    mcp_servers: list[str]       # MCP 服务器
    hooks: dict[str, list]       # 生命周期钩子
    permissions: PermissionSettings
    model: str
    max_turns: int = 50
```

**Swarm 后端类型**:

```python
BackendType = Literal[
    "subprocess",    # 子进程
    "in_process",    # 进程内
    "tmux",          # tmux 会话
    "iterm2"         # iTerm2 标签页
]
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

**子进程后端**:

```python
class SubprocessBackend:
    """子进程 Agent 后端"""

    async def spawn_agent(
        self,
        agent_def: AgentDefinition,
        cwd: str
    ) -> AgentHandle:
        """派生子 Agent"""

        # 准备配置文件
        config_path = self._write_agent_config(agent_def)

        # 启动子进程
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m", "openharness",
            "--agent-config", str(config_path),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        return AgentHandle(
            agent_id=agent_def.name,
            process=process,
            inbox=self._inbox_path,
            outbox=self._outbox_path,
        )

    async def send_message(
        self,
        agent_id: str,
        message: dict
    ) -> None:
        """发送消息到 Agent"""
        msg_path = self._inbox_path / f"{time.time()}_{uuid4()}.json"
        msg_path.write_text(json.dumps(message))

    async def receive_messages(
        self,
        agent_id: str
    ) -> list[dict]:
        """接收 Agent 的消息"""
        messages = []
        for msg_file in self._outbox_path.glob("*.json"):
            messages.append(json.loads(msg_file.read_text()))
            msg_file.unlink()
        return messages
```

---

### 9. Prompts - 上下文组装

**路径**: `src/openharness/prompts/`

**系统提示词结构**:

```
1. 基础系统提示词（身份、行为规范）
2. 环境信息（OS、Shell、Git、Python）
3. 推理设置（effort、passes）
4. 可用技能列表
5. 委托和子代理说明
6. CLAUDE.md 项目指令
7. 本地环境规则
8. Issue/PR 上下文
9. 项目记忆
```

**CLAUDE.md 发现**:

```python
def discover_claude_md_files(cwd: str | Path) -> list[Path]:
    """从当前目录向上搜索 CLAUDE.md"""
    results = []
    path = Path(cwd).resolve()

    while path != path.parent:
        # 检查 CLAUDE.md
        claude_md = path / "CLAUDE.md"
        if claude_md.exists():
            results.append(claude_md)

        # 检查 .claude/CLAUDE.md
        dot_claude = path / ".claude" / "CLAUDE.md"
        if dot_claude.exists():
            results.append(dot_claude)

        # 检查 .claude/rules/*.md
        rules_dir = path / ".claude" / "rules"
        if rules_dir.exists():
            results.extend(rules_dir.glob("*.md"))

        path = path.parent

    return results
```

**上下文组装器**:

```python
def build_system_prompt(
    cwd: str,
    settings: Settings,
    skills: list[SkillDefinition],
    memory_manager: MemoryManager | None = None
) -> str:
    """组装完整系统提示词"""

    sections = [
        get_base_system_prompt(),
        get_environment_info(),
        format_available_skills(skills),
        format_subagent_instructions(),
    ]

    # 项目 CLAUDE.md
    claude_md_files = discover_claude_md_files(cwd)
    for file in claude_md_files:
        sections.append(file.read_text())

    # 项目记忆
    if memory_manager:
        memories = await memory_manager.load_relevant_memories()
        sections.append(format_memories(memories))

    return "\n\n---\n\n".join(sections)
```

---

### 10. Config - 多层配置

**路径**: `src/openharness/config/`

**配置优先级**:

```
1. CLI 参数（最高优先级）
   ↓
2. 环境变量（ANTHROPIC_API_KEY、OPENHARNESS_MODEL 等）
   ↓
3. 配置文件（~/.openharness/settings.json）
   ↓
4. 默认值（最低优先级）
```

**关键路径**:

```python
def get_config_dir() -> Path:
    """配置目录"""
    return Path.home() / ".openharness"

def get_data_dir() -> Path:
    """数据目录"""
    return get_config_dir() / "data"

def get_sessions_dir() -> Path:
    """会话目录"""
    return get_data_dir() / "sessions"

def get_tasks_dir() -> Path:
    """任务目录"""
    return get_data_dir() / "tasks"

def get_skills_dir() -> Path:
    """技能目录"""
    return get_config_dir() / "skills"

def get_plugins_dir() -> Path:
    """插件目录"""
    return get_config_dir() / "plugins"
```

**设置模型**:

```python
class Settings(BaseModel):
    """顶层设置模型"""

    # 权限配置
    permission: PermissionSettings = PermissionSettings()

    # 记忆配置
    memory: MemorySettings = MemorySettings()

    # 沙箱配置
    sandbox: SandboxSettings = SandboxSettings()

    # 提供商配置
    provider_profiles: dict[str, ProviderProfile] = {}

    # MCP 服务器配置
    mcp_servers: dict[str, McpServerConfig] = {}

    # 钩子配置
    hooks: dict[str, list] = {}

    # 其他配置
    model: str = "claude-sonnet-4-6"
    max_turns: int = 50
    output_format: str = "text"
```

**配置示例**:

```json
{
  "model": "claude-sonnet-4-6",
  "max_turns": 50,
  "output_format": "text",
  "permission": {
    "mode": "default",
    "path_rules": [],
    "denied_commands": []
  },
  "provider_profiles": {
    "anthropic": {
      "provider": "anthropic",
      "api_format": "anthropic",
      "auth_source": "anthropic_api_key",
      "model": "claude-sonnet-4-6"
    }
  },
  "mcp_servers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["--root", "/home/user"]
    }
  }
}
```

---

### 11. UI - React TUI 前后端

**路径**: `src/openharness/ui/`

**前后端协议**:

```python
class FrontendRequest(BaseModel):
    """前端 -> 后端请求"""

    type: Literal[
        "submit_line",
        "permission_response",
        "interrupt",
        "shutdown",
        "resume",
        "load_session"
    ]
    line: str | None = None
    permission_granted: bool | None = None
    session_id: str | None = None

class BackendEvent(BaseModel):
    """后端 -> 前端事件"""

    type: Literal[
        "ready",
        "transcript_item",
        "tool_started",
        "tool_completed",
        "permission_request",
        "error",
        "shutdown"
    ]
    item: TranscriptItem | None = None
    tool_name: str | None = None
    tool_result: str | None = None
    permission_request: PermissionRequest | None = None
```

**后端主机**:

```python
class BackendHost:
    """JSON-lines 后端主机"""

    async def start(self) -> None:
        """启动后端进程"""
        self.process = await asyncio.create_subprocess_exec(
            *self.backend_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        # 启动事件读取任务
        asyncio.create_task(self._read_events())

    async def send_request(self, request: FrontendRequest) -> None:
        """发送请求到后端"""
        line = json.dumps(request.model_dump()) + "\n"
        self.process.stdin.write(line.encode())
        await self.process.stdin.drain()

    async def _read_events(self) -> None:
        """读取后端事件"""
        async for line in self.process.stdout:
            if line.startswith(b"OHJSON:"):
                event = BackendEvent.model_validate_json(line[7:])
                await self._handle_event(event)
```

**React 前端**:

```
frontend/terminal/
├── src/
│   ├── index.tsx
│   ├── App.tsx                    # 主应用
│   ├── types.ts                   # 类型定义
│   ├── components/
│   │   ├── ConversationView.tsx  # 对话视图
│   │   ├── PromptInput.tsx        # 输入框
│   │   ├── ToolCallDisplay.tsx    # 工具调用展示
│   │   ├── CommandPicker.tsx      # 命令选择器
│   │   ├── PermissionModal.tsx    # 权限对话框
│   │   ├── TodoPanel.tsx          # Todo 面板
│   │   └── SwarmPanel.tsx         # Swarm 面板
│   ├── hooks/
│   │   └── useBackendSession.ts   # 后端会话 hook
│   └── theme/
│       ├── ThemeContext.tsx       # 主题上下文
│       └── builtinThemes.ts       # 内置主题
└── package.json
```

**关键特性**:
- 基于 Ink 5（React for CLI）
- JSON-lines 协议通信
- Token 级流式渲染（30fps 缓冲）
- Markdown 渲染支持
- 主题切换系统

---

### 12. Skills - 技能系统

**路径**: `src/openharness/skills/`

**技能定义**:

```python
@dataclass(frozen=True)
class SkillDefinition:
    """技能定义"""

    name: str              # 唯一标识
    description: str       # 简短描述
    content: str           # Markdown 内容
    source: str            # "builtin" | "user" | "plugin"
    path: str | None       # 文件路径
```

**技能文件格式**:

```markdown
---
name: commit
description: Create clean, well-structured git commits
---

# Git Commit Skill

## When to use
Use when the user asks to commit changes or create a commit.

## Workflow
1. Run git status and git diff to see changes
2. Analyze the changes and draft a commit message
3. Stage relevant files
4. Create the commit
5. Verify the commit

## Best Practices
- Keep commits atomic
- Write clear, descriptive messages
- Follow conventional commits format
```

**加载路径**:

```python
def load_skills(
    settings: Settings,
    cwd: str,
    extra_roots: list[str] = None
) -> list[SkillDefinition]:
    """加载所有技能"""

    skills = []

    # 1. 内置技能
    for skill_file in BUNDLED_SKILLS_DIR.glob("*.md"):
        skills.append(parse_skill_file(skill_file, source="builtin"))

    # 2. 用户技能
    user_skills_dir = get_skills_dir()
    if user_skills_dir.exists():
        for skill_file in user_skills_dir.glob("*.md"):
            skills.append(parse_skill_file(skill_file, source="user"))

    # 3. 插件贡献技能
    plugins = load_plugins(settings, cwd)
    for plugin in plugins:
        skills.extend(plugin.skills)

    return skills
```

**兼容性**:
- 完全兼容 [anthropics/skills](https://github.com/anthropics/skills)
- 只需将 `.md` 文件复制到 `~/.openharness/skills/`

---

### 13. Plugins - 插件系统

**路径**: `src/openharness/plugins/`

**插件结构**:

```
<plugin-dir>/
├── plugin.json        # 清单文件
├── skills/             # 贡献的技能
│   ├── skill1.md
│   └── skill2.md
├── agents/             # Agent 定义
│   ├── agent1.md
│   └── agent2.md
├── hooks.json          # 钩子配置
├── mcp.json            # MCP 服务器配置
└── tools/              # Python 工具模块
    └── custom_tool.py
```

**插件清单**:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin",
  "author": "Your Name",
  "skills": ["skills/*.md"],
  "agents": ["agents/*.md"],
  "hooks": "hooks.json",
  "mcp": "mcp.json",
  "tools": ["tools/*.py"]
}
```

**插件加载器**:

```python
class PluginLoader:
    """插件加载器"""

    def load_plugins(
        self,
        settings: Settings,
        cwd: str,
        extra_roots: list[str] = None
    ) -> list[LoadedPlugin]:
        """加载所有插件"""

        plugins = []

        # 1. 用户插件目录
        user_plugins_dir = get_plugins_dir()
        if user_plugins_dir.exists():
            for plugin_dir in user_plugins_dir.iterdir():
                if plugin_dir.is_dir():
                    plugins.append(self._load_plugin(plugin_dir))

        # 2. 项目插件目录（需要权限）
        if settings.allow_project_plugins:
            project_plugins = Path(cwd) / ".openharness" / "plugins"
            if project_plugins.exists():
                for plugin_dir in project_plugins.iterdir():
                    plugins.append(self._load_plugin(plugin_dir))

        return plugins

    def _load_plugin(self, plugin_dir: Path) -> LoadedPlugin:
        """加载单个插件"""
        manifest_file = plugin_dir / "plugin.json"
        manifest = PluginManifest.model_validate_json(manifest_file.read_text())

        return LoadedPlugin(
            manifest=manifest,
            skills=self._load_skills(plugin_dir),
            agents=self._load_agents(plugin_dir),
            hooks=self._load_hooks(plugin_dir),
            mcp_servers=self._load_mcp(plugin_dir),
            tools=self._load_tools(plugin_dir),
        )
```

**兼容性**:
- 完全兼容 [claude-code plugins](https://github.com/anthropics/claude-code/tree/main/plugins)
- 测试通过 12+ 官方插件

---

### 14. Tasks - 后台任务管理

**路径**: `src/openharness/tasks/`

**任务类型**:

```python
TaskType = Literal[
    "local_bash",        # 本地 Shell 命令
    "local_agent",       # 本地 Agent
    "remote_agent",      # 远程 Agent
    "in_process_teammate"  # 进程内队友
]

TaskStatus = Literal[
    "pending",           # 等待中
    "running",           # 运行中
    "completed",         # 已完成
    "failed",            # 失败
    "killed"             # 已终止
]
```

**任务管理器**:

```python
class BackgroundTaskManager:
    """后台任务管理器"""

    def __init__(self):
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.Process] = {}

    async def create_shell_task(
        self,
        command: str,
        description: str,
        cwd: str,
        timeout: int = None
    ) -> TaskRecord:
        """创建 Shell 任务"""

        task_id = str(uuid4())
        task = TaskRecord(
            task_id=task_id,
            task_type="local_bash",
            description=description,
            status="pending",
            created_at=datetime.now(),
        )

        self._tasks[task_id] = task

        # 启动进程
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._processes[task_id] = process
        task.status = "running"

        # 异步等待完成
        asyncio.create_task(self._wait_for_task(task_id, timeout))

        return task

    async def read_output(self, task_id: str) -> str:
        """读取任务输出"""
        process = self._processes[task_id]
        output = await process.stdout.read()
        return output.decode()

    async def stop_task(self, task_id: str) -> bool:
        """停止任务"""
        process = self._processes.get(task_id)
        if process:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()

            self._tasks[task_id].status = "killed"
            return True
        return False
```

**任务持久化**:

```
~/.openharness/data/tasks/
├── <task_id>.json
├── <task_id>.output
└── ...
```

---

### 15. Sandbox - 沙箱系统

**路径**: `src/openharness/sandbox/`

**沙箱类型**:

```python
class SandboxBackend(str, Enum):
    SRT = "srt"          # sandbox-runtime (bwrap/sandbox-exec)
    DOCKER = "docker"   # Docker 容器
```

**沙箱配置**:

```python
class SandboxSettings(BaseModel):
    """沙箱配置"""

    enabled: bool = False
    backend: SandboxBackend = SandboxBackend.SRT

    # 网络配置
    network: SandboxNetworkSettings

    # 文件系统配置
    filesystem: SandboxFilesystemSettings

    # Docker 配置
    docker: DockerSandboxSettings
```

**Docker 后端**:

```python
class DockerBackend:
    """Docker 沙箱后端"""

    async def create_container(
        self,
        image: str,
        command: list[str],
        working_dir: str,
        mounts: list[Mount],
        network: str = "none",
        resource_limits: dict = None
    ) -> str:
        """创建 Docker 容器"""

        container = await self.docker_client.containers.create(
            image=image,
            command=command,
            working_dir=working_dir,
            mounts=[{"Type": "bind", "Source": m.source, "Target": m.target} for m in mounts],
            network=network,
            host_config={
                "SecurityOpt": ["no-new-privileges"],
                "Memory": resource_limits.get("memory", "512m"),
                "CpuQuota": resource_limits.get("cpu_quota", 50000),
            },
        )

        return container.id

    async def execute_in_container(
        self,
        container_id: str,
        command: list[str]
    ) -> tuple[int, str, str]:
        """在容器中执行命令"""

        exec_instance = await self.docker_client.containers.exec_create(
            container_id,
            cmd=command,
        )

        output = await self.docker_client.containers.exec_start(exec_instance.id)

        return output.exit_code, output.output, output.error
```

**路径验证器**:

```python
class PathValidator:
    """验证沙箱路径访问"""

    def __init__(self, sandbox_root: Path):
        self.sandbox_root = sandbox_root.resolve()

    def validate_path(self, path: str | Path) -> Path:
        """验证路径是否在沙箱内"""
        resolved = (self.sandbox_root / path).resolve()

        # 检查是否逃逸沙箱
        if not str(resolved).startswith(str(self.sandbox_root)):
            raise SandboxEscapeError(f"Path escapes sandbox: {path}")

        return resolved
```

---

### 16. Channels - 消息通道

**路径**: `src/openharness/channels/`

**基础通道接口**:

```python
class BaseChannel(ABC):
    """所有消息通道的基类"""

    @abstractmethod
    async def start(self) -> None:
        """启动通道"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止通道"""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """发送消息"""
        pass

    @abstractmethod
    def is_allowed(self, sender_id: str) -> bool:
        """检查发送者权限"""
        pass
```

**消息模型**:

```python
class InboundMessage(BaseModel):
    """入站消息"""

    channel: str              # "telegram" | "slack" | ...
    sender_id: str            # 发送者 ID
    chat_id: str              # 聊天 ID
    thread_id: str | None     # 线程 ID
    text: str                 # 消息文本
    attachments: list[Attachment]  # 附件

class OutboundMessage(BaseModel):
    """出站消息"""

    channel: str
    chat_id: str
    thread_id: str | None
    text: str
    reply_to: str | None
```

**消息总线**:

```python
class MessageBus:
    """消息总线"""

    def __init__(self):
        self._inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布入站消息"""
        await self._inbound_queue.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费入站消息"""
        return await self._inbound_queue.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布出站消息"""
        await self._outbound_queue.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """消费出站消息"""
        return await self._outbound_queue.get()
```

**支持的平台**:

| 平台 | SDK | 实现文件 |
|------|-----|----------|
| Telegram | python-telegram-bot | `impl/telegram.py` |
| Slack | slack-sdk | `impl/slack.py` |
| Discord | discord.py | `impl/discord.py` |
| Feishu | lark-oapi | `impl/feishu.py` |
| DingTalk | - | `impl/dingtalk.py` |
| Matrix | - | `impl/matrix.py` |
| QQ | - | `impl/qq.py` |
| WhatsApp | - | `impl/whatsapp.py` |
| Email | - | `impl/email.py` |
| MoChat | - | `impl/mochat.py` |

---

### 17. Auth - 认证系统

**路径**: `src/openharness/auth/`

**认证管理器**:

```python
class AuthManager:
    """认证管理器"""

    def __init__(self, storage: CredentialStorage):
        self.storage = storage

    async def authenticate(
        self,
        provider: str,
        auth_source: str,
        **kwargs
    ) -> bool:
        """执行认证流程"""

        if auth_source == "anthropic_api_key":
            api_key = kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return False
            self.storage.store_credential(provider, "api_key", api_key)
            return True

        elif auth_source == "copilot_oauth":
            # OAuth device flow
            device_code = await self._get_device_code()
            print(f"Please visit: {device_code.verification_uri}")
            print(f"Enter code: {device_code.user_code}")

            token = await self._poll_for_token(device_code.device_code)
            self.storage.store_credential(provider, "oauth_token", token)
            return True

        return False
```

**凭证存储**:

```python
class CredentialStorage:
    """凭证存储"""

    def __init__(self, use_keyring: bool = True):
        self.use_keyring = use_keyring and keyring.is_available()

    def store_credential(
        self,
        provider: str,
        key: str,
        value: str
    ) -> None:
        """存储凭证"""

        if self.use_keyring:
            keyring.set_password("openharness", f"{provider}:{key}", value)
        else:
            # 存储到文件
            creds_file = get_config_dir() / "credentials.json"
            creds = json.loads(creds_file.read_text()) if creds_file.exists() else {}
            creds.setdefault(provider, {})[key] = value
            creds_file.write_text(json.dumps(creds))

    def load_credential(
        self,
        provider: str,
        key: str
    ) -> str | None:
        """加载凭证"""

        if self.use_keyring:
            return keyring.get_password("openharness", f"{provider}:{key}")
        else:
            creds_file = get_config_dir() / "credentials.json"
            if not creds_file.exists():
                return None
            creds = json.loads(creds_file.read_text())
            return creds.get(provider, {}).get(key)
```

**支持的认证源**:

| 认证源 | 描述 |
|--------|------|
| `anthropic_api_key` | Anthropic API Key |
| `openai_api_key` | OpenAI API Key |
| `copilot_oauth` | GitHub Copilot OAuth |
| `codex_subscription` | Codex 订阅凭证 |
| `claude_subscription` | Claude 订阅凭证 |
| `moonshot_api_key` | Moonshot/Kimi API Key |
| `glm_api_key` | GLM/Zhipu API Key |

---

### 18. Services - 核心服务

**路径**: `src/openharness/services/`

#### compact/ - 对话压缩

```python
class CompactService:
    """对话压缩服务"""

    async def compact_if_needed(
        self,
        messages: list[ConversationMessage],
        threshold: int = 80000
    ) -> list[ConversationMessage]:
        """自动压缩对话"""

        if estimate_tokens(messages) < threshold:
            return messages

        # 微压缩：清除旧工具结果
        messages = self.micro_compact(messages)

        # 宏压缩：LLM 总结
        if estimate_tokens(messages) > threshold:
            messages = await self.macro_compact(messages)

        return messages

    def micro_compact(
        self,
        messages: list[ConversationMessage]
    ) -> list[ConversationMessage]:
        """微压缩：清除工具结果"""
        compacted = []
        for msg in messages:
            if msg.role == "user":
                compacted.append(msg)
            elif msg.role == "assistant":
                # 保留文本块，清除工具结果
                content = [b for b in msg.content if isinstance(b, TextBlock)]
                if content:
                    compacted.append(msg.__class__(role="assistant", content=content))
        return compacted

    async def macro_compact(
        self,
        messages: list[ConversationMessage]
    ) -> list[ConversationMessage]:
        """宏压缩：LLM 总结"""

        # 使用 Haiku 进行总结
        summary = await self.summarize_with_llm(messages)

        # 保留最近的消息
        return [
            SystemMessage(summary),
            messages[-10:]
        ]
```

#### oauth/ - OAuth 辅助

```python
class OAuthHelper:
    """OAuth 辅助服务"""

    async def device_flow(
        self,
        client_id: str,
        device_code_url: str,
        token_url: str
    ) -> str:
        """执行设备流程"""

        # 1. 获取设备码
        async with httpx.AsyncClient() as client:
            resp = await client.post(device_code_url, json={"client_id": client_id})
            data = resp.json()

        # 2. 显示用户码
        print(f"Visit: {data['verification_uri']}")
        print(f"Code: {data['user_code']}")

        # 3. 轮询等待授权
        start = time.time()
        while time.time() - start < data["expires_in"]:
            await asyncio.sleep(data["interval"])

            async with httpx.AsyncClient() as client:
                resp = await client.post(token_url, json={
                    "client_id": client_id,
                    "device_code": data["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                })

                if resp.status_code == 200:
                    return resp.json()["access_token"]

        raise TimeoutError("OAuth device flow timed out")
```

#### lsp/ - 轻量级代码智能

```python
class LightweightLSP:
    """轻量级 LSP 服务"""

    def find_definition(
        self,
        file_path: str,
        symbol: str
    ) -> Location | None:
        """查找定义"""

        # 使用 AST 解析
        tree = ast.parse(Path(file_path).read_text())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    return Location(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                    )

        return None

    def find_references(
        self,
        file_path: str,
        symbol: str
    ) -> list[Location]:
        """查找引用"""

        refs = []
        content = Path(file_path).read_text()

        # 简单文本搜索
        for match in re.finditer(rf"\b{re.escape(symbol)}\b", content):
            line = content[:match.start()].count("\n") + 1
            refs.append(Location(file=file_path, line=line))

        return refs
```

---

## ohmo - 个人代理应用

**路径**: `ohmo/`

### 工作空间结构

```
~/.ohmo/
├── SOUL.md          # Agent 人格定义
├── IDENTITY.md      # 身份信息
├── user.md          # 用户档案
├── BOOTSTRAP.md     # 首次运行引导
├── memory/          # 个人记忆
│   ├── preferences.md
│   └── ...
├── sessions/        # 会话存储
│   ├── latest.json
│   └── session-*.json
├── state.json       # 状态
└── gateway.json     # Gateway 配置
```

### 核心模块

#### workspace.py - 工作空间管理

```python
def init_workspace(workspace_dir: Path = None) -> None:
    """初始化 ohmo 工作空间"""

    workspace_dir = workspace_dir or Path.home() / ".ohmo"
    workspace_dir.mkdir(exist_ok=True)

    # 创建模板文件
    (workspace_dir / "SOUL.md").write_text(SOUL_TEMPLATE)
    (workspace_dir / "IDENTITY.md").write_text(IDENTITY_TEMPLATE)
    (workspace_dir / "user.md").write_text(USER_TEMPLATE)
    (workspace_dir / "BOOTSTRAP.md").write_text(BOOTSTRAP_TEMPLATE)

    # 创建目录
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "sessions").mkdir(exist_ok=True)

SOUL_TEMPLATE = """
# ohmo Soul

You are ohmo, a personal AI assistant that works for the user.

## Core Principles
- **Autonomy**: Take initiative without waiting for permission
- **Continuity**: Remember context across sessions
- **Reliability**: Deliver results, not just suggestions
- **Safety**: Respect boundaries and ask when uncertain

## Behavioral Guidelines
...
"""
```

#### prompts.py - 系统提示组装

```python
def build_ohmo_system_prompt(
    cwd: str,
    workspace: Path
) -> str:
    """组装 ohmo 系统提示词"""

    sections = [
        # 1. 基础 OpenHarness 系统提示
        get_base_system_prompt(),

        # 2. Agent 人格
        (workspace / "SOUL.md").read_text(),

        # 3. 身份信息
        (workspace / "IDENTITY.md").read_text(),

        # 4. 用户档案
        (workspace / "user.md").read_text(),

        # 5. 首次运行引导
        (workspace / "BOOTSTRAP.md").read_text(),

        # 6. 工作空间信息
        f"Working directory: {cwd}",

        # 7. 个人记忆
        load_memory_prompt(workspace / "memory"),
    ]

    return "\n\n---\n\n".join(sections)
```

#### gateway/ - 消息网关

**架构**:

```
MessageBus ←→ ChannelManager ←→ OhmoGatewayBridge ←→ OhmoSessionRuntimePool
     ↑                                                ↓
  Channel                                      QueryEngine
  (Telegram/Slack/Discord/Feishu)
```

**OhmoGatewayBridge**:

```python
class OhmoGatewayBridge:
    """Gateway 桥接器"""

    async def run(self) -> None:
        """运行桥接器"""

        while True:
            # 1. 接收入站消息
            inbound = await self.message_bus.consume_inbound()

            # 2. 获取或创建运行时
            session_key = self.router.route(inbound)
            runtime = await self.runtime_pool.get_or_create(session_key)

            # 3. 发送消息到运行时
            await runtime.send_message(inbound.text)

            # 4. 收集流式回复
            async for chunk in runtime.stream_response():
                outbound = OutboundMessage(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    thread_id=inbound.thread_id,
                    text=chunk,
                )
                await self.message_bus.publish_outbound(outbound)
```

**会话路由**:

```python
class SessionRouter:
    """会话路由器"""

    def route(self, msg: InboundMessage) -> str:
        """路由消息到会话"""

        # 格式: channel:chat_id:thread_id:sender_id
        return f"{msg.channel}:{msg.chat_id}:{msg.thread_id or 'main'}:{msg.sender_id}"
```

---

## 前后端架构

### React TUI 前端

**技术栈**:
- React 18 + Ink 5
- TypeScript
- marked (Markdown 渲染)

**关键组件**:

| 组件 | 职责 |
|------|------|
| `App.tsx` | 主应用，管理全局状态 |
| `ConversationView` | 对话历史展示 |
| `PromptInput` | 输入框 + 命令选择器 |
| `ToolCallDisplay` | 工具调用可视化 |
| `PermissionModal` | 权限请求对话框 |
| `TodoPanel` | Todo 列表面板 |
| `SwarmPanel` | 多 Agent 状态面板 |

**数据流**:

```
User Input
    ↓
PromptInput
    ↓
FrontendRequest (submit_line)
    ↓ JSON-lines
BackendHost
    ↓
BackendEvent (transcript_item, tool_started, ...)
    ↓
ConversationView (update state)
```

### 后端主机

```python
class BackendHost:
    """JSON-lines 后端主机"""

    async def run(self) -> None:
        """运行后端"""

        # 1. 启动后端进程
        await self.start()

        # 2. 等待 ready 事件
        await self._wait_for_ready()

        # 3. 主循环
        while True:
            # 接收前端请求
            request = await self._receive_from_frontend()

            # 处理请求
            if request.type == "submit_line":
                await self._handle_user_input(request.line)
            elif request.type == "permission_response":
                await self._handle_permission_response(request)
            elif request.type == "shutdown":
                break

        # 4. 清理
        await self.stop()
```

---

## 测试体系

### 测试结构

```
tests/
├── conftest.py                    # 测试配置
├── test_api/                      # API 客户端测试
│   ├── test_anthropic_client.py
│   ├── test_openai_client.py
│   ├── test_copilot_client.py
│   └── test_codex_client.py
├── test_auth/                     # 认证测试
├── test_engine/                   # 引擎测试
├── test_tools/                    # 工具测试
├── test_permissions/              # 权限测试
├── test_hooks/                    # 钩子测试
├── test_mcp/                      # MCP 测试
├── test_swarm/                    # 多 Agent 测试
├── test_ui/                       # UI 测试
└── ...

scripts/
├── e2e_smoke.py                   # E2E 冒烟测试
├── test_harness_features.py       # Harness 特性测试
├── test_real_skills_plugins.py    # 真实技能/插件测试
├── react_tui_e2e.py               # React TUI E2E
└── test_docker_sandbox_e2e.py     # Docker 沙箱测试
```

### 测试覆盖

| 类别 | 数量 | 状态 |
|------|------|------|
| 单元测试 + 集成测试 | 114+ | ✅ 全部通过 |
| CLI 标志 E2E | 6 | ✅ 真实模型调用 |
| Harness 特性 E2E | 9 | ✅ 重试/技能/并行/权限 |
| React TUI E2E | 3 | ✅ 欢迎/对话/状态 |
| TUI 交互 E2E | 4 | ✅ 命令/权限/快捷键 |
| 真实技能 + 插件 | 12 | ✅ anthropics/skills + claude-code/plugins |

---

## 依赖关系图

```
用户界面层
    │
    ├── ui/ (app, backend_host, runtime)
    │       ↓
    │   engine/ (query_engine, query)
    │       ↓
    ├── tools/ ──── mcp/ ──── auth/
    │       ↓         ↓        ↓
    │   api/ ────── hooks/ ── permissions/
    │       ↓         ↓        ↓
    │   prompts/ ─── config/
    │       ↓         ↓
    │   memory/ ─── coordinator/ ── swarm/
    │                ↓
    │            channels/
    │                ↓
    └─────────── services/
                    ↓
              sandbox/
```

**核心依赖流**:

1. `ui/` → `engine/` → `tools/`, `api/`, `hooks/`, `permissions/`
2. `tools/` → `mcp/`, `auth/`
3. `engine/` → `prompts/` → `memory/`
4. `coordinator/` → `swarm/` → `channels/`
5. 所有模块 → `config/` → `services/`

---

## 扩展机制

### 1. 添加自定义工具

```python
# my_tool.py
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    query: str = Field(description="Search query")

class MyTool(BaseTool[MyToolInput]):
    name = "my_tool"
    description = "Does something useful"
    input_model = MyToolInput

    async def execute(
        self,
        arguments: MyToolInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        result = do_something(arguments.query)
        return ToolResult(output=result)

# 注册工具
registry.register(MyTool())
```

### 2. 添加自定义技能

```markdown
<!-- ~/.openharness/skills/my-skill.md -->
---
name: my-skill
description: Expert guidance for my specific domain
---

# My Skill

## When to use
Use when the user asks about [your domain].

## Workflow
1. Step one
2. Step two
```

### 3. 添加自定义插件

```
~/.openharness/plugins/my-plugin/
├── plugin.json
├── skills/
│   └── skill1.md
├── agents/
│   └── agent1.md
├── hooks.json
└── mcp.json
```

### 4. 添加自定义钩子

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "echo 'Tool ${tool_name} starting'",
        "match": {"tool_name": "BashTool"}
      }
    ]
  }
}
```

---

## 部署架构

### 本地开发

```bash
# 安装
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness
uv sync --extra dev

# 测试
uv run pytest -q

# 运行
uv run oh
```

### 生产部署

```bash
# 安装
pip install openharness-ai

# 配置
oh setup

# 运行
oh
```

### Docker 部署

```dockerfile
FROM python:3.11-slim

RUN pip install openharness-ai

ENV OPENHARNESS_MODEL=claude-sonnet-4-6
ENV ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}

CMD ["oh"]
```

### Gateway 部署

```bash
# 初始化
ohmo init

# 配置通道
ohmo config

# 启动 Gateway
ohmo gateway start

# 查看状态
ohmo gateway status

# 后台运行
ohmo gateway run --daemon
```

---

## 总结

OpenHarness 是一个设计精良、功能完备的 AI Agent 框架：

### 架构亮点

1. **清晰的模块边界** - 每个模块职责单一，易于理解和维护
2. **丰富的扩展点** - Hooks、Plugins、Skills、MCP 四大扩展机制
3. **多提供商支持** - 统一的 API 抽象，支持 10+ LLM 提供商
4. **完善的安全模型** - 权限系统、沙箱、敏感路径保护三重保障
5. **多 Agent 协调** - Swarm 架构支持团队协作和任务委托
6. **多通道集成** - 支持 10+ 消息平台，Gateway 架构灵活可扩展

### 适用场景

- **研究** - 理解生产级 AI Agent 的工作原理
- **开发** - 构建专业化 AI 应用
- **自动化** - 实现复杂的工作流自动化
- **集成** - 将 AI Agent 集成到现有系统

### 技术特色

- **Python 3.10+** 充分利用现代异步特性
- **Pydantic v2** 强类型验证
- **React + Ink** 现代化终端 UI
- **MCP 协议** 开放的工具生态

---

**文档版本**: 1.0
**更新日期**: 2026-05-06
**维护者**: OpenHarness Team
