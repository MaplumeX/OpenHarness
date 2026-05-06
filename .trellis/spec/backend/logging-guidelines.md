# Logging Guidelines

> How logging is done in this project.

---

## Overview

OpenHarness uses Python's standard library `logging` module. No third-party logging libraries (structlog, loguru, etc.) are used. Log format is plain text (not JSON).

---

## Logging Setup

```python
# src/openharness/cli.py:2253-2261
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
)
```

Every module initializes its logger at the top:

```python
log = logging.getLogger(__name__)
```

---

## Log Levels

| Level | Usage | Example |
|-------|-------|---------|
| `DEBUG` | Normal tool execution flow, backend detection, permission checks | `log.debug("tool_call start: %s id=%s", tool_name, tool_use_id)` |
| `INFO` | Gateway lifecycle, channel routing, significant events | `logger.info("ohmo bridge connected workspace=%s", workspace)` |
| `WARNING` | Recoverable issues, fallbacks, invalid inputs | `log.warning("Keyring store failed, falling back to file: %s", exc)` |
| `ERROR` | Irrecoverable failures that still allow continuation | `logger.error("Failed to spawn teammate %s: %s", agent_id, exc)` |
| `EXCEPTION` | Unhandled/unexpected exceptions with full traceback | `logger.exception("ohmo gateway failed to process inbound message")` |

---

## Logging Format

### Use `%s`-style formatting (never f-strings)

```python
# CORRECT
log.debug("executed %s in %.2fs err=%s output_len=%d",
          tool_name, elapsed, result.is_error, len(result.output or ""))

# WRONG
log.debug(f"executed {tool_name} in {elapsed:.2f}s")  # Don't do this
```

### Use named parameters for context

```python
log.warning(
    "API request failed (attempt %d/%d, status=%s), retrying in %.1fs: %s",
    attempt + 1, MAX_RETRIES + 1, status, delay, exc,
)
```

---

## What to Log

- Backend detection and selection (tmux/iterm2/subprocess)
- Agent/teammate spawn, messaging, and shutdown events
- Gateway session lifecycle (connect, restart, error handling)
- Plugin/skill loading operations
- Authentication flows
- Docker sandbox operations
- Error conditions with stack traces (via `log.exception`)

---

## What NOT to Log

- **Tokens, secrets, credentials** — reference by name/ID, never log values
- **User prompts and model responses** — don't log conversation content
- **PII** — avoid logging user data that may contain sensitive info

---

## Real Examples

```python
# src/openharness/swarm/registry.py:33-38
logger.debug("[BackendRegistry] _detect_tmux: $TMUX not set")
logger.debug("[BackendRegistry] _detect_tmux: tmux binary not found on PATH")
logger.debug("[BackendRegistry] _detect_tmux: inside tmux session with binary available")

# src/openharness/swarm/subprocess_backend.py:90,100,156
logger.error("Failed to spawn teammate %s: %s", agent_id, exc)
logger.debug("Spawned teammate %s as task %s", agent_id, record.id)
logger.debug("Shut down teammate %s (task %s)", agent_id, task_id)

# ohmo/gateway/bridge.py:81,184,210
logger.info("ohmo bridge connected workspace=%s", workspace)
logger.info("ohmo bridge streaming message session=%s type=%s", session_key, message_type)
logger.exception("ohmo bridge error in message handler session=%s", session_key)
```
