# Error Handling

> How errors are handled in this project.

---

## Overview

OpenHarness uses a layered error handling strategy:
- **Custom exception hierarchy** for domain-specific failures
- **Error-to-stream conversion** inside the query engine (errors become `ErrorEvent` or `ToolResultBlock`)
- **Retry with exponential backoff** for transient API failures
- **Graceful degradation** for optional subsystems (keyring → file, sandbox → unsandboxed)

---

## Error Types

### Base Exception Hierarchy

Custom exceptions inherit from `RuntimeError` (operational failures) or `ValueError` (invalid input):

```python
# src/openharness/api/errors.py
class OpenHarnessApiError(RuntimeError):
    """Base class for upstream API failures."""

class AuthenticationFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the provided credentials."""

class RateLimitFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the request due to rate limits."""

class RequestFailure(OpenHarnessApiError):
    """Raised for generic request or transport failures."""
```

### Other Domain Errors

| Error | Location | Inherits From | Purpose |
|-------|----------|---------------|---------|
| `SwarmLockError` | `src/openharness/utils/file_lock.py` | `RuntimeError` | File-lock failures |
| `SwarmLockUnavailableError` | `src/openharness/utils/file_lock.py` | `SwarmLockError` | Platform without file locking |
| `NetworkGuardError` | `src/openharness/utils/network_guard.py` | `ValueError` | Outbound HTTP policy violation |
| `SandboxUnavailableError` | `src/openharness/sandbox/adapter.py` | `RuntimeError` | Sandbox required but unavailable |
| `MaxTurnsExceeded` | `src/openharness/engine/query.py` | `RuntimeError` | Agent turn limit hit |
| `McpServerNotConnectedError` | `src/openharness/mcp/client.py` | `Exception` | MCP server session lost |

---

## Error Handling Patterns

### 1. Retry with Exponential Backoff (API Client)

```python
# src/openharness/api/client.py:160-196
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

for attempt in range(MAX_RETRIES + 1):
    try:
        async with self._client.messages.stream(...) as response:
            ...
        return
    except APIStatusError as exc:
        if exc.status_code not in RETRYABLE_STATUS_CODES:
            raise _translate_api_error(exc) from exc
        delay = _get_retry_delay(exc, attempt)
        yield ApiRetryEvent(attempt=attempt + 1, delay=delay), None
        await asyncio.sleep(delay)
```

### 2. Error-to-Stream Conversion (Query Engine)

Errors inside the async generator are converted to `ErrorEvent` or `ToolResultBlock` instead of propagating:

```python
# src/openharness/engine/query.py:749-776
except Exception as exc:
    if _is_completion_token_limit_error(exc):
        # adapt max_tokens and retry
        continue
    yield ErrorEvent(message=f"API error: {exc}"), None
    return
```

```python
# src/openharness/engine/query.py:900-908
try:
    parsed_input = tool.input_model.model_validate(tool_input)
except Exception as exc:
    log.warning("invalid input for %s: %s", tool_name, exc)
    return ToolResultBlock(
        tool_use_id=tool_use_id,
        content=f"Invalid input for {tool_name}: {exc}",
        is_error=True,
    )
```

### 3. Concurrent Tool Execution with `return_exceptions=True`

```python
# src/openharness/engine/query.py:838-855
raw_results = await asyncio.gather(
    *[_run(tc) for tc in tool_calls], return_exceptions=True
)
for tc, result in zip(tool_calls, raw_results):
    if isinstance(result, BaseException):
        log.exception("tool execution raised: %s", tc.name, exc_info=result)
        result = ToolResultBlock(
            tool_use_id=tc.id,
            content=f"Tool {tc.name} failed: {type(result).__name__}: {result}",
            is_error=True,
        )
```

### 4. Interruption-to-Tool-Result Conversion

#### 1. Scope / Trigger

Interactive query cancellation crosses the UI backend, `QueryEngine`, the query
loop, and tool implementations. It must be represented as typed interrupt state,
not only raw task cancellation, because provider APIs reject an assistant
`tool_use` that is not followed by a matching user `tool_result`.

#### 2. Signatures

```python
# src/openharness/tools/base.py
InterruptReason = Literal["user_cancel", "submit_interrupt", "shutdown", "tool_failure"]
ToolInterruptBehavior = Literal["cancel", "block"]

@dataclass
class InterruptState:
    reason: InterruptReason | None = None
    running_tool_behaviors: set[ToolInterruptBehavior] = field(default_factory=set)

    def request(self, reason: InterruptReason) -> None: ...
    def clear(self) -> None: ...
    def set_running_tool_behaviors(self, behaviors: set[ToolInterruptBehavior]) -> None: ...
    def clear_running_tool_behaviors(self) -> None: ...
    def all_running_tools_interruptible(self) -> bool: ...
    def raise_if_requested(self) -> None: ...

@dataclass
class ToolExecutionContext:
    interrupt_state: InterruptState = field(default_factory=InterruptState)

class BaseTool(ABC):
    def interrupt_behavior(self) -> ToolInterruptBehavior:
        return "block"
```

```python
# src/openharness/engine/query.py
@dataclass
class QueryContext:
    interrupt_state: InterruptState = field(default_factory=InterruptState)
```

```python
# src/openharness/engine/query_engine.py
def request_interrupt(self, reason: InterruptReason) -> None: ...
def can_submit_interrupt(self) -> bool: ...
```

#### 3. Contracts

- `user_cancel`: stop the active turn, insert `[Request interrupted by user]`
  user message into conversation history, and continue draining remaining queued
  turns.
- `submit_interrupt`: only cancel the active tool phase when every running tool
  reports `interrupt_behavior() == "cancel"`; otherwise keep the urgent turn
  queued. Do **not** insert an interrupt user message — the queued turn itself
  provides context.
- `shutdown`: stop work for teardown, insert `[Request interrupted by user]`
  user message, and exit the drain loop immediately.
- `tool_failure`: internal reason for tool failure cascades.
- `block` is the default tool behavior and is the safe choice for mutating,
  shell-like, or side-effectful tools.
- `cancel` is opt-in for tools whose cleanup is safe and whose partial work will
  not corrupt state.

#### 4. Validation & Error Matrix

| Condition | Required behavior |
|-----------|-------------------|
| Interrupt before model/tool output | Raise/catch cancellation normally; no synthetic tool result is needed. |
| Interrupt after assistant `tool_use` and before matching result | Append one error `ToolResultBlock` for every unresolved tool use before returning control. |
| `user_cancel` or `shutdown` after CancelledError in `submit_message` | Insert `[Request interrupted by user]` user message at end of `QueryEngine._messages`. |
| `submit_interrupt` after CancelledError in `submit_message` | Do NOT insert interrupt user message; the queued turn provides context. |
| `user_cancel` in `_drain_turn_queue` | Continue processing remaining queued turns (do not exit the loop). |
| `shutdown` in `_drain_turn_queue` | Exit the drain loop immediately. |
| Submit-interrupt while any running tool is `block` | Do not cancel the active tool phase; leave the queued urgent turn pending. |
| Submit-interrupt while all running tools are `cancel` | Request interruption, cancel running tool tasks, and continue with provider-safe tool results. |
| Subprocess tool receives cancellation | Clean up the subprocess first, then let the query layer normalize cancellation into tool results. |

#### 5. Good/Base/Bad Cases

- Good: `sleep` checks `context.interrupt_state.raise_if_requested()` around
  blocking work and declares `interrupt_behavior() == "cancel"`.
- Base: a tool does not override `interrupt_behavior()`, so submit-interrupt is
  blocked while it runs.
- Bad: a tool swallows `asyncio.CancelledError` and returns a successful
  `ToolResult`, hiding that the user interrupted the turn.

#### 6. Tests Required

- Query engine regression: cancellation after assistant `tool_use` produces
  matching error `ToolResultBlock` entries in conversation history.
- Query engine regression: `user_cancel`/`shutdown` cancellation inserts
  `[Request interrupted by user]` user message; `submit_interrupt` does not.
- Parallel tool regression: cancellation or one tool failure cannot leave sibling
  tool uses unresolved.
- Backend host regression: user cancel continues draining remaining queued turns;
  shutdown exits the drain loop.
- Backend host regression: submit-interrupt cancels only when
  `QueryEngine.can_submit_interrupt()` is true.
- Tool regression: at least one `cancel` tool and one default `block` tool cover
  the policy matrix.

#### 7. Wrong vs Correct

Wrong:

```python
# Cancels the task after assistant tool_use, leaving history malformed.
task.cancel()
```

Correct:

```python
engine.request_interrupt("submit_interrupt")
task.cancel("submit_interrupt")
# query layer appends interrupted ToolResultBlock entries for unresolved tools
```

### 5. Graceful Degradation (Keyring Fallback)

```python
# src/openharness/auth/storage.py:130-138
if use_keyring:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _keyring_key(provider, key), value)
        return
    except Exception as exc:
        log.warning("Keyring store failed, falling back to file: %s", exc)
# ... fall back to file-based storage
```

### 6. Best-Effort Operations with `contextlib.suppress`

```python
# For operations where failure is acceptable
with contextlib.suppress(Exception):
    path.unlink(missing_ok=True)
```

---

## API Error Responses

### To-Model (Tool Results)

```python
# src/openharness/engine/messages.py
class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False
```

Errors are flagged with `is_error=True` and include human-readable message in `content`.

### To-Frontend (Backend Events)

```python
BackendEvent(type="error", message="...")
```

### To-Chat Channels (Gateway)

```python
# ohmo/gateway/bridge.py:26-50
def _format_gateway_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    # ... translate known error patterns to actionable guidance
    return f"[ohmo gateway error] {message}"
```

Gateway errors are prefixed with `[ohmo gateway error]` and include remediation steps.

---

## Common Mistakes

- **Letting exceptions escape the query engine** — convert to `ErrorEvent` instead.
- **Using bare `except:`** — always catch `Exception` or more specific types.
- **Swallowing errors without logging** — use `log.exception()` at minimum.
- **Retry without backoff** — use exponential backoff with jitter for retries.
- **Not preserving exception chains** — use `raise ... from exc` for translated errors.
