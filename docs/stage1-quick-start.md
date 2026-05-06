# 阶段 1: 快速上手（2-3 天）

> 深入理解 OpenHarness 的核心概念：Agent Loop、工具系统、技能系统

---

## 📋 目录

- [学习目标](#学习目标)
- [前置知识](#前置知识)
- [核心概念 1: Agent Loop](#核心概念-1-agent-loop)
- [核心概念 2: 工具系统](#核心概念-2-工具系统)
- [核心概念 3: 技能系统](#核心概念-3-技能系统)
- [工具 vs 技能对比](#工具-vs-技能对比)
- [实践项目](#实践项目)
- [验收标准](#验收标准)

---

## 学习目标

完成本阶段后，你将能够：

- ✅ 解释 Agent Loop 的核心流程和实现机制
- ✅ 创建并注册自定义工具
- ✅ 创建自定义技能文件
- ✅ 区分工具有和技能的作用场景

---

## 前置知识

### 必备概念

1. **异步编程**（Python asyncio）
   - `async def` / `await` 语法
   - `AsyncGenerator` 异步生成器
   - `asyncio.gather()` 并发执行

2. **Pydantic 模型**
   - `BaseModel` 数据模型
   - `Field()` 字段定义
   - 模型验证和序列化

3. **LLM Tool Use**
   - 了解 Function Calling / Tool Use 概念
   - 理解 LLM 如何调用工具并处理结果

### 开发环境

确保已完成阶段 0 的环境搭建：

```bash
# 克隆仓库
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness

# 安装依赖
uv sync --extra dev

# 验证安装
uv run pytest -q  # 应该看到测试通过
uv run oh --help   # 应该看到 CLI 帮助信息
```

---

## 核心概念 1: Agent Loop

### 什么是 Agent Loop？

Agent Loop 是 OpenHarness 的"心脏"，实现了完整的**查询 → 流式响应 → 工具调用 → 循环**机制。

### 核心流程图

```
用户输入 (Prompt)
    ↓
[1] 添加到消息历史
    ↓
[2] 调用 LLM API（流式）
    ↓
[3] 累积文本增量
    ↓
[4] 检查 stop_reason
    ├─ "end_turn" → 结束，返回结果
    └─ "tool_use" → 执行工具
         ↓
    [5] PreToolUse 钩子
         ↓
    [6] 权限检查
         ↓
    [7] 执行工具
         ↓
    [8] PostToolUse 钩子
         ↓
    [9] 将 tool_result 加入消息
         ↓
    [10] 循环回步骤 [2]（LLM 看到工具结果）
```

### 源码解读

#### 1. QueryEngine - 高级引擎

**文件**: `src/openharness/engine/query_engine.py`

`QueryEngine` 是顶层引擎，管理完整对话生命周期：

```python
class QueryEngine:
    """Owns conversation history and the tool-aware model loop."""

    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,  # API 客户端
        tool_registry: ToolRegistry,             # 工具注册表
        permission_checker: PermissionChecker,   # 权限检查器
        cwd: str | Path,                         # 当前工作目录
        model: str,                              # 模型名称
        system_prompt: str,                      # 系统提示词
        max_tokens: int = 4096,                 # 最大输出 token
        max_turns: int | None = 8,              # 最大循环次数
        hook_executor: HookExecutor | None = None,  # 钩子执行器
        ...
    ):
        self._messages: list[ConversationMessage] = []  # 对话历史
        self._cost_tracker = CostTracker()              # 成本追踪器
```

**关键方法**:

```python
async def submit_message(self, prompt: str) -> AsyncIterator[StreamEvent]:
    """提交用户消息并执行查询循环"""
    
    # 1. 创建用户消息
    user_message = ConversationMessage.from_user_text(prompt)
    
    # 2. 添加到历史
    self._messages.append(user_message)
    
    # 3. 执行 PreToolUse 钩子
    if self._hook_executor:
        await self._hook_executor.execute(
            HookEvent.USER_PROMPT_SUBMIT,
            {"prompt": user_message.text}
        )
    
    # 4. 构建查询上下文
    context = QueryContext(
        api_client=self._api_client,
        tool_registry=self._tool_registry,
        permission_checker=self._permission_checker,
        ...
    )
    
    # 5. 执行核心查询循环
    async for event, usage in run_query(context, self._messages):
        # 6. 追踪成本
        if usage:
            self._cost_tracker.add(usage)
        
        # 7. 流式返回事件
        yield event
```

**设计亮点**:

- **关注点分离**: `QueryEngine` 管理状态，`run_query()` 执行逻辑
- **流式设计**: 使用 `AsyncIterator` 流式返回事件
- **成本追踪**: 自动统计 token 使用量

#### 2. run_query() - 核心循环

**文件**: `src/openharness/engine/query.py`

`run_query()` 是 Agent Loop 的核心实现：

```python
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
    """运行对话循环直到模型停止请求工具"""
    
    turn_count = 0
    
    # 主循环：受 max_turns 限制
    while context.max_turns is None or turn_count < context.max_turns:
        turn_count += 1
        
        # ========== 步骤 1: 调用 LLM API ==========
        final_message: ConversationMessage | None = None
        usage = UsageSnapshot()
        
        try:
            # 流式调用 API
            async for event in context.api_client.stream_message(
                ApiMessageRequest(
                    model=context.model,
                    messages=messages,
                    system_prompt=context.system_prompt,
                    max_tokens=effective_max_tokens,
                    tools=context.tool_registry.to_api_schema(),  # 工具列表
                )
            ):
                # 返回文本增量
                if isinstance(event, ApiTextDeltaEvent):
                    yield AssistantTextDelta(text=event.text), None
                
                # 返回完成消息
                if isinstance(event, ApiMessageCompleteEvent):
                    final_message = event.message
                    usage = event.usage
        
        except Exception as exc:
            # 错误处理：自动压缩、重试等
            yield ErrorEvent(message=f"API error: {exc}"), None
            return
        
        # ========== 步骤 2: 检查是否结束 ==========
        if final_message is None:
            raise RuntimeError("Model stream finished without a final message")
        
        # 添加到历史
        messages.append(final_message)
        yield AssistantTurnComplete(message=final_message, usage=usage), usage
        
        # 如果没有工具调用，结束循环
        if not final_message.tool_uses:
            return
        
        # ========== 步骤 3: 执行工具调用 ==========
        tool_calls = final_message.tool_uses
        
        if len(tool_calls) == 1:
            # 单工具：顺序执行（立即返回事件）
            tc = tool_calls[0]
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
            yield ToolExecutionCompleted(
                tool_name=tc.name,
                output=result.content,
                is_error=result.is_error,
            ), None
            tool_results = [result]
        
        else:
            # 多工具：并发执行（先发送所有 start 事件）
            for tc in tool_calls:
                yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            
            # 并发执行所有工具
            raw_results = await asyncio.gather(
                *[_execute_tool_call(context, tc.name, tc.id, tc.input) for tc in tool_calls],
                return_exceptions=True
            )
            
            # 收集结果
            tool_results = []
            for tc, result in zip(tool_calls, raw_results):
                if isinstance(result, BaseException):
                    # 工具失败不影响其他工具
                    result = ToolResultBlock(
                        tool_use_id=tc.id,
                        content=f"Tool {tc.name} failed: {result}",
                        is_error=True,
                    )
                tool_results.append(result)
            
            # 发送完成事件
            for tc, result in zip(tool_calls, tool_results):
                yield ToolExecutionCompleted(
                    tool_name=tc.name,
                    output=result.content,
                    is_error=result.is_error,
                ), None
        
        # ========== 步骤 4: 添加工具结果到历史 ==========
        messages.append(ConversationMessage(role="user", content=tool_results))
        
        # 循环继续：LLM 将在下一轮看到工具结果
    
    # 达到最大轮数限制
    if context.max_turns is not None:
        raise MaxTurnsExceeded(context.max_turns)
```

**关键设计**:

1. **流式处理**：使用 `AsyncIterator` 流式返回事件
2. **并发执行**：多个工具并发执行（`asyncio.gather`）
3. **错误隔离**：单个工具失败不影响其他工具
4. **状态管理**：通过 `QueryContext` 共享状态

#### 3. _execute_tool_call() - 工具执行

```python
async def _execute_tool_call(
    context: QueryContext,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, object],
) -> ToolResultBlock:
    """执行单个工具调用"""
    
    # ========== 步骤 1: PreToolUse 钩子 ==========
    if context.hook_executor:
        pre_hooks = await context.hook_executor.execute(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": tool_name, "tool_input": tool_input}
        )
        if pre_hooks.blocked:
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=pre_hooks.reason,
                is_error=True,
            )
    
    # ========== 步骤 2: 查找工具 ==========
    tool = context.tool_registry.get(tool_name)
    if tool is None:
        return ToolResultBlock(
            tool_use_id=tool_use_id,
            content=f"Unknown tool: {tool_name}",
            is_error=True,
        )
    
    # ========== 步骤 3: 验证输入 ==========
    try:
        parsed_input = tool.input_model.model_validate(tool_input)
    except Exception as exc:
        return ToolResultBlock(
            tool_use_id=tool_use_id,
            content=f"Invalid input: {exc}",
            is_error=True,
        )
    
    # ========== 步骤 4: 权限检查 ==========
    decision = context.permission_checker.evaluate(
        tool_name,
        is_read_only=tool.is_read_only(parsed_input),
        file_path=_resolve_permission_file_path(context.cwd, tool_input, parsed_input),
        command=_extract_permission_command(tool_input, parsed_input),
    )
    
    if not decision.allowed:
        # 需要用户确认
        if decision.requires_confirmation and context.permission_prompt:
            confirmed = await context.permission_prompt(tool_name, decision.reason)
            if not confirmed:
                return ToolResultBlock(
                    tool_use_id=tool_use_id,
                    content="Permission denied by user",
                    is_error=True,
                )
        else:
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=decision.reason,
                is_error=True,
            )
    
    # ========== 步骤 5: 执行工具 ==========
    result = await tool.execute(
        parsed_input,
        ToolExecutionContext(
            cwd=context.cwd,
            metadata=context.tool_metadata,
            hook_executor=context.hook_executor,
        ),
    )
    
    # ========== 步骤 6: 处理输出 ==========
    # 大输出自动离线存储
    inline_output, artifact_path = _offload_tool_output_if_needed(
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        output=result.output,
    )
    
    tool_result = ToolResultBlock(
        tool_use_id=tool_use_id,
        content=inline_output,
        is_error=result.is_error,
    )
    
    # ========== 步骤 7: PostToolUse 钩子 ==========
    if context.hook_executor:
        await context.hook_executor.execute(
            HookEvent.POST_TOOL_USE,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_result.content,
                "tool_is_error": tool_result.is_error,
            },
        )
    
    return tool_result
```

**执行流程**:

```
1. PreToolUse 钩子
   ↓
2. 查找工具
   ↓
3. 验证输入（Pydantic）
   ↓
4. 权限检查
   ├─ 允许 → 继续
   ├─ 需确认 → 询问用户
   └─ 拒绝 → 返回错误
   ↓
5. 执行工具
   ↓
6. 处理输出（大输出离线存储）
   ↓
7. PostToolUse 钩子
   ↓
8. 返回结果
```

### 消息模型

**文件**: `src/openharness/engine/messages.py`

#### ContentBlock 类型

```python
ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock

class TextBlock(BaseModel):
    """纯文本内容"""
    type: Literal["text"] = "text"
    text: str

class ImageBlock(BaseModel):
    """图片内容（base64）"""
    type: Literal["image"] = "image"
    media_type: str
    data: str  # base64

class ToolUseBlock(BaseModel):
    """工具调用请求"""
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    """工具执行结果"""
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False
```

#### ConversationMessage

```python
class ConversationMessage(BaseModel):
    """单条对话消息"""
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
    
    @classmethod
    def from_user_text(cls, text: str) -> "ConversationMessage":
        """从文本创建用户消息"""
        return cls(role="user", content=[TextBlock(text=text)])
    
    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        """返回所有工具调用"""
        return [b for b in self.content if isinstance(b, ToolUseBlock)]
```

### 流式事件

**文件**: `src/openharness/engine/stream_events.py`

```python
StreamEvent = (
    AssistantTextDelta          # 文本增量
    | AssistantTurnComplete      # 对话轮完成
    | ToolExecutionStarted       # 工具开始执行
    | ToolExecutionCompleted     # 工具执行完成
    | ErrorEvent                 # 错误
    | StatusEvent                # 状态消息
    | CompactProgressEvent       # 压缩进度
)
```

**事件使用示例**:

```python
async for event, usage in run_query(context, messages):
    if isinstance(event, AssistantTextDelta):
        # 流式输出文本
        print(event.text, end="", flush=True)
    
    elif isinstance(event, ToolExecutionStarted):
        # 显示工具开始
        print(f"\n🔧 {event.tool_name}(...)")
    
    elif isinstance(event, ToolExecutionCompleted):
        # 显示工具结果
        if event.is_error:
            print(f"❌ {event.tool_name} failed: {event.output[:100]}")
        else:
            print(f"✅ {event.tool_name} completed")
    
    elif isinstance(event, AssistantTurnComplete):
        # 统计成本
        print(f"\n📊 Tokens: {event.usage.input_tokens} in / {event.usage.output_tokens} out")
```

---

## 核心概念 2: 工具系统

### 什么是工具？

工具是 Python 实现的功能模块，为 LLM 提供"手脚"——执行具体操作的能力。

### 工具基类

**文件**: `src/openharness/tools/base.py`

```python
class BaseTool(ABC, Generic[T]):
    """所有工具的抽象基类"""
    
    name: str                    # 工具名称（唯一标识）
    description: str             # 工具描述（给 LLM 看）
    input_model: type[T]        # Pydantic 输入模型
    
    @abstractmethod
    async def execute(
        self,
        arguments: T,
        context: ToolExecutionContext
    ) -> ToolResult:
        """执行工具逻辑"""
    
    def is_read_only(self, arguments: T) -> bool:
        """判断是否为只读操作（用于权限检查）"""
        return False
    
    def to_api_schema(self) -> dict[str, Any]:
        """生成 LLM API 所需的 JSON Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
```

**设计要点**:

1. **泛型设计**：`Generic[T]` 允许类型检查
2. **Pydantic 集成**：自动验证输入、生成 Schema
3. **只读标记**：`is_read_only()` 用于权限判断

### 工具注册表

```python
class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> BaseTool | None:
        """按名称获取工具"""
        return self._tools.get(name)
    
    def list_tools(self) -> list[BaseTool]:
        """列出所有工具"""
        return list(self._tools.values())
    
    def to_api_schema(self) -> list[dict]:
        """生成 API Schema 列表"""
        return [tool.to_api_schema() for tool in self._tools.values()]
```

### 工具执行上下文

```python
@dataclass
class ToolExecutionContext:
    """工具执行时的共享上下文"""
    
    cwd: Path                                  # 当前工作目录
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据
    hook_executor: HookExecutor | None = None # 钩子执行器
```

### 工具结果

```python
@dataclass(frozen=True)
class ToolResult:
    """工具执行结果"""
    
    output: str                    # 输出文本
    is_error: bool = False         # 是否错误
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据
```

### 示例：BashTool

**文件**: `src/openharness/tools/bash_tool.py`

```python
from pydantic import BaseModel, Field

# 1. 定义输入模型
class BashToolInput(BaseModel):
    """Bash 工具参数"""
    
    command: str = Field(description="Shell command to execute")
    cwd: str | None = Field(default=None, description="Working directory override")
    timeout_seconds: int = Field(default=600, ge=1, le=600)

# 2. 实现工具类
class BashTool(BaseTool[BashToolInput]):
    """执行 Shell 命令"""
    
    name = "bash"
    description = "Run a shell command in the local repository."
    input_model = BashToolInput
    
    # 3. 实现执行逻辑
    async def execute(
        self,
        arguments: BashToolInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        # 解析工作目录
        cwd = Path(arguments.cwd).expanduser() if arguments.cwd else context.cwd
        
        # 检查交互式命令
        preflight_error = _preflight_interactive_command(arguments.command)
        if preflight_error:
            return ToolResult(output=preflight_error, is_error=True)
        
        # 创建子进程
        process = await create_shell_subprocess(
            arguments.command,
            cwd=cwd,
            prefer_pty=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        
        # 等待执行（带超时）
        try:
            await asyncio.wait_for(process.wait(), timeout=arguments.timeout_seconds)
        except asyncio.TimeoutError:
            # 超时处理
            output = await _drain_available_output(process.stdout)
            await _terminate_process(process, force=True)
            return ToolResult(
                output=f"Command timed out after {arguments.timeout_seconds}s\n{output}",
                is_error=True,
            )
        
        # 读取输出
        output = await _read_remaining_output(process)
        text = output.decode("utf-8", errors="replace").strip()
        
        # 返回结果
        return ToolResult(
            output=text or "(no output)",
            is_error=process.returncode != 0,
            metadata={"returncode": process.returncode},
        )
    
    # 4. 只读判断
    def is_read_only(self, arguments: BashToolInput) -> bool:
        """判断命令是否只读"""
        # 简单启发式：ls、cat、echo 等命令视为只读
        return arguments.command.strip().startswith(("ls ", "cat ", "echo ", "pwd"))
```

**关键点**:

1. **输入验证**：使用 Pydantic 自动验证类型、范围
2. **超时处理**：防止命令无限挂起
3. **错误处理**：返回结构化错误信息
4. **元数据**：携带 `returncode` 等信息

### 示例：FileReadTool

**文件**: `src/openharness/tools/file_read_tool.py`

```python
class FileReadToolInput(BaseModel):
    """文件读取参数"""
    
    path: str = Field(description="Path of the file to read")
    offset: int = Field(default=0, ge=0, description="Zero-based starting line")
    limit: int = Field(default=200, ge=1, le=2000, description="Number of lines")

class FileReadTool(BaseTool[FileReadToolInput]):
    """读取文本文件"""
    
    name = "read_file"
    description = "Read a text file from the local repository."
    input_model = FileReadToolInput
    
    # 标记为只读操作
    def is_read_only(self, arguments: FileReadToolInput) -> bool:
        return True
    
    async def execute(
        self,
        arguments: FileReadToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        # 1. 解析路径
        path = _resolve_path(context.cwd, arguments.path)
        
        # 2. 沙箱检查
        if is_docker_sandbox_active():
            allowed, reason = validate_sandbox_path(path, context.cwd)
            if not allowed:
                return ToolResult(output=f"Sandbox: {reason}", is_error=True)
        
        # 3. 文件检查
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        if path.is_dir():
            return ToolResult(output=f"Cannot read directory: {path}", is_error=True)
        
        # 4. 读取内容
        raw = path.read_bytes()
        
        # 5. 二进制检查
        if b"\x00" in raw:
            return ToolResult(output=f"Binary file cannot be read as text: {path}", is_error=True)
        
        # 6. 解码文本
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        
        # 7. 分页
        selected = lines[arguments.offset : arguments.offset + arguments.limit]
        numbered = [
            f"{arguments.offset + i + 1:>6}\t{line}"
            for i, line in enumerate(selected)
        ]
        
        # 8. 返回结果
        return ToolResult(output="\n".join(numbered))
```

### 工具注册

**文件**: `src/openharness/tools/__init__.py`

```python
def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """创建默认工具注册表"""
    registry = ToolRegistry()
    
    # 注册所有内置工具
    for tool in (
        BashTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        WebSearchTool(),
        SkillTool(),
        AgentTool(),
        # ... 更多工具
    ):
        registry.register(tool)
    
    # 注册 MCP 工具
    if mcp_manager:
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    
    return registry
```

---

## 核心概念 3: 技能系统

### 什么是技能？

技能是 **Markdown 格式的知识指导**，为 LLM 提供"大脑"——领域知识和最佳实践。

### 技能 vs 工具

| 维度 | 工具 | 技能 |
|------|------|------|
| **本质** | Python 代码 | Markdown 文本 |
| **作用** | 执行操作 | 提供知识 |
| **类比** | 手脚 | 大脑 |
| **创建** | 编程 | 写文档 |
| **格式** | Pydantic + async def | Markdown + YAML frontmatter |

### 技能定义

**文件**: `src/openharness/skills/types.py`

```python
@dataclass(frozen=True)
class SkillDefinition:
    """加载的技能"""
    
    name: str              # 唯一标识
    description: str       # 简短描述
    content: str           # Markdown 内容
    source: str            # 来源："builtin" | "user" | "plugin"
    path: str | None       # 文件路径
```

### 技能文件格式

技能文件使用 Markdown + YAML frontmatter：

```markdown
---
name: commit
description: Create clean, well-structured git commits
---

# commit

Create clean, well-structured git commits.

## When to use

Use when the user asks to commit changes, create a PR, or prepare code for review.

## Workflow

1. Run `git status` and `git diff` to understand all changes
2. Analyze changes: categorize as feature, fix, refactor, docs, test, etc.
3. Draft a concise commit message:
   - First line: imperative mood, under 72 chars, describes the "why"
   - Body (if needed): explain context, trade-offs, or breaking changes
4. Stage only relevant files — never stage .env, credentials, or large binaries
5. Create the commit

## Rules

- Prefer specific `git add <file>` over `git add -A`
- Never use `--no-verify` unless explicitly asked
- Never amend published commits unless explicitly asked
- If a pre-commit hook fails, fix the issue and create a NEW commit (don't --amend)
- Include `Co-Authored-By` if pair programming
```

**结构说明**:

1. **YAML Frontmatter**（可选）:
   - `name`: 技能名称
   - `description`: 简短描述

2. **Markdown 内容**:
   - 标题：技能名称
   - When to use：使用场景
   - Workflow：工作流程
   - Rules：具体规则

### 技能加载

**文件**: `src/openharness/skills/loader.py`

#### 加载流程

```python
def load_skill_registry(
    cwd: str | Path | None = None,
    *,
    extra_skill_dirs: Iterable[str | Path] | None = None,
) -> SkillRegistry:
    """加载所有技能"""
    registry = SkillRegistry()
    
    # 1. 内置技能
    for skill in get_bundled_skills():
        registry.register(skill)
    
    # 2. 用户技能
    for skill in load_user_skills():
        registry.register(skill)
    
    # 3. 额外目录技能
    for skill in load_skills_from_dirs(extra_skill_dirs):
        registry.register(skill)
    
    # 4. 插件贡献技能
    if cwd:
        for plugin in load_plugins(cwd):
            for skill in plugin.skills:
                registry.register(skill)
    
    return registry
```

#### 加载顺序

```
1. 内置技能（bundled/）
   ↓
2. 用户技能（~/.openharness/skills/）
   ↓
3. 插件技能（~/.openharness/plugins/<plugin>/skills/）
   ↓
4. 项目技能（<project>/.openharness/skills/）
```

**优先级**: 后加载的覆盖先加载的。

### 技能工具

**文件**: `src/openharness/tools/skill_tool.py`

```python
class SkillToolInput(BaseModel):
    """技能工具参数"""
    
    name: str = Field(description="Skill name")

class SkillTool(BaseTool[SkillToolInput]):
    """读取技能内容"""
    
    name = "skill"
    description = "Read a bundled, user, or plugin skill by name."
    input_model = SkillToolInput
    
    def is_read_only(self, arguments: SkillToolInput) -> bool:
        return True
    
    async def execute(
        self,
        arguments: SkillToolInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        # 1. 加载技能注册表
        registry = load_skill_registry(context.cwd)
        
        # 2. 查找技能（尝试多种名称形式）
        skill = (
            registry.get(arguments.name) or
            registry.get(arguments.name.lower()) or
            registry.get(arguments.name.title())
        )
        
        # 3. 返回结果
        if skill is None:
            return ToolResult(output=f"Skill not found: {arguments.name}", is_error=True)
        
        return ToolResult(output=skill.content)
```

**使用方式**:

```
用户: "Use the commit skill to create a git commit"

LLM 调用:
{
  "name": "skill",
  "input": {"name": "commit"}
}

工具返回:
# commit 的完整 Markdown 内容
```

### 内置技能

**目录**: `src/openharness/skills/bundled/content/`

| 技能 | 描述 |
|------|------|
| `commit.md` | Git 提交流程 |
| `review.md` | 代码审查 |
| `debug.md` | 调试流程 |
| `plan.md` | 规划实现 |
| `simplify.md` | 代码简化 |
| `test.md` | 测试编写 |
| `diagnose.md` | 问题诊断 |

---

## 工具 vs 技能对比

### 详细对比表

| 维度 | 工具（Tool） | 技能（Skill） |
|------|--------------|---------------|
| **本质** | Python 代码实现 | Markdown 文本知识 |
| **作用** | 执行具体操作 | 提供领域知识 |
| **类比** | 手脚（行动能力） | 大脑（知识库） |
| **创建难度** | 需要编程 | 只需写文档 |
| **格式** | Pydantic + async def | Markdown + YAML |
| **注册位置** | `ToolRegistry` | `SkillRegistry` |
| **调用方式** | LLM 自动调用 | 注入系统提示词 |
| **示例** | `BashTool`、`FileReadTool` | `commit.md`、`review.md` |
| **扩展性** | 任意 Python 功能 | 静态知识指导 |

### 使用场景

#### 使用工具的场景

- 执行 Shell 命令
- 读写文件
- 网络请求
- 调用外部 API
- 启动后台任务
- 任何需要"行动"的操作

#### 使用技能的场景

- 提供最佳实践
- 指导工作流程
- 领域知识注入
- 代码审查清单
- 调试思路
- 架构决策指南

### 组合使用示例

**用户请求**: "Create a git commit for my changes"

**执行流程**:

```
1. LLM 调用 `skill` 工具加载 commit 技能
   ↓
2. 工具返回 commit.md 内容
   ↓
3. LLM 根据 commit 技能指导：
   - 调用 `BashTool` 执行 git status
   - 调用 `BashTool` 执行 git diff
   - 分析改动
   - 调用 `BashTool` 执行 git add
   - 调用 `BashTool` 执行 git commit
   ↓
4. 完成提交
```

**关键点**: 工具提供"行动力"，技能提供"智慧"。

---

## 实践项目

### 项目 1.1: 创建自定义工具

**目标**: 创建一个 `HelloTool`，返回问候语

#### 步骤 1: 创建工具文件

```python
# src/openharness/tools/hello_tool.py

from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

# 1. 定义输入模型
class HelloInput(BaseModel):
    """Hello 工具参数"""
    
    name: str = Field(description="Name to greet")
    greeting: str = Field(default="Hello", description="Greeting word")

# 2. 实现工具类
class HelloTool(BaseTool[HelloInput]):
    """问候工具"""
    
    name = "hello"
    description = "Say hello to someone"
    input_model = HelloInput
    
    # 3. 实现执行逻辑
    async def execute(
        self,
        arguments: HelloInput,
        context: ToolExecutionContext
    ) -> ToolResult:
        # 生成问候语
        message = f"{arguments.greeting}, {arguments.name}!"
        
        # 返回结果
        return ToolResult(output=message)
    
    # 4. 标记为只读
    def is_read_only(self, arguments: HelloInput) -> bool:
        return True  # 问候不会修改任何东西
```

#### 步骤 2: 注册工具

```python
# src/openharness/tools/__init__.py

from openharness.tools.hello_tool import HelloTool

def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    registry = ToolRegistry()
    
    for tool in (
        # ... 其他工具
        HelloTool(),  # 添加到列表
    ):
        registry.register(tool)
    
    return registry
```

#### 步骤 3: 测试工具

```bash
# 启动交互式会话
uv run oh

# 在会话中输入
"Use the hello tool to greet Alice"
```

**预期输出**:

```
🔧 hello(name="Alice")
✅ Hello, Alice!
```

#### 进阶练习

1. **添加参数验证**:

```python
from pydantic import field_validator

class HelloInput(BaseModel):
    name: str = Field(description="Name to greet", min_length=1, max_length=50)
    
    @field_validator("name")
    @classmethod
    def name_must_be_alphabetic(cls, v):
        if not v.replace(" ", "").isalpha():
            raise ValueError("Name must contain only letters and spaces")
        return v.title()
```

2. **添加上下文信息**:

```python
async def execute(self, arguments, context):
    # 使用上下文
    cwd = context.cwd
    
    message = f"{arguments.greeting}, {arguments.name}!"
    message += f"\n\nWorking directory: {cwd}"
    
    return ToolResult(output=message)
```

3. **编写单元测试**:

```python
# tests/test_tools/test_hello_tool.py

import pytest
from openharness.tools.hello_tool import HelloTool, HelloInput
from openharness.tools.base import ToolExecutionContext
from pathlib import Path

@pytest.mark.asyncio
async def test_hello_tool():
    """测试基本功能"""
    tool = HelloTool()
    args = HelloInput(name="World")
    context = ToolExecutionContext(cwd=Path("/tmp"))
    
    result = await tool.execute(args, context)
    
    assert result.output == "Hello, World!"
    assert not result.is_error

@pytest.mark.asyncio
async def test_hello_tool_custom_greeting():
    """测试自定义问候语"""
    tool = HelloTool()
    args = HelloInput(name="Alice", greeting="Hi")
    context = ToolExecutionContext(cwd=Path("/tmp"))
    
    result = await tool.execute(args, context)
    
    assert result.output == "Hi, Alice!"

def test_hello_tool_schema():
    """测试 JSON Schema 生成"""
    tool = HelloTool()
    schema = tool.to_api_schema()
    
    assert schema["name"] == "hello"
    assert "name" in schema["input_schema"]["properties"]
    assert "greeting" in schema["input_schema"]["properties"]
```

运行测试:

```bash
uv run pytest tests/test_tools/test_hello_tool.py -v
```

---

### 项目 1.2: 创建自定义技能

**目标**: 创建一个代码审查技能

#### 步骤 1: 创建技能文件

```markdown
<!-- ~/.openharness/skills/code-review.md -->

---
name: code-review
description: Systematic code review workflow with best practices
---

# Code Review

Systematic code review workflow focusing on bugs, security, and quality.

## When to use

Use when the user asks to:
- Review code or pull requests
- Check for bugs or security issues
- Improve code quality

## Workflow

1. **Understand Context**
   - Read CLAUDE.md for project guidelines
   - Identify the scope of changes
   - Check related files and dependencies

2. **Check Logic**
   - Off-by-one errors
   - Null/undefined handling
   - Race conditions
   - Error propagation
   - Edge cases

3. **Check Security**
   - Injection vulnerabilities (SQL, command, XSS)
   - Hardcoded secrets or credentials
   - Path traversal
   - Unsafe deserialization
   - OWASP Top 10

4. **Check Performance**
   - N+1 queries
   - Unnecessary allocations
   - Missing indexes
   - Inefficient algorithms

5. **Check Tests**
   - Are new paths covered?
   - Edge cases tested?
   - Mocks used correctly?
   - Integration tests needed?

6. **Check Style**
   - Naming consistency
   - Dead code
   - Unnecessary complexity
   - Missing documentation

## Rules

- Be specific: "line 42 may throw if `user` is null"
- Suggest fixes, don't just point out problems
- Prioritize: critical > major > minor > nit
- Acknowledge good patterns
- Provide file:line references

## Checklist

- [ ] Logic correctness
- [ ] Error handling
- [ ] Security issues
- [ ] Performance concerns
- [ ] Code style and clarity
- [ ] Test coverage
- [ ] Documentation

## Example Feedback

```
CRITICAL: src/auth.py:42
- Issue: Password comparison uses `==` instead of constant-time comparison
- Fix: Use `secrets.compare_digest(user_input, stored_hash)`
- Risk: Timing attack vulnerability

GOOD: src/utils.py:15-20
- Clean error handling with proper logging
```
```

#### 步骤 2: 测试技能

```bash
# 启动交互式会话
uv run oh

# 在会话中输入
"Use the code-review skill to review src/openharness/tools/base.py"
```

**预期行为**:

```
1. LLM 调用 `skill` 工具加载 code-review 技能
   ↓
2. LLM 根据技能指导进行审查：
   - 调用 `read_file` 读取目标文件
   - 按照清单检查逻辑、安全、性能等
   - 提供具体的改进建议
```

#### 进阶练习

1. **创建项目特定技能**:

```markdown
<!-- <project>/.openharness/skills/project-style.md -->

---
name: project-style
description: Project-specific coding style guidelines
---

# Project Style Guide

## When to use

Use when writing or reviewing code in this project.

## Rules

### Python
- Use type hints for all function signatures
- Maximum line length: 100 characters
- Prefer f-strings over .format()
- Use dataclasses for data containers

### Testing
- Test file location: `tests/test_<module>.py`
- Use pytest fixtures for setup
- Minimum coverage: 80%

### Documentation
- Docstrings: Google style
- README: Keep under 100 lines
- Architecture: Document in ARCHITECTURE.md
```

2. **创建团队技能**:

```markdown
<!-- ~/.openharness/skills/team-conventions.md -->

---
name: team-conventions
description: Team-specific development conventions
---

# Team Conventions

## Git
- Branch naming: `<type>/<ticket>-<description>`
  - Types: feature, fix, refactor, docs, test
  - Example: `feature/AUTH-123-add-login`
- Commit message: Conventional Commits
  - Format: `type(scope): description`
  - Example: `feat(auth): add OAuth2 login`

## Code Review
- Require at least 1 approval
- CI must pass
- No direct commits to main
- Delete branch after merge

## Deployment
- Staging: automatic from develop
- Production: manual release PR
```

3. **创建调试技能**:

```markdown
<!-- ~/.openharness/skills/debug-workflow.md -->

---
name: debug-workflow
description: Systematic debugging workflow
---

# Debug Workflow

## When to use

Use when encountering bugs, errors, or unexpected behavior.

## Workflow

1. **Reproduce**
   - Document exact steps
   - Check if reproducible
   - Isolate minimal case

2. **Understand**
   - Read error message carefully
   - Check stack trace
   - Identify affected code

3. **Hypothesize**
   - Generate multiple hypotheses
   - Rank by likelihood
   - Design experiments to test

4. **Verify**
   - Make one change at a time
   - Test after each change
   - Use logging/print debugging

5. **Fix**
   - Write test first (TDD)
   - Implement fix
   - Run all tests
   - Check for regressions

6. **Document**
   - Add comment if non-obvious
   - Update changelog
   - Close related issues
```

---

## 验收标准

完成本阶段后，你应该能够：

### 理论理解

- [ ] 解释 Agent Loop 的完整流程（查询→流式→工具→循环）
- [ ] 描述消息模型的四种 Block 类型及其作用
- [ ] 说明流式事件（StreamEvent）的设计目的
- [ ] 区分工具和技能的本质差异

### 实践能力

- [ ] 独立创建并注册自定义工具
- [ ] 编写 Pydantic 输入模型并添加验证
- [ ] 实现工具的 `execute()` 和 `is_read_only()` 方法
- [ ] 创建自定义技能 Markdown 文件
- [ ] 使用 YAML frontmatter 定义技能元数据

### 测试能力

- [ ] 为自定义工具编写单元测试
- [ ] 使用 `pytest` 运行测试
- [ ] 验证工具的 JSON Schema 生成正确

### 调试能力

- [ ] 使用 `--debug` 标志查看详细日志
- [ ] 在工具代码中添加日志输出
- [ ] 理解工具执行的事件流

---

## 常见问题

### Q1: 工具和技能什么时候用？

**A**:
- 需要**执行操作**时用工具（如读文件、运行命令）
- 需要**提供知识**时用技能（如审查清单、最佳实践）
- 通常组合使用：技能指导 + 工具执行

### Q2: 如何调试 Agent Loop？

**A**: 三种方法：

1. **使用调试标志**:
   ```bash
   uv run oh --debug
   ```

2. **添加日志**:
   ```python
   import logging
   log = logging.getLogger(__name__)
   log.debug("Executing tool: %s", tool_name)
   ```

3. **单元测试**:
   ```python
   # 测试特定工具
   result = await tool.execute(args, context)
   assert not result.is_error
   ```

### Q3: 工具的输入模型有什么限制？

**A**:
- 必须继承 `pydantic.BaseModel`
- 字段必须有 `description`（给 LLM 看）
- 避免复杂的嵌套结构
- 使用 `Field()` 添加约束

### Q4: 技能文件可以放在哪里？

**A**: 四个位置（按优先级）：

1. 项目目录：`<project>/.openharness/skills/`
2. 用户目录：`~/.openharness/skills/`
3. 插件目录：`~/.openharness/plugins/<plugin>/skills/`
4. 内置目录：`src/openharness/skills/bundled/content/`

### Q5: 如何查看可用的工具和技能？

**A**:

```bash
# 查看工具
uv run oh --dry-run -p "List available tools"

# 查看技能
ls ~/.openharness/skills/
ls src/openharness/skills/bundled/content/
```

---

## 下一步

完成本阶段后，继续学习：

**阶段 2: 核心架构理解**
- API 客户端层设计
- 权限系统机制
- 钩子生命周期
- 配置系统管理

---

## 参考资源

### 核心文件

- `src/openharness/engine/query_engine.py` - 高级引擎
- `src/openharness/engine/query.py` - 核心循环
- `src/openharness/tools/base.py` - 工具基类
- `src/openharness/skills/loader.py` - 技能加载

### 相关文档

- [Pydantic 文档](https://docs.pydantic.dev/)
- [Python asyncio 文档](https://docs.python.org/3/library/asyncio.html)
- [Anthropic Tool Use 文档](https://docs.anthropic.com/claude/docs/tool-use)

### 扩展阅读

- [ARCHITECTURE.md](../ARCHITECTURE.md) - 完整架构文档
- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南
- [docs/SHOWCASE.md](../docs/SHOWCASE.md) - 使用案例

---

**文档版本**: 1.0  
**更新日期**: 2026-05-06  
**维护者**: OpenHarness Team

祝你学习愉快！如有问题，欢迎在 GitHub Issues 中提问。
