# Research: OpenHarness interrupt and queue current gaps

- Query: Current OpenHarness implementation relevant to robust interrupt handling and message queue integration.
- Scope: internal
- Date: 2026-05-08

## Findings

### Files found

- `src/openharness/ui/session_queue.py` - in-memory priority queue for interactive session turns.
- `src/openharness/ui/backend_host.py` - React terminal JSON-lines backend, request loop, interrupt handling, queue drain.
- `src/openharness/ui/protocol.py` - Pydantic protocol models for frontend requests, backend events, and queue snapshots.
- `frontend/terminal/src/App.tsx` - Ink application input handling and busy-state submission behavior.
- `frontend/terminal/src/hooks/useBackendSession.ts` - backend child process bridge, event reducer, busy/queue state.
- `frontend/terminal/src/components/PromptInput.tsx` - multiline prompt input that remains focused during busy state.
- `frontend/terminal/src/components/StatusBar.tsx` - queue count rendering.
- `src/openharness/engine/query.py` - tool-aware model loop and tool execution.
- `src/openharness/engine/query_engine.py` - conversation history owner around `run_query`.
- `src/openharness/engine/messages.py` - conversation/tool-use models and restore-time sanitization.
- `src/openharness/ui/runtime.py` - `handle_line` bridge between UI commands and `QueryEngine`.
- `src/openharness/tools/base.py` - base tool abstraction and execution context.
- `src/openharness/tools/bash_tool.py` - representative long-running subprocess tool.
- `src/openharness/tools/grep_tool.py` - representative search subprocess tool with Python fallback.
- `src/openharness/tools/sleep_tool.py` - minimal cancellable async tool.
- `tests/test_ui/test_react_backend.py` - current backend interrupt and queue tests.
- `tests/test_ui/test_session_queue.py` - queue unit tests.
- `tests/test_engine/test_query_engine.py` - query/tool execution tests including parallel tool-result safety.
- `tests/test_engine/test_messages.py` - restore-time malformed tool-turn sanitization tests.
- `tests/test_tools/test_bash_tool.py` - subprocess timeout and cleanup tests.

### Current queue behavior

- `SessionTurnQueue` supports only three priorities, `now`, `next`, and `later`, and returns FIFO order within each priority using an internal sequence counter (`src/openharness/ui/session_queue.py:11`, `src/openharness/ui/session_queue.py:80`, `src/openharness/ui/session_queue.py:100`, `src/openharness/ui/session_queue.py:115`).
- Queue items have static metadata and a computed display label, but no lifecycle reason, interrupt policy, owner, cancellation timestamp, or retry/resume marker (`src/openharness/ui/session_queue.py:47`).
- `ReactBackendHost.run` enqueues `submit_line` and `apply_select_command` requests instead of executing them directly (`src/openharness/ui/backend_host.py:161`, `src/openharness/ui/backend_host.py:173`).
- `_enqueue_submit_line`, `_enqueue_apply_select_command`, and `_enqueue_synthetic_followup` emit a queue snapshot and start one drain task (`src/openharness/ui/backend_host.py:237`, `src/openharness/ui/backend_host.py:252`, `src/openharness/ui/backend_host.py:268`, `src/openharness/ui/backend_host.py:284`).
- `_drain_turn_queue` sets the active turn, runs it, appends a recent snapshot as `completed` or `cancelled`, then clears active state (`src/openharness/ui/backend_host.py:289`, `src/openharness/ui/backend_host.py:295`, `src/openharness/ui/backend_host.py:298`, `src/openharness/ui/backend_host.py:300`).
- If the active turn is cancelled, `_drain_turn_queue` returns immediately and leaves later queued turns in the queue (`src/openharness/ui/backend_host.py:304`). This matches the current test expectation that interrupting `first` leaves `second` queued (`tests/test_ui/test_react_backend.py:226`), but it does not automatically resume queued work after a safe cancellation.
- Queue snapshots include `active`, `queued`, and `recent` arrays, with item states limited to `queued`, `running`, `completed`, and `cancelled` (`src/openharness/ui/protocol.py:66`, `src/openharness/ui/protocol.py:78`).
- The status bar only renders queue state as `running`/`idle` plus queued count (`frontend/terminal/src/components/StatusBar.tsx:76`, `frontend/terminal/src/components/StatusBar.tsx:107`). There is no user-facing cancelled reason or blocked-by-tool state.

### Current interrupt behavior

- The only backend interrupt mechanism is direct cancellation of the active asyncio task (`src/openharness/ui/backend_host.py:331`). There is no interrupt object, reason enum, cancellation token, or policy check.
- Interrupt requests are handled both in `_read_requests` and the main `run` loop, which gives interrupt priority over the normal request queue when read directly from stdin (`src/openharness/ui/backend_host.py:150`, `src/openharness/ui/backend_host.py:210`).
- `_run_active_request` catches `asyncio.CancelledError`, marks `_active_request_cancelled`, emits a system transcript item, status/tasks snapshots, and `line_complete`, then returns `True` (`src/openharness/ui/backend_host.py:215`, `src/openharness/ui/backend_host.py:221`). This converts cancellation to UI completion at the host layer only.
- `_shutdown` also calls `_interrupt_active_request`, so shutdown and user interrupt currently share the same cancellation path and cannot be distinguished downstream (`src/openharness/ui/backend_host.py:323`).
- Permission/question modal futures are popped in `finally`, but an interrupt during `_ask_permission` or `_ask_question` does not emit a modal-clear event (`src/openharness/ui/backend_host.py:869`, `src/openharness/ui/backend_host.py:893`). The frontend `line_complete` handler clears busy state, not `modal`, so an interrupted modal can remain visible until another event changes it (`frontend/terminal/src/hooks/useBackendSession.ts:359`, `frontend/terminal/src/hooks/useBackendSession.ts:399`).

### Current frontend submission behavior

- `PromptInput` always renders `MultilineTextInput` with `focus`, including when `busy` is true (`frontend/terminal/src/components/PromptInput.tsx:221`). Its Enter handler calls `onSubmit` regardless of busy state (`frontend/terminal/src/components/PromptInput.tsx:85`).
- `App.onSubmit` sends `submit_line` during busy state and clears the local input/history (`frontend/terminal/src/App.tsx:385`). This means ordinary Enter submit can queue a prompt while a turn is running.
- The top-level `useInput` handler still returns early for most keys when `session.busy` is true (`frontend/terminal/src/App.tsx:284`). Ctrl+C/Escape interrupt works (`frontend/terminal/src/App.tsx:182`, `frontend/terminal/src/App.tsx:278`), and `/stop` in `onSubmit` maps to interrupt (`frontend/terminal/src/App.tsx:376`), but busy-state editing/navigation behavior depends on `PromptInput`'s separate input handler and should be tested at the Ink level.
- `useBackendSession` sets `busy` to true when a queue snapshot has an active turn, but it does not set `busy` false from an empty queue snapshot; `line_complete` remains the true end-of-turn signal (`frontend/terminal/src/hooks/useBackendSession.ts:251`, `frontend/terminal/src/hooks/useBackendSession.ts:359`).

### Current query and conversation-state behavior

- `QueryContext` has no cancellation or interrupt fields (`src/openharness/engine/query.py:137`).
- `run_query` catches normal `Exception` around provider streaming and converts it to `ErrorEvent`, but it does not catch `asyncio.CancelledError` because that is a cancellation control-flow exception (`src/openharness/engine/query.py:724`, `src/openharness/engine/query.py:749`).
- After a model response, `run_query` appends the assistant message and yields `AssistantTurnComplete` before executing tools (`src/openharness/engine/query.py:796`, `src/openharness/engine/query.py:797`).
- `QueryEngine.submit_message` copies `query_messages` back into engine history when it observes `AssistantTurnComplete` (`src/openharness/engine/query_engine.py:181`, `src/openharness/engine/query_engine.py:185`, `src/openharness/engine/query_engine.py:186`). If cancellation happens after the assistant emitted `tool_use` blocks but before matching `tool_result` blocks are appended, `engine.messages` can end with dangling tool uses.
- `run_query` appends tool results only after all selected tools complete (`src/openharness/engine/query.py:864`). There is no synthetic interrupted `ToolResultBlock` path for cancellation before this point.
- Restore-time sanitization can drop dangling trailing `tool_use` messages and orphan tool results (`src/openharness/engine/messages.py:118`, `tests/test_engine/test_messages.py:30`, `tests/test_engine/test_messages.py:44`), but runtime interruption does not call this sanitizer before the next queued or submitted turn.
- `handle_line` saves a session snapshot after normal completion or `MaxTurnsExceeded`, but not in a `finally` for arbitrary cancellation (`src/openharness/ui/runtime.py:641`, `src/openharness/ui/runtime.py:660`). An interrupted turn can therefore leave in-memory history malformed while persistent restore later may sanitize a different state.
- Parallel tool execution already has a safety pattern for ordinary tool exceptions: `asyncio.gather(..., return_exceptions=True)` and synthetic error `ToolResultBlock` for raised tools (`src/openharness/engine/query.py:834`, `src/openharness/engine/query.py:838`, `src/openharness/engine/query.py:843`). The regression test covers ordinary raised exceptions, not parent-task cancellation (`tests/test_engine/test_query_engine.py:1215`).

### Current tool cancellation behavior

- `ToolExecutionContext` carries `cwd`, metadata, and hooks only. It has no cancellation token, interrupt reason, deadline, or helper method for cooperative checks (`src/openharness/tools/base.py:17`).
- `BaseTool` has `execute`, `is_read_only`, and `to_api_schema`; it has no `interrupt_behavior` contract such as `cancel` versus `block` (`src/openharness/tools/base.py:35`).
- `_execute_tool_call` awaits `tool.execute` directly and converts successful tool output to `ToolResultBlock`; it does not catch `asyncio.CancelledError` and does not synthesize interrupted tool results (`src/openharness/engine/query.py:952`, `src/openharness/engine/query.py:976`).
- `SleepTool` is naturally cancellable via `asyncio.sleep`, but cancellation raises and produces no `ToolResult` (`src/openharness/tools/sleep_tool.py:29`).
- `BashTool` cleans up subprocesses on `asyncio.CancelledError` and re-raises (`src/openharness/tools/bash_tool.py:55`, `src/openharness/tools/bash_tool.py:75`). This prevents orphan subprocesses but still leaves the query without a provider-safe tool result.
- `GrepTool` terminates `rg` subprocesses on cancellation and re-raises (`src/openharness/tools/grep_tool.py:212`, `src/openharness/tools/grep_tool.py:286`). Its pure-Python fallback is synchronous over files and has no cooperative cancellation checkpoint (`src/openharness/tools/grep_tool.py:94`).

### Likely test points

- Backend host: busy submit should enqueue a new `submit_line`, emit a `queue_snapshot`, and preserve order while the active turn is running. Existing coverage is close in `tests/test_ui/test_react_backend.py:182`, but should include the request-loop path and frontend-visible snapshot expectations.
- Backend host: interrupt should distinguish user interrupt, submit interrupt, and shutdown. Current tests only assert direct task cancellation and leaving the queue untouched (`tests/test_ui/test_react_backend.py:111`, `tests/test_ui/test_react_backend.py:144`, `tests/test_ui/test_react_backend.py:226`).
- Backend host: after a cancellable active turn, queued turns should either resume automatically or remain paused by an explicit policy. The current implicit behavior is "pause after cancellation" (`src/openharness/ui/backend_host.py:304`).
- Query engine: cancellation after `AssistantTurnComplete` and before tool completion should leave either synthetic interrupted `ToolResultBlock`s or sanitized history before the next request.
- Query engine: parent-task cancellation during parallel tools should not bypass provider-safe tool-result handling.
- Tool abstraction: a cancellable tool such as `sleep` or `bash` should observe an interrupt context and produce/enable an interrupted result path; a blocking tool should prevent submit-interrupt cancellation while allowing the message to stay queued.
- Frontend: busy-state typing and Enter submit should be verified with Ink/component tests because `App.useInput` and `PromptInput.useInput` both observe input while busy.
- Modal interruption: permission/question modal should be cleared or marked cancelled when the active request is interrupted.

## Code Patterns

- Error-to-stream conversion is preferred for query failures: `run_query` converts provider exceptions to `ErrorEvent` (`src/openharness/engine/query.py:749`), and backend renders `ErrorEvent` as both an error event and system transcript item (`src/openharness/ui/backend_host.py:430`).
- Provider-safe tool-result conversion already exists for ordinary parallel tool failures (`src/openharness/engine/query.py:834`). Reusing this pattern for intentional cancellation would fit existing design better than letting cancellation leak after a `tool_use`.
- Restore-time safety already lives in `sanitize_conversation_messages` (`src/openharness/engine/messages.py:118`), but runtime safety probably belongs closer to `run_query` / `QueryEngine` so the next in-memory request is safe without a restart.
- Subprocess tools already use `asyncio.CancelledError` cleanup and re-raise (`src/openharness/tools/bash_tool.py:75`, `src/openharness/tools/grep_tool.py:286`), so new cancellation contracts can preserve cleanup behavior while changing how the query loop represents cancellation to the model.

## External References

- None. This pass was internal code research only. The PRD already summarizes Claude Code reference areas for later comparison.

## Related Specs

- `.trellis/spec/backend/index.md` - backend spec entry point.
- `.trellis/spec/backend/error-handling.md` - relevant guidance: convert query-engine errors to stream events or tool results.
- `.trellis/spec/backend/quality-guidelines.md` - relevant guidance: async pytest patterns, strict typing, and no bare exception handling.

## Caveats / Not Found

- No first-class interrupt/cancellation type was found in the queried backend, engine, or tool abstractions.
- No tool-level `interrupt_behavior` or equivalent policy hook was found.
- No runtime synthetic interrupted `ToolResultBlock` path was found.
- No tests were found for cancellation after assistant `tool_use` but before matching `tool_result`.
- No tests were found for frontend busy-state prompt editing/submission through Ink input events.
- `task.py current --source` reported no active task in this sub-agent session, so this file was written to the explicit task path provided by the dispatch request.
