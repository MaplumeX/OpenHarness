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

### 4. Graceful Degradation (Keyring Fallback)

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

### 5. Best-Effort Operations with `contextlib.suppress`

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
