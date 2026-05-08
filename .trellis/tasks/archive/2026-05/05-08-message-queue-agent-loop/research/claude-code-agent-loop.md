# Research: claude-code agent loop and message queue

- Query: Research sibling project `../claude-code` for message queue, query/agent loop, task/background process, and UI interaction architecture; extract implications for OpenHarness.
- Scope: internal
- Date: 2026-05-08

## Findings

### Files found

- `../claude-code/src/utils/messageQueueManager.ts` - Process-wide command queue with priority, React subscription, drain/remove helpers, and transcript logging.
- `../claude-code/src/utils/handlePromptSubmit.ts` - Normalizes direct input and queued input into one execution path; reserves the query guard before async prompt processing.
- `../claude-code/src/utils/queueProcessor.ts` - Between-turn queue drain policy for the REPL main thread.
- `../claude-code/src/hooks/useQueueProcessor.ts` - React hook that triggers queue processing when no query/local JSX UI is active.
- `../claude-code/src/screens/REPL.tsx` - TUI submit path, concurrent-query fallback, queued command execution, and subagent transcript message submission.
- `../claude-code/src/cli/print.ts` - Headless/SDK loop that drains the same queue, batches prompts, invokes `ask()`, and emits SDK events.
- `../claude-code/src/QueryEngine.ts` - Conversation-scoped wrapper around user input processing, persistence, system init, and `query()`.
- `../claude-code/src/query.ts` - Core streaming model/tool loop, recursive tool-result continuation, stop hooks, compaction, and mid-turn queued attachment drain.
- `../claude-code/src/services/tools/toolOrchestration.ts` - Tool execution scheduler that runs read-only/concurrency-safe tool batches concurrently and mutating batches serially.
- `../claude-code/src/Task.ts` - Shared task types, terminal-state helper, task context, and task ID generation.
- `../claude-code/src/tasks.ts` - Task registry mapping task types to task handlers.
- `../claude-code/src/utils/task/framework.ts` - Task registration, AppState update helper, SDK task-start events, output-delta attachment generation, and eviction support.
- `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx` - Background local-agent task state, pending messages, foreground/background transitions, and completion notification enqueueing.
- `../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx` - Background shell task state, foreground-to-background conversion, stall watchdog, and task notification enqueueing.
- `../claude-code/src/tools/AgentTool/AgentTool.tsx` - Agent tool foreground/background behavior and async completion notification wiring.
- `../claude-code/src/tools/AgentTool/runAgent.ts` - Subagent query loop wrapper with sidechain transcript persistence and cleanup.
- `../claude-code/src/tools/SendMessageTool/SendMessageTool.ts` - Inter-agent message routing to local agent pending queues or resumed agents.
- `../claude-code/src/context/QueuedMessageContext.tsx` - UI context for rendering queued messages.
- `../claude-code/src/hooks/useCommandQueue.ts` - Thin React subscription hook over the queue snapshot.
- `../claude-code/src/remote/RemoteSessionManager.ts` - Remote session WebSocket receive + HTTP send + permission control flow.
- `../claude-code/src/hooks/useMailboxBridge.ts` - Mailbox-to-submit bridge for polling incoming local mailbox messages.

### Code patterns

1. Single process-wide queue, multiple drain sites.

   `messageQueueManager.ts` keeps `commandQueue` as a module-level array, exposes a frozen snapshot for `useSyncExternalStore`, and logs every operation to transcript storage (`../claude-code/src/utils/messageQueueManager.ts:41`, `../claude-code/src/utils/messageQueueManager.ts:53`, `../claude-code/src/utils/messageQueueManager.ts:58`, `../claude-code/src/utils/messageQueueManager.ts:71`, `../claude-code/src/utils/messageQueueManager.ts:128`).

   Design implication for OpenHarness: use a small queue abstraction independent of UI state. The queue should expose push/pop/snapshot/subscription APIs so CLI, TUI, and agent code can share it without coupling to a renderer.

2. Priority is simple and explicit.

   Claude Code uses `now > next > later`; ordinary user input defaults to `next`, task notifications default to `later`, and dequeue chooses the first command at the highest priority while preserving FIFO inside the priority (`../claude-code/src/utils/messageQueueManager.ts:49`, `../claude-code/src/utils/messageQueueManager.ts:123`, `../claude-code/src/utils/messageQueueManager.ts:137`, `../claude-code/src/utils/messageQueueManager.ts:151`, `../claude-code/src/utils/messageQueueManager.ts:167`).

   Design implication for OpenHarness: avoid a complex scheduler initially. Three priorities are enough for interrupts, normal user input, and system/task notifications.

3. Direct input and queued input converge before model execution.

   `handlePromptSubmit()` converts direct input into a `QueuedCommand`, then calls `executeUserInput()` with `[cmd]`; queue-processor calls skip validation and also enter `executeUserInput()` (`../claude-code/src/utils/handlePromptSubmit.ts:148`, `../claude-code/src/utils/handlePromptSubmit.ts:356`, `../claude-code/src/utils/handlePromptSubmit.ts:368`, `../claude-code/src/utils/handlePromptSubmit.ts:389`).

   Design implication for OpenHarness: keep one "execute turn input" path. Do not duplicate direct-submit and queued-submit parsing.

4. The active query guard is reserved before async preprocessing.

   `executeUserInput()` creates a fresh abort controller, calls `queryGuard.reserve()` before `processUserInput()`, and releases the reservation in `finally` (`../claude-code/src/utils/handlePromptSubmit.ts:417`, `../claude-code/src/utils/handlePromptSubmit.ts:426`, `../claude-code/src/utils/handlePromptSubmit.ts:431`, `../claude-code/src/utils/handlePromptSubmit.ts:597`).

   Design implication for OpenHarness: mark a turn as dispatching before hook/command preprocessing starts, otherwise a second submit can race into a duplicate agent loop.

5. When busy, submit queues instead of starting a second loop.

   If `queryGuard.isActive` or external loading is true, `handlePromptSubmit()` enqueues prompt/bash commands and clears input; optional interrupt aborts the current turn if the active tool supports it (`../claude-code/src/utils/handlePromptSubmit.ts:313`, `../claude-code/src/utils/handlePromptSubmit.ts:319`, `../claude-code/src/utils/handlePromptSubmit.ts:336`).

   `REPL.onQuery()` has a second guard: if another query is already running, it extracts user-visible messages and enqueues them instead of proceeding (`../claude-code/src/screens/REPL.tsx:2866`, `../claude-code/src/screens/REPL.tsx:2870`, `../claude-code/src/screens/REPL.tsx:2876`).

   Design implication for OpenHarness: treat "queue on busy" as a core invariant, not only a UI behavior.

6. REPL drains between turns and batches safe items.

   `useQueueProcessor()` subscribes to query state and queue snapshot, then calls `processQueueIfReady()` only when no query and no blocking local UI are active (`../claude-code/src/hooks/useQueueProcessor.ts:23`, `../claude-code/src/hooks/useQueueProcessor.ts:48`, `../claude-code/src/hooks/useQueueProcessor.ts:60`).

   `queueProcessor.ts` processes slash/bash one at a time but batches non-slash items of the same mode (`../claude-code/src/utils/queueProcessor.ts:36`, `../claude-code/src/utils/queueProcessor.ts:68`, `../claude-code/src/utils/queueProcessor.ts:76`).

   Design implication for OpenHarness: implement a deterministic batching rule. Batch normal prompts if desired, but keep commands that have side effects or special parsing isolated.

7. Headless/SDK drains the same queue in its run loop.

   `print.ts` owns a `run()` function that exits early if already running, filters queue items to main-thread commands (`agentId === undefined`), drains with `dequeue()`, batches compatible prompts, emits lifecycle events, then calls `ask()` (`../claude-code/src/cli/print.ts:1865`, `../claude-code/src/cli/print.ts:1920`, `../claude-code/src/cli/print.ts:1934`, `../claude-code/src/cli/print.ts:1950`, `../claude-code/src/cli/print.ts:2006`, `../claude-code/src/cli/print.ts:2147`).

   Design implication for OpenHarness: make the queue runner reusable outside TUI. The agent-loop service should not depend on textual UI components.

8. QueryEngine is conversation state; `query.ts` is the model/tool loop.

   `QueryEngine` persists mutable conversation messages, read-file state, usage, denials, and a single abort controller across `submitMessage()` calls (`../claude-code/src/QueryEngine.ts:177`, `../claude-code/src/QueryEngine.ts:200`, `../claude-code/src/QueryEngine.ts:209`).

   `ask()` is a compatibility wrapper that constructs a `QueryEngine` and delegates to `submitMessage()` (`../claude-code/src/QueryEngine.ts:1186`, `../claude-code/src/QueryEngine.ts:1249`, `../claude-code/src/QueryEngine.ts:1287`).

   Design implication for OpenHarness: split "session/conversation engine" from "single recursive model/tool loop". The former owns persistent state; the latter should be a pure-ish async generator over events.

9. The model loop is an async generator with explicit transitions.

   `query()` yields stream starts, streamed assistant messages, tool result messages, attachments, and terminal reasons. It loops by updating a `State` object and continuing after compaction, tool execution, stop hooks, max-token recovery, or next-turn tool-result continuation (`../claude-code/src/query.ts:226`, `../claude-code/src/query.ts:659`, `../claude-code/src/query.ts:824`, `../claude-code/src/query.ts:1267`, `../claude-code/src/query.ts:1380`, `../claude-code/src/query.ts:1714`).

   Design implication for OpenHarness: model loop should emit typed events and return typed terminal reasons; avoid hidden callback-only flow.

10. Tool calls are partitioned by concurrency safety.

   Read-only/concurrency-safe tool calls run in concurrent batches; non-safe tools run serially and can mutate `ToolUseContext` after each call (`../claude-code/src/services/tools/toolOrchestration.ts:23`, `../claude-code/src/services/tools/toolOrchestration.ts:33`, `../claude-code/src/services/tools/toolOrchestration.ts:66`, `../claude-code/src/services/tools/toolOrchestration.ts:106`).

   Design implication for OpenHarness: preserve serial execution for mutating tools. Add a per-tool `is_concurrency_safe` or equivalent only when needed.

11. Mid-turn queue draining becomes model attachments, not new turns.

   After tool calls, `query.ts` snapshots queued commands at or above `next` or `later` depending on whether Sleep ran, filters slash commands, scopes by main thread vs agent, passes them to attachment generation, then removes consumed prompt/task-notification commands (`../claude-code/src/query.ts:1547`, `../claude-code/src/query.ts:1560`, `../claude-code/src/query.ts:1570`, `../claude-code/src/query.ts:1580`, `../claude-code/src/query.ts:1630`, `../claude-code/src/query.ts:1642`).

   Design implication for OpenHarness: queued messages that arrive during a tool loop can be injected into the same agent turn at a safe boundary, after tool results and before the next model request. Do not interleave regular user messages before required tool_result blocks.

12. Task system is AppState-backed with file output handles.

   `Task.ts` defines shared task status, terminal-state detection, `TaskContext`, and generated task IDs with type prefixes (`../claude-code/src/Task.ts:9`, `../claude-code/src/Task.ts:19`, `../claude-code/src/Task.ts:33`, `../claude-code/src/Task.ts:86`).

   `registerTask()` writes into AppState and emits SDK `task_started` once; `generateTaskAttachments()` reads task output deltas and returns offset patches instead of mutating stale task objects (`../claude-code/src/utils/task/framework.ts:77`, `../claude-code/src/utils/task/framework.ts:104`, `../claude-code/src/utils/task/framework.ts:158`, `../claude-code/src/utils/task/framework.ts:160`).

   Design implication for OpenHarness: store task metadata in one state map, but stream large task output through files or append-only logs with offsets.

13. Background task completion routes through the same message queue.

   Local shell and local agent completion build XML-ish task notification messages and call `enqueuePendingNotification()` (`../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:105`, `../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:160`, `../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:166`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:197`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:252`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:258`).

   Design implication for OpenHarness: background process results should re-enter the model through the queue, not by directly mutating the active loop.

14. Foreground tasks can be backgrounded without re-spawning.

   Local shell tasks can transition an existing foreground `ShellCommand` into background state and attach a result handler (`../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:293`, `../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:308`, `../claude-code/src/tasks/LocalShellTask/LocalShellTask.tsx:331`).

   Local agent tasks use a background signal promise; `backgroundAgentTask()` marks the task backgrounded and resolves the signal so `AgentTool` can detach and continue the iterator in a background closure (`../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:517`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:526`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:620`, `../claude-code/src/tools/AgentTool/AgentTool.tsx:883`, `../claude-code/src/tools/AgentTool/AgentTool.tsx:897`, `../claude-code/src/tools/AgentTool/AgentTool.tsx:925`).

   Design implication for OpenHarness: if backgrounding is needed, model it as a state transition plus ownership transfer, not as cancellation plus restart.

15. Agent-to-agent messages are queued per target agent.

   `LocalAgentTaskState` includes `pendingMessages`; `queuePendingMessage()` appends, and `drainPendingMessages()` clears atomically (`../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:135`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:162`, `../claude-code/src/tasks/LocalAgentTask/LocalAgentTask.tsx:181`).

   `SendMessageTool` resolves a target by registered name or raw agent ID; running local agents get a pending message, stopped agents are resumed in background (`../claude-code/src/tools/SendMessageTool/SendMessageTool.ts:800`, `../claude-code/src/tools/SendMessageTool/SendMessageTool.ts:807`, `../claude-code/src/tools/SendMessageTool/SendMessageTool.ts:809`, `../claude-code/src/tools/SendMessageTool/SendMessageTool.ts:823`).

   Design implication for OpenHarness: separate main prompt queue from per-agent inboxes. Per-agent inbox delivery should occur at agent loop boundaries.

16. Remote sessions separate stream receive, message send, and permission control.

   `RemoteSessionManager` receives SDK messages/control requests over WebSocket, sends user messages via HTTP POST, and tracks pending permission requests in a map (`../claude-code/src/remote/RemoteSessionManager.ts:90`, `../claude-code/src/remote/RemoteSessionManager.ts:113`, `../claude-code/src/remote/RemoteSessionManager.ts:146`, `../claude-code/src/remote/RemoteSessionManager.ts:196`, `../claude-code/src/remote/RemoteSessionManager.ts:219`, `../claude-code/src/remote/RemoteSessionManager.ts:247`).

   Design implication for OpenHarness: keep remote transport concerns outside the core loop. Use adapter callbacks that translate transport events into queue items and permission responses.

### Proposed OpenHarness architecture implications

- Introduce a backend `MessageQueue` service with typed items: `prompt`, `task_notification`, `permission_response`, and maybe `system_tick`; include `priority`, `target_agent_id`, `uuid`, `metadata`, and `created_at`.
- Keep queue storage initially in memory if OpenHarness is still single-process, but make the interface persistence-ready. Claude Code's module singleton is simple, but OpenHarness may benefit from explicit dependency injection for tests and API hosts.
- Build a single `AgentLoop.submit_or_queue()` facade: if no loop is active, reserve a guard and execute; if active, enqueue.
- Implement the active loop as an async event generator yielding typed events: `model_stream`, `tool_started`, `tool_result`, `task_started`, `task_notification`, `permission_request`, `terminal`.
- Add a safe boundary after tool results where queued notifications/messages are converted into loop attachments before the next model request.
- Model background work as `TaskState` records plus append-only output logs. Notifications should be delivered through the same queue to avoid side channels.
- Add per-agent inboxes for agent-to-agent messages. Deliver inbox messages only at tool-round/model-round boundaries.
- Avoid overbuilding scheduler semantics. Start with `now`, `next`, and `later`; add more only after real priority conflicts appear.

### External references

- None. This research used only local source under `../claude-code` and project Trellis docs.

### Related specs

- `.trellis/spec/backend/index.md` - Backend stack and quality baseline; relevant because OpenHarness is Python backend-oriented and uses file-based state patterns.

## Caveats / Not Found

- `python3 ./.trellis/scripts/task.py current --source` returned no active task in this research sub-session. The dispatch prompt provided the explicit output path `.trellis/tasks/05-08-message-queue-agent-loop/research/claude-code-agent-loop.md`, so the artifact was written there.
- `.trellis/tasks/05-08-message-queue-agent-loop/prd.md` was not present at research time; only `task.json`, `implement.jsonl`, and `check.jsonl` existed.
- I did not inspect every Claude Code task type. The representative background paths reviewed were local shell, local agent, remote session manager, SDK/headless loop, and queue drains.
- Some source files in `../claude-code` include generated/source-map content; findings cite normal source lines only.
