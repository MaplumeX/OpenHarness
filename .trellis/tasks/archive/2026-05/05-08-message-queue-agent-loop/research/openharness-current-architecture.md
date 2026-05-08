# Research: OpenHarness current message queue and agent loop architecture

- Query: Existing message queue, QueryEngine/run_query agent loop, background task, swarm, UI backend host, and channel/bus integration points relevant to designing a Claude Code-like message queue plus agent loop.
- Scope: internal
- Date: 2026-05-08

## Findings

### Files found

- `.trellis/workflow.md` - Trellis workflow requires research artifacts to be persisted under task `research/`.
- `.trellis/spec/backend/index.md` - Backend guideline index; Python 3.11 target, Pydantic v2, pytest-asyncio, Ruff, strict mypy.
- `.trellis/spec/backend/directory-structure.md` - Module layout; `engine/`, `ui/`, `tasks/`, `swarm/`, and `channels/` are the relevant backend areas.
- `.trellis/spec/backend/error-handling.md` - Query-engine errors should be converted to stream events or tool results.
- `.trellis/spec/backend/logging-guidelines.md` - Use stdlib logging and `%s`-style formatting; avoid logging prompts/responses or secrets.
- `.trellis/spec/backend/quality-guidelines.md` - Async behavior needs pytest coverage; new public APIs need type annotations.
- `src/openharness/engine/query.py` - Core tool-aware model loop and tool execution.
- `src/openharness/engine/query_engine.py` - Conversation-owning wrapper around `run_query`.
- `src/openharness/ui/runtime.py` - Shared runtime assembly and `handle_line` command/model entrypoint.
- `src/openharness/ui/backend_host.py` - React TUI stdin/stdout host, request queue, busy flag, interrupt handling, event rendering.
- `src/openharness/ui/protocol.py` - Frontend request and backend event schema.
- `src/openharness/tasks/manager.py` - Background subprocess task manager, stdin writes, task restart behavior, completion listeners.
- `src/openharness/tasks/types.py` - Runtime task records and statuses.
- `src/openharness/tools/agent_tool.py` - Tool that spawns background/subagent tasks.
- `src/openharness/tools/send_message_tool.py` - Tool that sends follow-up messages to background/swarm agents.
- `src/openharness/tools/task_list_tool.py` - Tool for listing background tasks.
- `src/openharness/tools/task_output_tool.py` - Tool for reading background task output.
- `src/openharness/ui/coordinator_drain.py` - Coordinator-mode waiter that turns completed background tasks into follow-up user messages.
- `src/openharness/channels/bus/events.py` - Chat inbound/outbound dataclasses and `session_key`.
- `src/openharness/channels/bus/queue.py` - Simple in-memory inbound/outbound `asyncio.Queue` bus.
- `src/openharness/channels/adapter.py` - Generic channel bus to `QueryEngine.submit_message()` bridge.
- `ohmo/gateway/bridge.py` - More advanced per-session channel bridge with replacement/cancel semantics and progress/final outbound events.
- `ohmo/gateway/runtime.py` - Channel runtime pool that reuses `RuntimeBundle` per session and streams `QueryEngine` events.
- `src/openharness/swarm/in_process.py` - In-process teammate loop with `ContextVar`, abort controller, mailbox drain, and per-agent message queue.
- `src/openharness/swarm/mailbox.py` - File-based agent inbox with atomic JSON file writes and read markers.
- `src/openharness/swarm/subprocess_backend.py` - Swarm subprocess backend layered on `BackgroundTaskManager`.
- `tests/test_swarm/test_in_process.py` - Existing tests for in-process spawn, shutdown, send_message, and mailbox writes.
- `tests/test_tools/test_task_tools.py` - Regression tests requiring `AgentTool` and `send_message` to use subprocess-backed task IDs.
- `tests/test_tools/test_integration_flows.py` - Integration test for completed local agent restart on follow-up message.
- `tests/test_ui/test_react_backend.py` - Tests for backend host request reading, interrupt, and cancel recovery.
- `tests/test_ohmo/test_gateway.py` - Tests for gateway progress updates, logging, `/stop`, and `/restart`.

### Current agent loop behavior

`QueryEngine` owns in-memory conversation history, appends each submitted user message, executes `USER_PROMPT_SUBMIT` hooks, builds a `QueryContext`, then delegates to `run_query` (`src/openharness/engine/query_engine.py:147`). It updates stored conversation history only when `AssistantTurnComplete` is seen (`src/openharness/engine/query_engine.py:185`). `continue_pending()` can resume an interrupted tool loop without adding a new user message (`src/openharness/engine/query_engine.py:192`).

`run_query` loops until no tool calls remain or `max_turns` is exceeded (`src/openharness/engine/query.py:632`, `src/openharness/engine/query.py:698`). It streams model text as `AssistantTextDelta`, appends the final assistant message, yields `AssistantTurnComplete`, and returns when no tool calls remain (`src/openharness/engine/query.py:724`, `src/openharness/engine/query.py:796`, `src/openharness/engine/query.py:802`). Single tools run sequentially; multiple tools run concurrently with `asyncio.gather(..., return_exceptions=True)` so every tool_use gets a tool_result (`src/openharness/engine/query.py:815`, `src/openharness/engine/query.py:827`, `src/openharness/engine/query.py:838`). Tool execution does hook checks, permission checks, output offloading, and carryover metadata recording (`src/openharness/engine/query.py:871`).

Design implication: a Claude Code-like loop should not fork a second model/tool execution engine. The durable queue runner should feed prompts into `QueryEngine.submit_message()` / `continue_pending()` and render the existing `StreamEvent` types. Any new cancellation or queue semantics should wrap the current loop, not duplicate tool execution.

### UI host and request queue behavior

`ReactBackendHost` already has an inbound `_request_queue: asyncio.Queue[FrontendRequest]`, permission/question future maps, `_busy`, and `_active_request_task` (`src/openharness/ui/backend_host.py:74`). `run()` reads one queued request at a time; when busy it rejects `submit_line` and `apply_select_command` with `"Session is busy"` (`src/openharness/ui/backend_host.py:140`, `src/openharness/ui/backend_host.py:160`). `_read_requests()` resolves permission/question responses directly, handles interrupt immediately, and queues all other requests (`src/openharness/ui/backend_host.py:182`). `_run_active_request()` wraps processing in a task and emits transcript/status/tasks/line_complete when cancelled (`src/openharness/ui/backend_host.py:211`). `_process_line()` renders stream events to backend protocol events, delegates to `handle_line()`, optionally drains coordinator async agents, then emits status/task snapshots and `line_complete` (`src/openharness/ui/backend_host.py:237`, `src/openharness/ui/backend_host.py:345`, `src/openharness/ui/backend_host.py:352`, `src/openharness/ui/backend_host.py:359`).

Design implication: this is the narrowest integration point for user-facing queue semantics. Replacing `_busy` rejection with a real session turn queue is likely lower risk than changing `QueryEngine` first. The queue needs protocol-visible states so the frontend can show queued/running/cancelled messages, not just the current `line_complete` event.

### Runtime entrypoint behavior

`build_runtime()` creates the `QueryEngine`, hook executor, tool registry, app state, session id, and tool metadata buckets (`src/openharness/ui/runtime.py:199`, `src/openharness/ui/runtime.py:321`). `handle_line()` parses slash commands first, then either renders command output, submits command prompts through `engine.submit_message()`, continues pending loops through `engine.continue_pending()`, or processes normal prompts (`src/openharness/ui/runtime.py:522`, `src/openharness/ui/runtime.py:536`, `src/openharness/ui/runtime.py:560`, `src/openharness/ui/runtime.py:595`). `/continue` is implemented as a command result with `continue_pending=True` (`src/openharness/commands/registry.py:953`).

Design implication: queued work should probably store a normalized "line request" plus enough render context, then call `handle_line()` in order. That keeps slash commands, prompt submission, snapshot saves, and `continue_pending` behavior centralized.

### Background agent task behavior

`BackgroundTaskManager` stores in-memory task records, subprocess handles, waiters, locks, generation counters, and completion listeners (`src/openharness/tasks/manager.py:50`). `create_agent_task()` starts a shell subprocess, records the prompt, and writes the prompt to stdin (`src/openharness/tasks/manager.py:91`). `write_to_task()` serializes payloads as one JSON/plain line, writes to stdin, and auto-restarts completed agent tasks when needed (`src/openharness/tasks/manager.py:181`, `src/openharness/tasks/manager.py:287`). Restart explicitly notes that prior interactive context was not preserved (`src/openharness/tasks/manager.py:21`, `src/openharness/tasks/manager.py:295`). Task records are runtime-only dataclasses with `local_bash`, `local_agent`, `remote_agent`, and `in_process_teammate` types (`src/openharness/tasks/types.py:10`).

`AgentTool` intentionally uses the `subprocess` backend so returned task IDs are pollable by task tools (`src/openharness/tools/agent_tool.py:61`). `SendMessageTool` routes `name@team` to the subprocess backend and plain task IDs to `BackgroundTaskManager.write_to_task()` (`src/openharness/tools/send_message_tool.py:31`). Regression tests lock this in: `AgentTool` must not return unpollable `in_process_...` IDs (`tests/test_tools/test_task_tools.py:102`) and swarm send_message must call `SubprocessBackend.send_message` (`tests/test_tools/test_task_tools.py:161`). Integration tests also expect follow-up after a completed agent to restart and append output (`tests/test_tools/test_integration_flows.py:145`).

Design implication: background tasks are not the right primitive for a primary interactive message queue if context continuity is required. They are useful for worker/subagent work and for a "queued background worker" style, but current restart semantics explicitly discard process-local interactive state.

### Coordinator async-agent behavior

When tools spawn async agents, `run_query` stores metadata in `async_agent_tasks` (`src/openharness/engine/query.py:340`). `drain_coordinator_async_agents()` polls pending task entries until terminal status, formats `<task-notification>` payloads, and submits them back through `engine.submit_message()` as follow-up user messages (`src/openharness/ui/coordinator_drain.py:159`, `src/openharness/ui/coordinator_drain.py:186`, `src/openharness/ui/coordinator_drain.py:192`). This runs after `_process_line()` in the React backend and after print-mode prompt handling (`src/openharness/ui/backend_host.py:352`, `src/openharness/ui/app.py:300`).

Design implication: this is an existing "system-generated queued follow-up" pattern. A generalized session queue can borrow the idea of follow-up user messages, but should avoid blocking the main UI indefinitely unless that is an explicit mode.

### Channels bus and gateway behavior

The generic `MessageBus` is a minimal in-memory pair of `asyncio.Queue` objects with publish/consume helpers and queue-size properties (`src/openharness/channels/bus/queue.py:8`). `InboundMessage` carries channel, sender, chat, content, media, metadata, and optional session key override (`src/openharness/channels/bus/events.py:8`). `ChannelBridge` consumes inbound messages with a 1s timeout, calls `QueryEngine.submit_message(msg.content)`, accumulates only assistant deltas, and publishes one final outbound message (`src/openharness/channels/adapter.py:78`, `src/openharness/channels/adapter.py:94`, `src/openharness/channels/adapter.py:119`). It does not use `InboundMessage.session_key` to select per-chat engine state beyond outbound metadata.

`OhmoGatewayBridge` is more complete: it keeps a task per `session_key`, logs inbound/final events, handles `/stop` and `/restart`, cancels an in-flight task for the same session when a newer user message arrives, publishes replacement progress, streams progress/tool/final outbound updates, and cleans task maps on completion (`ohmo/gateway/bridge.py:67`, `ohmo/gateway/bridge.py:70`, `ohmo/gateway/bridge.py:89`, `ohmo/gateway/bridge.py:95`, `ohmo/gateway/bridge.py:171`, `ohmo/gateway/bridge.py:243`). Tests cover progress updates, logging, stop cancellation, and restart dispatch (`tests/test_ohmo/test_gateway.py:891`, `tests/test_ohmo/test_gateway.py:927`, `tests/test_ohmo/test_gateway.py:957`, `tests/test_ohmo/test_gateway.py:995`).

`OhmoSessionRuntimePool.stream_message()` reuses a `RuntimeBundle` by session key, parses slash commands, streams command results or engine messages, supports `continue_pending`, saves snapshots, and converts `StreamEvent` objects into channel progress/final updates (`ohmo/gateway/runtime.py:162`, `ohmo/gateway/runtime.py:176`, `ohmo/gateway/runtime.py:230`, `ohmo/gateway/runtime.py:276`, `ohmo/gateway/runtime.py:314`, `ohmo/gateway/runtime.py:337`, `ohmo/gateway/runtime.py:388`).

Design implication: the ohmo gateway already has a session-keyed "active task per conversation" controller. It currently replaces/cancels older work instead of queueing. For Claude Code-like semantics, this is the closest existing pattern for remote channels: change replacement behavior to enqueue/interrupt based on policy.

### Swarm in-process behavior

`InProcessBackend` has the most direct "message queue plus loop" shape. `TeammateContext` includes an `asyncio.Queue[TeammateMessage]` with a comment that queued leader messages are injected between query iterations (`src/openharness/swarm/in_process.py:144`). `start_in_process_teammate()` binds a `ContextVar`, runs `_run_query_loop()` if a `QueryContext` is supplied, otherwise runs a stub, and writes idle notification on exit (`src/openharness/swarm/in_process.py:196`, `src/openharness/swarm/in_process.py:252`, `src/openharness/swarm/in_process.py:277`). `_drain_mailbox()` reads unread file-based messages, handles shutdown immediately, and puts `user_message` payloads into `ctx.message_queue` (`src/openharness/swarm/in_process.py:295`, `src/openharness/swarm/in_process.py:320`). `_run_query_loop()` drains mailbox and `message_queue` during `run_query()` event iteration, appending queued text as new user messages (`src/openharness/swarm/in_process.py:335`, `src/openharness/swarm/in_process.py:357`, `src/openharness/swarm/in_process.py:377`, `src/openharness/swarm/in_process.py:382`). `send_message()` writes to the file mailbox, but the direct low-latency queue path described in the docstring is not actually implemented because it cannot access another task's `ContextVar` from `_active` entries (`src/openharness/swarm/in_process.py:494`).

Design implication: this implementation is useful as a reference, but not directly reusable as-is. A robust main-session queue should keep queue state in an explicit controller object, not inside task-local `ContextVar`, so producers can enqueue messages without relying on cross-task context access.

### File-based mailbox behavior

`TeammateMailbox` writes each message as a JSON file under `~/.openharness/teams/<team>/agents/<agent_id>/inbox`, using a temp file plus `os.replace()` under an exclusive lock (`src/openharness/swarm/mailbox.py:1`, `src/openharness/swarm/mailbox.py:126`). Reads sort message files and skip corrupted entries; `mark_read()` updates JSON under lock (`src/openharness/swarm/mailbox.py:153`, `src/openharness/swarm/mailbox.py:183`). Factory helpers create `user_message`, `shutdown`, and `idle_notification` messages (`src/openharness/swarm/mailbox.py:253`, `src/openharness/swarm/mailbox.py:258`, `src/openharness/swarm/mailbox.py:263`).

Design implication: file mailbox is appropriate for inter-process durability and remote/subprocess agents. For in-process React TUI turn queueing, an `asyncio.Queue` plus session snapshot integration is simpler. If crash recovery or cross-process enqueue is required, reuse mailbox-style atomic file writes rather than inventing ad hoc append logs.

## Design implications for a Claude Code-like queue

1. Introduce a small session-level queue/controller at the UI/runtime boundary rather than changing the core model loop first.
2. Queue items should be typed: user submit line, command apply, synthetic follow-up, interrupt/stop, possibly remote channel message. This avoids bolting special cases onto plain strings.
3. Preserve `handle_line()` as the execution entrypoint so slash commands, snapshots, command-triggered prompts, and `continue_pending()` stay consistent.
4. Replace `_busy` rejection in `ReactBackendHost` with enqueue + protocol events, but keep permission/question responses out-of-band as they are today.
5. Cancellation policy should be explicit per surface:
   - React TUI: interrupt active turn; queued items may remain or be cancelled depending on user action.
   - ohmo channels: current behavior replaces an active session message; queueing would be a deliberate policy change.
   - coordinator workers: continue using background task completion notifications.
6. Avoid using `BackgroundTaskManager` for the primary interactive queue when conversation continuity is required; its local-agent restart path says context is not preserved.
7. If new persistent queue state is needed, model it as a file-based service under `services/` or a focused `queue/` module, following existing `swarm/mailbox.py` atomic write patterns.
8. Tests should be added near `tests/test_ui/test_react_backend.py` for queue order, busy replacement, interrupt behavior, and protocol events; near `tests/test_ohmo/test_gateway.py` if channel policy changes; and near `tests/test_swarm/test_in_process.py` only if in-process teammate messaging changes.

## External References

- None. This research used repository-local code and specs only.

## Related Specs

- `.trellis/spec/backend/index.md` - backend pre-development index and quality overview.
- `.trellis/spec/backend/directory-structure.md:71` - module organization and examples for complex domains.
- `.trellis/spec/backend/error-handling.md:73` - query-engine errors should become stream events/tool results.
- `.trellis/spec/backend/logging-guidelines.md:46` - `%s` logging format requirement.
- `.trellis/spec/backend/logging-guidelines.md:80` - do not log secrets, prompts, responses, or PII.
- `.trellis/spec/backend/quality-guidelines.md:29` - type hints, Pydantic validation, async test expectations.

## Caveats / Not Found

- `task.py current --source` returned no active task in this sub-agent session. The caller provided the explicit output path `.trellis/tasks/05-08-message-queue-agent-loop/research/openharness-current-architecture.md`, so this artifact was written there.
- No general-purpose durable "main session message queue" module exists today. Existing queues are specialized: channel bus, swarm mailbox, in-process teammate queue, React backend request queue, and background task stdin writes.
- The generic `ChannelBridge` does not preserve per-session `QueryEngine` state; ohmo gateway runtime pool does.
- `InProcessBackend.send_message()` writes to the mailbox only. Despite comments, it does not directly push into the target task's in-memory `ctx.message_queue`.
- Background task records are in-memory and task output is file-backed; this is not a durable job queue across process restarts.
