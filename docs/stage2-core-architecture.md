# 阶段 2: 核心架构理解（3-4 天）

> 深入理解 OpenHarness 的四大核心架构模块：API 客户端层、权限系统、钩子系统、配置系统

---

## 📋 目录

- [学习目标](#学习目标)
- [前置知识](#前置知识)
- [模块 2.1: API 客户端层](#模块-21-api-客户端层)
- [模块 2.2: 权限系统](#模块-22-权限系统)
- [模块 2.3: 钩子系统](#模块-23-钩子系统)
- [模块 2.4: 配置系统](#模块-24-配置系统)
- [实践项目](#实践项目)
- [验收标准](#验收标准)

---

## 学习目标

完成本阶段后，你将能够：

- ✅ 理解 API 客户端层的统一协议设计
- ✅ 掌握 Anthropic 和 OpenAI 兼容客户端的实现差异
- ✅ 解释 Provider 自动检测机制
- ✅ 描述权限检查的 7 步流程
- ✅ 实现 4 种类型的 Hook
- ✅ 理解多层配置优先级

---

## 前置知识

### 必备概念

1. **HTTP 协议**
   - REST API 基础
   - 状态码含义（429、500、502、503、529）
   - Retry-After 响应头

2. **API 客户端设计**
   - 流式响应（Server-Sent Events）
   - 重试机制（指数退避）
   - 错误映射

3. **权限模型**
   - 白名单/黑名单
   - 路径匹配（glob/fnmatch）
   - 沙箱隔离

4. **配置管理**
   - XDG 基础目录规范
   - 多层配置合并
   - 环境变量覆盖

### 开发环境

确保已完成阶段 1 的学习：

```bash
# 验证环境
uv run oh --version
uv run pytest -q
```

---

## 模块 2.1: API 客户端层

### 架构概览

API 客户端层采用**协议驱动设计**，通过 `SupportsStreamingMessages` Protocol 定义统一接口，支持多种 LLM 提供商。

```
┌─────────────────────────────────────────────────────────┐
│                   QueryEngine                            │
│                 (依赖 Protocol 接口)                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│        SupportsStreamingMessages Protocol                │
│  - stream_message(request) -> AsyncGenerator            │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┼───────────┬─────────────┐
         ▼           ▼           ▼             ▼
┌────────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────┐
│ Anthropic │ │   OpenAI    │ │ Copilot  │ │ Codex    │
│ApiClient  │ │ Compatible  │ │ Client   │ │ Client   │
└───────────┘ └─────────────┘ └──────────┘ └──────────┘
```

### SupportsStreamingMessages Protocol

**文件**: `src/openharness/api/client.py`

```python
class SupportsStreamingMessages(Protocol):
    """流式消息 API 客户端协议"""
    
    def stream_message(
        self,
        request: ApiMessageRequest,
    ) -> AsyncGenerator[
        ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent,
        None,
    ]:
        """流式生成消息
        
        Args:
            request: 包含 model、messages、tools、system_prompt 等
            
        Yields:
            ApiTextDeltaEvent: 文本增量
            ApiMessageCompleteEvent: 消息完成
            ApiRetryEvent: 重试事件
        """
        ...
```

**设计要点**:

1. **协议而非抽象类**: 使用 `Protocol` 定义接口，允许鸭子类型
2. **异步生成器**: `AsyncGenerator` 实现流式输出
3. **统一事件模型**: 所有客户端返回相同事件类型

### ApiMessageRequest

```python
@dataclass
class ApiMessageRequest:
    """API 请求参数"""
    
    model: str                           # 模型名称
    messages: list[ConversationMessage]  # 对话历史
    tools: list[dict[str, Any]]          # 工具 Schema
    system_prompt: str | None = None     # 系统提示词
    max_tokens: int = 4096              # 最大输出 token
    temperature: float | None = None     # 温度参数
    stop_sequences: list[str] | None = None  # 停止序列
```

### AnthropicApiClient

**文件**: `src/openharness/api/client.py`

#### 核心实现

```python
class AnthropicApiClient:
    """Anthropic 原生 API 客户端"""
    
    MAX_RETRIES = 3      # 最大重试次数
    BASE_DELAY = 1.0     # 基础延迟（秒）
    MAX_DELAY = 30.0     # 最大延迟（秒）
    
    def __init__(self, api_key: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
    
    async def stream_message(
        self,
        request: ApiMessageRequest,
    ) -> AsyncGenerator[
        ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent,
        None,
    ]:
        """流式生成消息（带重试）"""
        
        retry_count = 0
        while retry_count <= self.MAX_RETRIES:
            try:
                # 调用 Anthropic SDK
                async with self._client.messages.stream(
                    model=request.model,
                    messages=[msg.model_dump() for msg in request.messages],
                    tools=request.tools,
                    system=request.system_prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    stop_sequences=request.stop_sequences,
                ) as stream:
                    # 流式输出
                    async for event in stream:
                        if event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "text"):
                                yield ApiTextDeltaEvent(text=delta.text)
                        
                        elif event.type == "message_stop":
                            # 消息完成
                            message = await stream.get_final_message()
                            yield ApiMessageCompleteEvent(
                                message=_convert_anthropic_message(message),
                                usage=_convert_usage(message.usage),
                            )
                            return
                
            except Exception as e:
                # 检查是否可重试
                if not self._is_retryable(e):
                    raise self._translate_api_error(e)
                
                retry_count += 1
                if retry_count > self.MAX_RETRIES:
                    raise RuntimeError(f"Max retries exceeded: {self.MAX_RETRIES}")
                
                # 计算延迟
                delay = self._get_retry_delay(e, retry_count)
                yield ApiRetryEvent(attempt=retry_count, delay_seconds=delay)
                
                await asyncio.sleep(delay)
```

#### 重试逻辑

```python
def _is_retryable(self, error: Exception) -> bool:
    """判断错误是否可重试"""
    
    # 网络错误
    if isinstance(error, (httpx.NetworkError, httpx.TimeoutException)):
        return True
    
    # API 错误
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in {429, 500, 502, 503, 529}
    
    return False

def _get_retry_delay(self, error: Exception, attempt: int) -> float:
    """计算重试延迟（指数退避 + 抖动）"""
    
    # 从响应头获取建议延迟
    if isinstance(error, anthropic.RateLimitError):
        if hasattr(error, "response") and "retry-after" in error.response.headers:
            retry_after = error.response.headers["retry-after"]
            try:
                return float(retry_after)
            except ValueError:
                pass
    
    # 指数退避
    delay = self.BASE_DELAY * (2 ** (attempt - 1))
    delay = min(delay, self.MAX_DELAY)
    
    # 添加抖动（±50%）
    jitter = delay * 0.5 * (random.random() * 2 - 1)
    delay += jitter
    
    return max(delay, self.BASE_DELAY)
```

**关键点**:

1. **状态码判断**: 429（限流）、500/502/503/529（服务器错误）可重试
2. **Retry-After**: 优先使用 API 返回的建议延迟
3. **指数退避**: 每次延迟翻倍，避免过度重试
4. **抖动**: 添加随机性，避免多个客户端同时重试

#### 错误映射

```python
def _translate_api_error(self, error: Exception) -> Exception:
    """将 API 错误转换为领域错误"""
    
    if isinstance(error, anthropic.AuthenticationError):
        return AuthenticationError(f"Invalid API key: {error}")
    
    if isinstance(error, anthropic.PermissionError):
        return PermissionError(f"Permission denied: {error}")
    
    if isinstance(error, anthropic.NotFoundError):
        return ModelNotFoundError(f"Model not found: {error}")
    
    if isinstance(error, anthropic.RateLimitError):
        return RateLimitError(f"Rate limit exceeded: {error}")
    
    return error
```

### OpenAICompatibleClient

**文件**: `src/openharness/api/openai_client.py`

OpenAI 兼容客户端实现了 Anthropic → OpenAI 格式转换。

#### 核心实现

```python
class OpenAICompatibleClient:
    """OpenAI 兼容 API 客户端"""
    
    def __init__(self, api_key: str, base_url: str | None = None):
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    
    async def stream_message(
        self,
        request: ApiMessageRequest,
    ) -> AsyncGenerator[
        ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent,
        None,
    ]:
        """流式生成消息（格式转换）"""
        
        # 1. 转换请求格式
        openai_messages = self._convert_messages_to_openai(
            messages=request.messages,
            system_prompt=request.system_prompt,
        )
        openai_tools = self._convert_tools_to_openai(request.tools)
        
        # 2. 构建参数
        params = {
            "model": request.model,
            "messages": openai_messages,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        
        if openai_tools:
            params["tools"] = openai_tools
        
        # 3. 流式调用
        retry_count = 0
        while retry_count <= self.MAX_RETRIES:
            try:
                stream = await self._client.chat.completions.create(**params)
                
                # 4. 流式输出
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    
                    # 处理文本
                    if delta.content:
                        # 剥离 think 块（某些模型会输出）
                        text = self._strip_think_blocks(delta.content)
                        if text:
                            yield ApiTextDeltaEvent(text=text)
                    
                    # 处理推理内容（Kimi k2.5 等模型）
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        # 静默处理，不输出给用户
                        pass
                    
                    # 处理工具调用
                    if delta.tool_calls:
                        for tool_call in delta.tool_calls:
                            yield ApiToolCallDeltaEvent(
                                id=tool_call.id,
                                name=tool_call.function.name,
                                arguments=tool_call.function.arguments,
                            )
                
                # 5. 消息完成
                yield ApiMessageCompleteEvent(...)
                return
                
            except Exception as e:
                # 重试逻辑（同 Anthropic）
                ...
```

#### 消息格式转换

```python
def _convert_messages_to_openai(
    self,
    messages: list[ConversationMessage],
    system_prompt: str | None,
) -> list[dict]:
    """将 Anthropic 消息格式转换为 OpenAI 格式"""
    
    openai_messages = []
    
    # 1. 系统提示词（作为第一条消息）
    if system_prompt:
        openai_messages.append({
            "role": "system",
            "content": system_prompt,
        })
    
    # 2. 转换对话消息
    for msg in messages:
        if msg.role == "user":
            # 用户消息
            content = self._convert_content_blocks(msg.content)
            openai_messages.append({
                "role": "user",
                "content": content,
            })
        
        elif msg.role == "assistant":
            # 助手消息
            openai_msg = self._convert_assistant_message(msg)
            openai_messages.append(openai_msg)
    
    return openai_messages

def _convert_assistant_message(
    self,
    msg: ConversationMessage,
) -> dict:
    """转换助手消息"""
    
    # 提取文本内容
    text_parts = [
        block.text for block in msg.content
        if isinstance(block, TextBlock)
    ]
    
    # 提取工具调用
    tool_calls = []
    for block in msg.content:
        if isinstance(block, ToolUseBlock):
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                },
            })
    
    result = {"role": "assistant"}
    
    if text_parts:
        result["content"] = "\n".join(text_parts)
    
    if tool_calls:
        result["tool_calls"] = tool_calls
    
    return result
```

#### 工具格式转换

```python
def _convert_tools_to_openai(
    self,
    tools: list[dict],
) -> list[dict]:
    """将 Anthropic 工具 Schema 转换为 OpenAI 格式"""
    
    openai_tools = []
    
    for tool in tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        }
        openai_tools.append(openai_tool)
    
    return openai_tools
```

#### Think 块剥离

```python
def _strip_think_blocks(self, text: str) -> str:
    """剥离 <think>...</think> 块"""
    
    # 某些模型（如 DeepSeek）会输出推理过程
    # 使用正则表达式移除
    import re
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
```

#### Token 限制参数

```python
def _token_limit_param_for_model(
    self,
    model: str,
) -> str:
    """根据模型选择 token 限制参数"""
    
    # GPT-5 / o 系列模型使用 max_completion_tokens
    if re.match(r'^(gpt-5|o\d)', model):
        return "max_completion_tokens"
    
    # 其他模型使用 max_tokens
    return "max_tokens"
```

### Provider 注册表

**文件**: `src/openharness/api/registry.py`

#### ProviderSpec 定义

```python
@dataclass(frozen=True)
class ProviderSpec:
    """提供商规格"""
    
    name: str                        # 名称（如 "anthropic"）
    keywords: tuple[str, ...]        # 检测关键词
    env_key: str                     # 环境变量名
    backend_type: str                # 后端类型："anthropic" | "openai"
    default_base_url: str | None     # 默认 API 地址
    api_key_prefix: str | None       # API Key 前缀
    default_models: list[str] | None # 默认模型列表
    is_gateway: bool = False         # 是否为网关服务
    is_local: bool = False           # 是否为本地服务
    voice_supported: bool = False    # 是否支持语音
```

#### 内置 Provider 列表

```python
PROVIDERS: tuple[ProviderSpec, ...] = (
    # 网关服务（优先检测）
    ProviderSpec(
        name="copilot",
        keywords=("copilot",),
        env_key="GITHUB_TOKEN",
        backend_type="copilot",
        default_base_url=None,
        api_key_prefix=None,
        default_models=["gpt-4o"],
        is_gateway=True,
    ),
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        backend_type="openai",
        default_base_url="https://openrouter.ai/api/v1",
        api_key_prefix="sk-or-",
        default_models=None,
        is_gateway=True,
    ),
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="AIHUBMIX_API_KEY",
        backend_type="openai",
        default_base_url="https://aihubmix.com/v1",
        api_key_prefix=None,
        default_models=None,
        is_gateway=True,
    ),
    
    # 云端服务
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        backend_type="anthropic",
        default_base_url=None,
        api_key_prefix="sk-ant-",
        default_models=["claude-sonnet-4-6", "claude-opus-4-7"],
        is_gateway=False,
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        backend_type="openai",
        default_base_url=None,
        api_key_prefix="sk-",
        default_models=["gpt-4o", "gpt-4-turbo"],
        is_gateway=False,
    ),
    
    # ... 更多 Provider
)
```

#### Provider 检测

```python
def detect_provider_from_registry(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> ProviderSpec | None:
    """从注册表检测 Provider"""
    
    # 第一优先级：API Key 前缀
    if api_key:
        for provider in PROVIDERS:
            if provider.api_key_prefix and api_key.startswith(provider.api_key_prefix):
                return provider
    
    # 第二优先级：base_url 关键词
    if base_url:
        base_lower = base_url.lower()
        for provider in PROVIDERS:
            if provider.keywords:
                for keyword in provider.keywords:
                    if keyword in base_lower:
                        return provider
    
    # 第三优先级：model 关键词
    if model:
        model_lower = model.lower()
        for provider in PROVIDERS:
            if provider.keywords:
                for keyword in provider.keywords:
                    if keyword in model_lower:
                        return provider
    
    return None
```

### Provider 信息检测

**文件**: `src/openharness/api/provider.py`

#### ProviderInfo

```python
@dataclass(frozen=True)
class ProviderInfo:
    """Provider 信息"""
    
    name: str              # 名称
    auth_kind: str         # 认证类型："api_key" | "oauth" | "none"
    voice_supported: bool  # 是否支持语音
```

#### 多模态模型检测

```python
# 多模态模型命名模式（正则表达式）
_MULTIMODAL_MODEL_PATTERNS = (
    r"claude-3.*",           # Claude 3 系列
    r"claude-sonnet.*",      # Claude Sonnet
    r"claude-opus.*",        # Claude Opus
    r"gpt-4.*vision.*",      # GPT-4 Vision
    r"gpt-4o.*",             # GPT-4o
    r"gpt-4-turbo.*",        # GPT-4 Turbo
    r"gemini.*",             # Gemini
    r"qwen.*vl.*",           # 通义千问 VL
    r"glm-4v.*",             # 智谱 GLM-4V
    r"llava.*",              # LLaVA
    # ... 更多模式
)

def is_model_multimodal(model: str) -> bool:
    """启发式判断模型是否多模态"""
    
    for pattern in _MULTIMODAL_MODEL_PATTERNS:
        if re.match(pattern, model, re.IGNORECASE):
            return True
    
    return False
```

---

## 模块 2.2: 权限系统

### 架构概览

权限系统采用**多层防御**策略，从硬编码保护到用户配置规则，逐级检查。

```
用户请求 → 权限检查
    ↓
[1] 敏感路径保护（硬编码）
    ↓
[2] 工具黑名单
    ↓
[3] 工具白名单
    ↓
[4] 路径规则
    ↓
[5] 命令黑名单
    ↓
[6] 权限模式
    ↓
[7] 返回决策
```

### PermissionChecker

**文件**: `src/openharness/permissions/checker.py`

#### 敏感路径保护

```python
# 硬编码保护的敏感路径（不可覆盖）
SENSITIVE_PATH_PATTERNS = frozenset([
    "~/.ssh/*",              # SSH 密钥
    "~/.aws/*",              # AWS 凭证
    "~/.gnupg/*",            # GPG 密钥
    "~/.docker/*",           # Docker 配置
    "~/.kube/*",             # Kubernetes 配置
    "~/.openharness/credentials/*",  # OpenHarness 凭证
])
```

#### 核心检查流程

```python
class PermissionChecker:
    """权限检查器"""
    
    def __init__(self, settings: PermissionSettings, cwd: Path):
        self._settings = settings
        self._cwd = cwd
        self._sensitive_matcher = _build_sensitive_matcher()
    
    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool: BaseTool | None = None,
    ) -> PermissionDecision:
        """评估权限
        
        返回：
            PermissionDecision(allowed, requires_confirmation, reason)
        """
        
        # 1. 敏感路径检查
        if self._check_sensitive_paths(arguments):
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Access to sensitive path is denied",
            )
        
        # 2. 工具黑名单
        if tool_name in self._settings.denied_tools:
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason=f"Tool '{tool_name}' is denied",
            )
        
        # 3. 工具白名单
        if self._settings.allowed_tools:
            if tool_name not in self._settings.allowed_tools:
                return PermissionDecision(
                    allowed=False,
                    requires_confirmation=False,
                    reason=f"Tool '{tool_name}' not in allowed list",
                )
        
        # 4. 路径规则
        path_decision = self._check_path_rules(arguments)
        if path_decision is not None:
            return path_decision
        
        # 5. 命令黑名单
        if tool_name == "bash":
            command = arguments.get("command", "")
            for pattern in self._settings.denied_commands:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(
                        allowed=False,
                        requires_confirmation=False,
                        reason=f"Command matches denied pattern: {pattern}",
                    )
        
        # 6. 权限模式
        if self._settings.mode == PermissionMode.FULL_AUTO:
            # 完全自动：所有操作都允许
            return PermissionDecision(allowed=True, requires_confirmation=False)
        
        elif self._settings.mode == PermissionMode.PLAN:
            # 计划模式：修改操作需确认
            if tool and not tool.is_read_only(arguments):
                return PermissionDecision(
                    allowed=True,
                    requires_confirmation=True,
                    reason="Write operation in plan mode",
                )
        
        # 7. 默认模式：修改操作需确认
        if tool and not tool.is_read_only(arguments):
            return PermissionDecision(
                allowed=True,
                requires_confirmation=True,
                reason="Write operation requires confirmation",
            )
        
        return PermissionDecision(allowed=True, requires_confirmation=False)
```

#### 路径规则检查

```python
def _check_path_rules(
    self,
    arguments: dict[str, Any],
) -> PermissionDecision | None:
    """检查路径规则"""
    
    # 提取参数中的路径
    paths = self._extract_paths(arguments)
    
    for path in paths:
        # 解析路径
        resolved = _resolve_path(self._cwd, path)
        
        # 匹配规则
        for rule in self._settings.path_rules:
            if fnmatch.fnmatch(str(resolved), rule.pattern):
                if rule.allow:
                    # 允许规则
                    return PermissionDecision(allowed=True, requires_confirmation=False)
                else:
                    # 拒绝规则
                    return PermissionDecision(
                        allowed=False,
                        requires_confirmation=False,
                        reason=f"Path matches denied pattern: {rule.pattern}",
                    )
    
    return None

def _policy_match_paths(
    self,
    arguments: dict[str, Any],
) -> list[Path]:
    """从参数中提取路径"""
    
    paths = []
    
    # 常见路径参数名
    for key in ("path", "file_path", "dest", "source"):
        if key in arguments:
            paths.append(arguments[key])
    
    # Bash 命令特殊处理
    if "command" in arguments:
        # 解析命令中的路径
        ...
    
    return paths
```

### PermissionDecision

```python
@dataclass(frozen=True)
class PermissionDecision:
    """权限决策"""
    
    allowed: bool               # 是否允许
    requires_confirmation: bool # 是否需要确认
    reason: str                 # 原因
```

### PathRule

```python
@dataclass(frozen=True)
class PathRule:
    """路径规则"""
    
    pattern: str   # glob 模式
    allow: bool    # True=允许，False=拒绝
```

**使用示例**:

```python
# 配置路径规则
settings = PermissionSettings(
    path_rules=[
        PathRule(pattern="**/.env", allow=False),      # 拒绝所有 .env 文件
        PathRule(pattern="src/**", allow=True),         # 允许 src 目录
        PathRule(pattern="tests/**", allow=True),       # 允许 tests 目录
    ]
)
```

### PermissionMode

**文件**: `src/openharness/permissions/modes.py`

```python
class PermissionMode(str, Enum):
    """权限模式"""
    
    DEFAULT = "default"     # 默认：修改操作需确认
    PLAN = "plan"           # 计划模式：所有修改操作需确认
    FULL_AUTO = "full_auto" # 完全自动：所有操作都允许
```

**模式说明**:

| 模式 | 只读操作 | 修改操作 | 适用场景 |
|------|---------|---------|---------|
| `DEFAULT` | 自动允许 | 需确认 | 日常开发 |
| `PLAN` | 自动允许 | 需确认 | 规划阶段 |
| `FULL_AUTO` | 自动允许 | 自动允许 | 自动化脚本 |

---

## 模块 2.3: 钩子系统

### 架构概览

钩子系统采用**事件驱动**架构，在关键生命周期节点触发自定义逻辑。

```
Agent Loop
    ↓
[HookEvent]
    ↓
HookExecutor
    ↓
匹配 HookDefinition
    ↓
执行 Hook
    ├─ CommandHook → Shell 命令
    ├─ PromptHook → LLM 验证
    ├─ HttpHook → HTTP 请求
    └─ AgentHook → 独立 Agent
```

### HookEvent

**文件**: `src/openharness/hooks/events.py`

```python
class HookEvent(str, Enum):
    """钩子事件"""
    
    # 会话生命周期
    SESSION_START = "session_start"   # 会话开始
    SESSION_END = "session_end"       # 会话结束
    
    # 压缩事件
    PRE_COMPACT = "pre_compact"       # 压缩前
    POST_COMPACT = "post_compact"     # 压缩后
    
    # 工具调用
    PRE_TOOL_USE = "pre_tool_use"    # 工具调用前
    POST_TOOL_USE = "post_tool_use"   # 工具调用后
    
    # 用户交互
    USER_PROMPT_SUBMIT = "user_prompt_submit"  # 用户提交提示词
    
    # 通知
    NOTIFICATION = "notification"    # 通知事件
    
    # 停止
    STOP = "stop"                     # 停止事件
    
    # 子 Agent
    SUBAGENT_STOP = "subagent_stop"   # 子 Agent 停止
```

### HookDefinition 类型

**文件**: `src/openharness/hooks/schemas.py`

#### CommandHookDefinition

```python
class CommandHookDefinition(BaseModel):
    """命令钩子"""
    
    type: Literal["command"] = "command"
    command: str                      # Shell 命令
    timeout: int = 60                 # 超时（秒）
    matcher: str | None = None        # 匹配模式（fnmatch）
    block_on_failure: bool = False    # 失败时是否阻塞
```

**示例**:

```json
{
  "type": "command",
  "command": "pre-commit run --files $FILES",
  "matcher": "write_file",
  "block_on_failure": true
}
```

#### PromptHookDefinition

```python
class PromptHookDefinition(BaseModel):
    """提示词钩子（LLM 验证）"""
    
    type: Literal["prompt"] = "prompt"
    prompt: str                       # 验证提示词
    model: str | None = None          # 使用的模型
    block_on_failure: bool = True     # 失败时是否阻塞
```

**示例**:

```json
{
  "type": "prompt",
  "prompt": "Review this change for security issues. Return {\"ok\": true} if safe, {\"ok\": false, \"reason\": \"...\"} if not.",
  "model": "claude-sonnet-4-6",
  "block_on_failure": true
}
```

#### HttpHookDefinition

```python
class HttpHookDefinition(BaseModel):
    """HTTP 钩子"""
    
    type: Literal["http"] = "http"
    url: str                          # 请求 URL
    headers: dict[str, str] = {}      # 请求头
    block_on_failure: bool = False    # 失败时是否阻塞
```

**示例**:

```json
{
  "type": "http",
  "url": "https://api.example.com/hooks/pre-commit",
  "headers": {
    "Authorization": "Bearer $TOKEN"
  }
}
```

#### AgentHookDefinition

```python
class AgentHookDefinition(BaseModel):
    """Agent 钩子"""
    
    type: Literal["agent"] = "agent"
    prompt: str                       # Agent 提示词
    model: str | None = None          # 使用的模型
    block_on_failure: bool = True     # 失败时是否阻塞
    timeout: int = 300                # 超时（秒，最大 1200）
```

### HookExecutor

**文件**: `src/openharness/hooks/executor.py`

#### 核心实现

```python
@dataclass
class HookExecutionContext:
    """钩子执行上下文"""
    
    cwd: Path                       # 当前工作目录
    api_client: SupportsStreamingMessages  # API 客户端
    default_model: str              # 默认模型

class HookExecutor:
    """钩子执行器"""
    
    def __init__(self, registry: HookRegistry, context: HookExecutionContext):
        self._registry = registry
        self._context = context
    
    async def execute(
        self,
        event: HookEvent,
        *,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        prompt: str | None = None,
    ) -> AggregatedHookResult:
        """执行指定事件的所有钩子"""
        
        results = []
        
        # 获取匹配的钩子
        hooks = self._registry.get(event)
        
        for hook in hooks:
            # 检查是否匹配
            if not self._matches_hook(hook, tool_name, prompt):
                continue
            
            # 执行钩子
            try:
                result = await self._execute_hook(hook, tool_arguments)
                results.append(result)
                
                # 如果阻塞且失败，立即返回
                if result.blocked:
                    return AggregatedHookResult(results=results)
            
            except Exception as e:
                # 执行失败
                result = HookResult(
                    hook_type=hook.type,
                    success=False,
                    output=str(e),
                    blocked=hook.block_on_failure,
                    reason=f"Hook execution failed: {e}",
                )
                results.append(result)
                
                if hook.block_on_failure:
                    return AggregatedHookResult(results=results)
        
        return AggregatedHookResult(results=results)
```

#### 执行不同类型钩子

```python
async def _execute_hook(
    self,
    hook: HookDefinition,
    arguments: dict[str, Any] | None,
) -> HookResult:
    """执行单个钩子"""
    
    if hook.type == "command":
        return await self._run_command_hook(hook, arguments)
    
    elif hook.type == "prompt":
        return await self._run_prompt_hook(hook, arguments)
    
    elif hook.type == "http":
        return await self._run_http_hook(hook, arguments)
    
    elif hook.type == "agent":
        return await self._run_agent_hook(hook, arguments)
    
    else:
        raise ValueError(f"Unknown hook type: {hook.type}")

async def _run_command_hook(
    self,
    hook: CommandHookDefinition,
    arguments: dict[str, Any] | None,
) -> HookResult:
    """运行命令钩子"""
    
    # 1. 注入参数
    command = self._inject_arguments(hook.command, arguments)
    
    # 2. 创建子进程
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=self._context.cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **self._get_hook_env()},
    )
    
    # 3. 等待执行（带超时）
    try:
        await asyncio.wait_for(process.wait(), timeout=hook.timeout)
    except asyncio.TimeoutError:
        process.kill()
        return HookResult(
            hook_type="command",
            success=False,
            output=f"Command timed out after {hook.timeout}s",
            blocked=hook.block_on_failure,
            reason="Timeout",
        )
    
    # 4. 读取输出
    output = await process.stdout.read()
    text = output.decode("utf-8", errors="replace")
    
    return HookResult(
        hook_type="command",
        success=process.returncode == 0,
        output=text,
        blocked=hook.block_on_failure and process.returncode != 0,
        reason=None if process.returncode == 0 else "Command failed",
    )

async def _run_prompt_hook(
    self,
    hook: PromptHookDefinition,
    arguments: dict[str, Any] | None,
) -> HookResult:
    """运行提示词钩子（LLM 验证）"""
    
    # 1. 构建提示词
    prompt = self._inject_arguments(hook.prompt, arguments)
    
    # 2. 调用 LLM
    request = ApiMessageRequest(
        model=hook.model or self._context.default_model,
        messages=[ConversationMessage.from_user_text(prompt)],
        tools=[],
        max_tokens=1024,
    )
    
    response_text = ""
    async for event in self._context.api_client.stream_message(request):
        if isinstance(event, ApiTextDeltaEvent):
            response_text += event.text
    
    # 3. 解析响应
    try:
        result = json.loads(response_text)
        ok = result.get("ok", False)
        reason = result.get("reason", "No reason provided")
    except json.JSONDecodeError:
        ok = False
        reason = f"Invalid JSON response: {response_text}"
    
    return HookResult(
        hook_type="prompt",
        success=ok,
        output=response_text,
        blocked=hook.block_on_failure and not ok,
        reason=reason if not ok else None,
    )
```

### HookRegistry

**文件**: `src/openharness/hooks/loader.py`

```python
class HookRegistry:
    """钩子注册表"""
    
    def __init__(self):
        self._hooks: dict[HookEvent, list[HookDefinition]] = defaultdict(list)
    
    def register(self, event: HookEvent, hook: HookDefinition) -> None:
        """注册钩子"""
        self._hooks[event].append(hook)
    
    def get(self, event: HookEvent) -> list[HookDefinition]:
        """获取事件的所有钩子"""
        return self._hooks[event]

def load_hook_registry(
    settings: Settings,
    cwd: Path,
) -> HookRegistry:
    """加载钩子注册表"""
    
    registry = HookRegistry()
    
    # 1. 从设置加载
    if settings.hooks:
        for event_name, hooks in settings.hooks.items():
            event = HookEvent(event_name)
            for hook_data in hooks:
                hook = _parse_hook_definition(hook_data)
                registry.register(event, hook)
    
    # 2. 从插件加载
    for plugin in load_plugins(cwd):
        for event, hooks in plugin.hooks.items():
            for hook in hooks:
                registry.register(event, hook)
    
    return registry
```

### 热重载

**文件**: `src/openharness/hooks/hot_reload.py`

```python
class HookReloader:
    """钩子热重载器"""
    
    def __init__(self, config_path: Path, callback: Callable[[], None]):
        self._config_path = config_path
        self._callback = callback
        self._last_mtime = config_path.stat().st_mtime_ns
        self._task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """启动热重载监控"""
        self._task = asyncio.create_task(self._watch_loop())
    
    async def stop(self) -> None:
        """停止热重载监控"""
        if self._task:
            self._task.cancel()
    
    async def _watch_loop(self) -> None:
        """监控循环"""
        while True:
            await asyncio.sleep(1.0)  # 每秒检查一次
            
            try:
                mtime = self._config_path.stat().st_mtime_ns
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    self._callback()  # 触发重载
            except FileNotFoundError:
                pass
```

---

## 模块 2.4: 配置系统

### 架构概览

配置系统采用**多层合并**策略，优先级从高到低：CLI > 环境变量 > 配置文件 > 默认值。

```
配置来源（按优先级）
    ↓
[1] CLI 参数
    ↓
[2] 环境变量（OPENHARNESS_*）
    ↓
[3] 用户配置（~/.openharness/settings.json）
    ↓
[4] 项目配置（<project>/.openharness/settings.json）
    ↓
[5] 默认值
    ↓
合并 → Settings 对象
```

### Settings 模型

**文件**: `src/openharness/config/settings.py`

#### 核心结构

```python
class Settings(BaseModel):
    """全局配置"""
    
    # Provider 配置
    provider: str | None = None          # Provider 名称
    model: str | None = None             # 模型名称
    api_key: str | None = None           # API Key
    base_url: str | None = None          # API 地址
    
    # 权限配置
    permissions: PermissionSettings = PermissionSettings()
    
    # 钩子配置
    hooks: dict[str, list[dict]] = {}    # Hook 定义
    
    # 记忆配置
    memory: MemorySettings = MemorySettings()
    
    # 沙箱配置
    sandbox: SandboxSettings = SandboxSettings()
    
    # 其他配置
    max_tokens: int = 4096
    temperature: float | None = None
    
    @classmethod
    def load(cls, cwd: Path) -> "Settings":
        """加载配置（合并所有层）"""
        ...
```

#### PermissionSettings

```python
class PermissionSettings(BaseModel):
    """权限配置"""
    
    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = []        # 工具白名单
    denied_tools: list[str] = []         # 工具黑名单
    path_rules: list[PathRule] = []      # 路径规则
    denied_commands: list[str] = []      # 命令黑名单
```

#### MemorySettings

```python
class MemorySettings(BaseModel):
    """记忆配置"""
    
    enabled: bool = True                 # 是否启用
    max_files: int = 20                  # 最大文件数
    max_entrypoint_lines: int = 500      # 入口点最大行数
```

#### SandboxSettings

```python
class SandboxSettings(BaseModel):
    """沙箱配置"""
    
    network: NetworkSettings = NetworkSettings()
    filesystem: FilesystemSettings = FilesystemSettings()
    docker: DockerSettings = DockerSettings()

class NetworkSettings(BaseModel):
    """网络配置"""
    
    allowed_hosts: list[str] = ["*"]     # 允许的主机
    denied_hosts: list[str] = []         # 拒绝的主机

class FilesystemSettings(BaseModel):
    """文件系统配置"""
    
    read_only: bool = False              # 是否只读
    allowed_paths: list[str] = []       # 允许的路径
    denied_paths: list[str] = []        # 拒绝的路径
```

### ProviderProfile

```python
@dataclass(frozen=True)
class ProviderProfile:
    """Provider 配置档案"""
    
    label: str                           # 显示名称
    provider: str                        # Provider 名称
    api_format: str                      # API 格式："anthropic" | "openai"
    auth_source: str                    # 认证来源："env" | "file" | "oauth"
    default_model: str | None            # 默认模型
    base_url: str | None                 # API 地址
    credential_slot: str | None          # 凭证槽位
    models: list[str] | None             # 可用模型列表
```

#### 内置 Profile

```python
def default_provider_profiles() -> list[ProviderProfile]:
    """内置 Provider 配置档案"""
    
    return [
        ProviderProfile(
            label="claude-api",
            provider="anthropic",
            api_format="anthropic",
            auth_source="env",
            default_model="claude-sonnet-4-6",
            base_url=None,
            credential_slot="ANTHROPIC_API_KEY",
            models=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        ),
        ProviderProfile(
            label="openai-compatible",
            provider="openai",
            api_format="openai",
            auth_source="env",
            default_model="gpt-4o",
            base_url=None,
            credential_slot="OPENAI_API_KEY",
            models=["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        ),
        ProviderProfile(
            label="copilot",
            provider="copilot",
            api_format="copilot",
            auth_source="oauth",
            default_model="gpt-4o",
            base_url=None,
            credential_slot="GITHUB_TOKEN",
            models=["gpt-4o"],
        ),
        # ... 更多 Profile
    ]
```

### 模型别名解析

```python
def resolve_model_setting(
    model_alias: str,
    provider: str,
    default_models: dict[str, str],
) -> str:
    """解析模型别名
    
    Args:
        model_alias: 别名（"default", "best", "sonnet", "opus", "haiku"）
        provider: Provider 名称
        default_models: 默认模型映射
    
    Returns:
        实际模型名称
    """
    
    # Claude 家族别名
    if provider == "anthropic":
        aliases = {
            "default": "claude-sonnet-4-6",
            "best": "claude-opus-4-7",
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-7",
            "haiku": "claude-haiku-4-5",
        }
        return aliases.get(model_alias, model_alias)
    
    # OpenAI 家族别名
    elif provider == "openai":
        aliases = {
            "default": "gpt-4o",
            "best": "gpt-4o",
        }
        return aliases.get(model_alias, model_alias)
    
    # 其他 Provider：使用默认或原值
    return default_models.get(provider, model_alias)
```

### 路径解析

**文件**: `src/openharness/config/paths.py`

#### XDG 风格路径

```python
def get_config_dir() -> Path:
    """获取配置目录
    
    优先级：
    1. OPENHARNESS_CONFIG_DIR 环境变量
    2. ~/.openharness/
    """
    env_dir = os.environ.get("OPENHARNESS_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    
    return Path.home() / ".openharness"

def get_data_dir() -> Path:
    """获取数据目录
    
    返回：~/.openharness/data/
    """
    return get_config_dir() / "data"

def get_sessions_dir() -> Path:
    """获取会话目录
    
    返回：~/.openharness/sessions/
    """
    return get_config_dir() / "sessions"

def get_tasks_dir() -> Path:
    """获取任务目录
    
    返回：~/.openharness/tasks/
    """
    return get_config_dir() / "tasks"

def get_logs_dir() -> Path:
    """获取日志目录
    
    返回：~/.openharness/logs/
    """
    return get_config_dir() / "logs"

def get_project_config_dir(cwd: Path) -> Path:
    """获取项目配置目录
    
    返回：<project>/.openharness/
    """
    return cwd / ".openharness"
```

#### Autopilot 路径

```python
def get_autopilot_registry() -> Path:
    """获取 Autopilot 注册表
    
    返回：~/.openharness/autopilot/registry.json
    """
    return get_data_dir() / "autopilot" / "registry.json"

def get_repo_journal(cwd: Path) -> Path:
    """获取仓库日志
    
    返回：<project>/.openharness/journal.md
    """
    return get_project_config_dir(cwd) / "journal.md"

def get_active_repo_context(cwd: Path) -> Path:
    """获取活动仓库上下文
    
    返回：<project>/.openharness/context.md
    """
    return get_project_config_dir(cwd) / "context.md"
```

---

## 实践项目

### 项目 2.1: 添加新的 Provider

**目标**: 添加对 Groq Provider 的支持

#### 步骤 1: 添加 ProviderSpec

```python
# src/openharness/api/registry.py

PROVIDERS: tuple[ProviderSpec, ...] = (
    # ... 其他 Provider
    
    ProviderSpec(
        name="groq",
        keywords=("groq", "llama", "mixtral"),
        env_key="GROQ_API_KEY",
        backend_type="openai",
        default_base_url="https://api.groq.com/openai/v1",
        api_key_prefix="gsk_",
        default_models=["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
        is_gateway=False,
    ),
)
```

#### 步骤 2: 测试 Provider 检测

```python
# tests/test_api/test_registry.py

def test_groq_detection():
    """测试 Groq Provider 检测"""
    
    # 通过 API Key 前缀检测
    provider = detect_provider_from_registry(
        api_key="gsk_test123",
        base_url=None,
        model=None,
    )
    assert provider.name == "groq"
    
    # 通过 base_url 检测
    provider = detect_provider_from_registry(
        api_key=None,
        base_url="https://api.groq.com/openai/v1",
        model=None,
    )
    assert provider.name == "groq"
    
    # 通过模型名称检测
    provider = detect_provider_from_registry(
        api_key=None,
        base_url=None,
        model="llama-3.3-70b-versatile",
    )
    assert provider.name == "groq"
```

---

### 项目 2.2: 实现自定义 Hook

**目标**: 创建文件写入前的代码格式检查 Hook

#### 步骤 1: 创建 Hook 配置

```json
// ~/.openharness/settings.json

{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "black --check $FILE_PATH",
        "matcher": "write_file",
        "block_on_failure": true
      }
    ]
  }
}
```

#### 步骤 2: 测试 Hook

```bash
# 启动会话
uv run oh

# 尝试写入未格式化的代码
"Write a Python function to calculate fibonacci"
```

**预期行为**:

1. LLM 调用 `write_file` 工具
2. `pre_tool_use` Hook 触发
3. 执行 `black --check` 命令
4. 如果格式不正确，阻塞操作并显示错误

---

### 项目 2.3: 配置多层权限规则

**目标**: 配置多层权限规则，保护敏感文件

#### 步骤 1: 创建配置文件

```json
// ~/.openharness/settings.json

{
  "permissions": {
    "mode": "default",
    "denied_tools": ["bash"],
    "denied_commands": ["rm -rf", "sudo"],
    "path_rules": [
      {"pattern": "**/.env", "allow": false},
      {"pattern": "**/credentials.json", "allow": false},
      {"pattern": "src/**", "allow": true},
      {"pattern": "tests/**", "allow": true}
    ]
  }
}
```

#### 步骤 2: 测试权限检查

```bash
# 启动会话
uv run oh --config ~/.openharness/settings.json

# 测试被拒绝的工具
"Use bash to list files"  # 应该被拒绝

# 测试被拒绝的命令
"Run rm -rf /tmp/test"    # 应该被拒绝

# 测试路径规则
"Read .env file"          # 应该被拒绝
"Read src/main.py"        # 应该被允许
```

---

## 验收标准

完成本阶段后，你应该能够：

### 理论理解

- [ ] 解释 `SupportsStreamingMessages` Protocol 的设计目的
- [ ] 描述 Anthropic 和 OpenAI 客户端的实现差异
- [ ] 说明 Provider 自动检测的 3 层优先级
- [ ] 描述权限检查的 7 步流程
- [ ] 解释 4 种 Hook 类型的作用场景
- [ ] 说明多层配置的合并优先级

### 实践能力

- [ ] 添加新的 ProviderSpec 到注册表
- [ ] 实现 4 种类型的 Hook
- [ ] 配置多层权限规则
- [ ] 使用模型别名（default/best/sonnet/opus/haiku）

### 测试能力

- [ ] 编写 Provider 检测测试
- [ ] 编写 Hook 执行测试
- [ ] 编写权限检查测试

### 调试能力

- [ ] 使用 `--debug` 查看 API 客户端日志
- [ ] 查看 Hook 执行结果
- [ ] 追踪配置加载流程

---

## 常见问题

### Q1: 如何添加新的 Provider？

**A**: 三步流程：

1. 在 `PROVIDERS` 元组中添加 `ProviderSpec`
2. 实现 API 客户端（如果需要新格式）
3. 编写检测测试

### Q2: Hook 失败会发生什么？

**A**: 取决于 `block_on_failure` 设置：

- `true`: Hook 失败会阻塞操作
- `false`: Hook 失败只记录日志，不阻塞

### Q3: 配置优先级是什么？

**A**: 从高到低：

1. CLI 参数（`--model`、`--provider` 等）
2. 环境变量（`OPENHARNESS_MODEL` 等）
3. 用户配置（`~/.openharness/settings.json`）
4. 项目配置（`<project>/.openharness/settings.json`）
5. 默认值

### Q4: 如何调试权限问题？

**A**: 使用 `--debug` 标志：

```bash
uv run oh --debug
```

日志会显示：
- 哪个工具被调用
- 权限检查的每一步
- 最终决策（allowed/requires_confirmation）

### Q5: 如何查看当前配置？

**A**: 使用 `--show-config` 标志：

```bash
uv run oh --show-config
```

会显示合并后的完整配置。

---

## 下一步

完成本阶段后，继续学习：

**阶段 3: 关键模块深入**
- 记忆系统
- 沙箱隔离
- MCP 协议
- 前端架构

---

## 参考资源

### 核心文件

- `src/openharness/api/client.py` - API 客户端基类
- `src/openharness/api/openai_client.py` - OpenAI 兼容客户端
- `src/openharness/api/registry.py` - Provider 注册表
- `src/openharness/permissions/checker.py` - 权限检查器
- `src/openharness/hooks/executor.py` - Hook 执行器
- `src/openharness/config/settings.py` - 配置模型

### 相关文档

- [Anthropic API 文档](https://docs.anthropic.com/)
- [OpenAI API 文档](https://platform.openai.com/docs/)
- [Pydantic 文档](https://docs.pydantic.dev/)
- [Python asyncio 文档](https://docs.python.org/3/library/asyncio.html)

### 扩展阅读

- [ARCHITECTURE.md](../ARCHITECTURE.md) - 完整架构文档
- [LEARNING_PATH.md](../LEARNING_PATH.md) - 学习路线
- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南

---

**文档版本**: 1.0  
**更新日期**: 2026-05-06  
**维护者**: OpenHarness Team

祝你学习愉快！如有问题，欢迎在 GitHub Issues 中提问。
