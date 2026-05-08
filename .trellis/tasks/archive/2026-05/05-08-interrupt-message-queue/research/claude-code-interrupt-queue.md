# Research: Claude Code interrupt and queued message handling

- Query: How `/Users/maplume/Code/Projects/claude-code` implements interrupt handling, busy-submit message queueing, queued command draining, tool interrupt behavior, and provider-safe interrupted tool results; identify OpenHarness adaptation points.
- Scope: mixed
- Date: 2026-05-08

## Findings

### Files Found

OpenHarness:

- `src/openharness/ui/session_queue.py` - in-memory priority/FIFO queue for interactive turns.
- `src/openharness/ui/backend_host.py` - React backend host request loop, turn drain loop, interrupt handling, queue snapshots.
- `src/openharness/ui/protocol.py` - frontend/backend request and queue snapshot schema.
- `src/openharness/engine/query.py` - model/tool loop and tool result creation.
- `src/openharness/engine/query_engine.py` - conversation state owner with `submit_message()` and `continue_pending()`.
- `src/openharness/ui/runtime.py` - line handling, `/continue`, pending tool-result summary.
- `frontend/terminal/src/App.tsx` - keyboard interrupt and busy-submit behavior.
- `frontend/terminal/src/hooks/useBackendSession.ts` - queue snapshot, busy, and `line_complete` state handling.
- `tests/test_ui/test_session_queue.py` - queue priority/FIFO tests.
- `tests/test_ui/test_react_backend.py` - backend interrupt and queue drain tests.

Claude Code:

- `/Users/maplume/Code/Projects/claude-code/src/utils/messageQueueManager.ts` - module-level unified command queue with priority, snapshots, editable pop, and queue operation logging.
- `/Users/maplume/Code/Projects/claude-code/src/hooks/useQueueProcessor.ts` and `src/utils/queueProcessor.ts` - React-side between-turn queue drain trigger and batching rules.
- `/Users/maplume/Code/Projects/claude-code/src/screens/REPL.tsx` - REPL busy-submit, query guard, interrupt, auto-restore, and queued-command processing.
- `/Users/maplume/Code/Projects/claude-code/src/utils/handlePromptSubmit.ts` - fresh abort controller per turn and query guard reservation before async processing.
- `/Users/maplume/Code/Projects/claude-code/src/query.ts` - provider-safe query loop, missing tool result generation, abort paths, and mid-turn queued attachment drain.
- `/Users/maplume/Code/Projects/claude-code/src/services/tools/StreamingToolExecutor.ts` - streaming/concurrent tool execution, synthetic errors, and per-tool interrupt behavior.
- `/Users/maplume/Code/Projects/claude-code/src/Tool.ts` - tool context and `interruptBehavior()` contract.
- `/Users/maplume/Code/Projects/claude-code/src/utils/abortController.ts` - abort controller helpers and parent-child signal propagation.
- `/Users/maplume/Code/Projects/claude-code/src/cli/print.ts` - non-React/headless queue drain and `now` priority interrupt behavior.
- `/Users/maplume/Code/Projects/claude-code/src/QueryEngine.ts` - SDK-facing engine-level `interrupt()`.

### OpenHarness Current State

OpenHarness already has a session turn queue with `now`, `next`, and `later` priorities. The queue preserves FIFO within each priority by a sequence number and exposes stable labels/snapshots (`src/openharness/ui/session_queue.py:14`, `src/openharness/ui/session_queue.py:69`, `src/openharness/ui/session_queue.py:80`, `src/openharness/ui/session_queue.py:100`, `src/openharness/ui/session_queue.py:115`).

The React backend host always enqueues submitted lines and selected command applications, then starts a single drain task if needed (`src/openharness/ui/backend_host.py:237`, `src/openharness/ui/backend_host.py:252`, `src/openharness/ui/backend_host.py:284`). The drain loop sets `_active_turn`, emits queue snapshots, runs the turn, records recent completed/cancelled state, and stops draining on cancellation so queued items remain queued (`src/openharness/ui/backend_host.py:289`, `src/openharness/ui/backend_host.py:295`, `src/openharness/ui/backend_host.py:298`, `src/openharness/ui/backend_host.py:300`, `src/openharness/ui/backend_host.py:304`).

OpenHarness interrupt currently cancels the active request task only. `_run_active_request()` catches `asyncio.CancelledError`, emits a system transcript item, status snapshot, task snapshot, and `line_complete`, then marks the turn as cancelled (`src/openharness/ui/backend_host.py:215`, `src/openharness/ui/backend_host.py:221`, `src/openharness/ui/backend_host.py:223`, `src/openharness/ui/backend_host.py:231`, `src/openharness/ui/backend_host.py:331`). The request reader handles interrupt frames immediately instead of waiting behind the request queue (`src/openharness/ui/backend_host.py:210`).

The frontend already supports busy-submit queueing and busy interruption. Ctrl+C and Esc send `interrupt` while busy (`frontend/terminal/src/App.tsx:182`, `frontend/terminal/src/App.tsx:278`), `/stop` maps to interrupt (`frontend/terminal/src/App.tsx:376`), and normal input during busy still sends `submit_line` instead of being dropped (`frontend/terminal/src/App.tsx:385`). `useBackendSession` sets busy on active queue snapshots and clears busy only on `line_complete`, not on assistant completion (`frontend/terminal/src/hooks/useBackendSession.ts:251`, `frontend/terminal/src/hooks/useBackendSession.ts:359`).

OpenHarness provider safety around normal tool execution is good for non-cancel errors: multiple tools use `asyncio.gather(..., return_exceptions=True)` and convert every exception to `ToolResultBlock`, preventing missing tool results (`src/openharness/engine/query.py:827`, `src/openharness/engine/query.py:838`, `src/openharness/engine/query.py:850`, `src/openharness/engine/query.py:864`). However, cancellation of the outer active request can still interrupt the loop before matching tool results are appended. There is no current abort token/reason passed into `run_query()` or tool execution, and no cancellation path that synthesizes missing `ToolResultBlock`s for already-emitted `ToolUseBlock`s.

OpenHarness does have pending-continuation support after max-turn stops: `QueryEngine.has_pending_continuation()` detects user `ToolResultBlock`s after assistant tool uses, `continue_pending()` resumes without appending a user message, and runtime renders a compact `/continue` hint (`src/openharness/engine/query_engine.py:132`, `src/openharness/engine/query_engine.py:192`, `src/openharness/ui/runtime.py:429`, `src/openharness/ui/runtime.py:475`). This can be reused as the model for an interrupt-safe continuation path.

Tests already lock the current queue semantics: priority/FIFO and labels (`tests/test_ui/test_session_queue.py:13`, `tests/test_ui/test_session_queue.py:45`), interrupt cancellation via stdin (`tests/test_ui/test_react_backend.py:110`), cancellation recovery and `line_complete` (`tests/test_ui/test_react_backend.py:143`), FIFO draining while active (`tests/test_ui/test_react_backend.py:182`), and interrupt leaving queued turns intact (`tests/test_ui/test_react_backend.py:225`).

### Claude Code Patterns

Claude Code uses one module-level command queue for user prompts, task notifications, and orphaned permissions. It exposes an immutable snapshot for `useSyncExternalStore`, keeps direct read APIs for non-React code, and logs enqueue/dequeue/remove operations (`src/utils/messageQueueManager.ts:41`, `src/utils/messageQueueManager.ts:53`, `src/utils/messageQueueManager.ts:58`, `src/utils/messageQueueManager.ts:71`, `src/utils/messageQueueManager.ts:90`, `src/utils/messageQueueManager.ts:128`). Priority order is `now > next > later`, with FIFO inside a priority (`src/utils/messageQueueManager.ts:49`, `src/utils/messageQueueManager.ts:151`, `src/utils/messageQueueManager.ts:167`).

The queue supports user recovery/editing: Esc/Up can pop all editable queued messages back into the prompt while leaving non-editable system notifications queued (`src/utils/messageQueueManager.ts:343`, `src/utils/messageQueueManager.ts:359`, `src/utils/messageQueueManager.ts:428`, `src/screens/REPL.tsx:2165`). This is a separate UX behavior from aborting a running task.

The REPL prevents concurrent turns with `queryGuard.tryStart()`. If a new query is attempted while one is active, it extracts user-visible messages and enqueues them instead of starting a second model loop (`src/screens/REPL.tsx:2866`, `src/screens/REPL.tsx:2870`, `src/screens/REPL.tsx:2876`, `src/screens/REPL.tsx:2877`). `handlePromptSubmit()` reserves the guard before any async input processing so concurrent submissions during command/bash preprocessing are also queued (`src/utils/handlePromptSubmit.ts:417`, `src/utils/handlePromptSubmit.ts:430`, `src/utils/handlePromptSubmit.ts:437`, `src/utils/handlePromptSubmit.ts:597`).

Queued work drains only when the query is idle and no local JSX UI blocks input. `useQueueProcessor` subscribes to both query guard and queue snapshot via `useSyncExternalStore` (`src/hooks/useQueueProcessor.ts:33`, `src/hooks/useQueueProcessor.ts:40`, `src/hooks/useQueueProcessor.ts:48`). `processQueueIfReady()` handles slash and bash commands one at a time, but batches same-mode non-slash commands (`src/utils/queueProcessor.ts:34`, `src/utils/queueProcessor.ts:68`, `src/utils/queueProcessor.ts:76`).

Claude Code distinguishes cancel reasons. Esc/user cancel calls `abortController.abort('user-cancel')`, remote cancel sends a remote interrupt, and `now` priority queued messages abort the current operation with reason `'interrupt'` (`src/screens/REPL.tsx:2106`, `src/screens/REPL.tsx:2147`, `src/screens/REPL.tsx:2150`, `src/screens/REPL.tsx:4100`). Auto-restore only applies to `user-cancel`, not programmatic `'interrupt'`, and only when no queued command exists (`src/screens/REPL.tsx:2996`, `src/screens/REPL.tsx:3010`).

For non-React/headless mode, Claude Code uses the same queue concepts: it subscribes to queue changes and aborts the current controller when a `now` command arrives (`src/cli/print.ts:1858`), then drains main-thread commands between turns, batching prompt-mode followers (`src/cli/print.ts:1930`, `src/cli/print.ts:1935`, `src/cli/print.ts:1950`).

Tool interrupt behavior is explicit. `Tool.interruptBehavior()` returns `'cancel'` or `'block'` and defaults to `'block'` if omitted (`src/Tool.ts:407`, `src/Tool.ts:416`). `StreamingToolExecutor` treats parent abort reason `'interrupt'` specially: only tools declaring `'cancel'` are cancelled; `'block'` tools should keep running and the new message waits (`src/services/tools/StreamingToolExecutor.ts:219`, `src/services/tools/StreamingToolExecutor.ts:223`, `src/services/tools/StreamingToolExecutor.ts:233`). It also reports whether all running tools are interruptible for UI state (`src/services/tools/StreamingToolExecutor.ts:254`).

Provider-safe interrupted tool results are handled in two layers. First, `query.ts` has `yieldMissingToolResultBlocks()` to synthesize an error `tool_result` for every emitted assistant `tool_use` when the stream exits before tools respond (`src/query.ts:123`, `src/query.ts:133`). Second, `StreamingToolExecutor` creates synthetic error result messages for user interruption, streaming fallback, or sibling tool error (`src/services/tools/StreamingToolExecutor.ts:153`, `src/services/tools/StreamingToolExecutor.ts:160`, `src/services/tools/StreamingToolExecutor.ts:174`, `src/services/tools/StreamingToolExecutor.ts:189`). On abort, `query.ts` consumes remaining streaming tool results specifically to avoid unpaired tool uses, then skips the extra interruption message for submit-interrupts because the queued user message provides context (`src/query.ts:1011`, `src/query.ts:1016`, `src/query.ts:1025`, `src/query.ts:1044`; mid-tool equivalent at `src/query.ts:1484`, `src/query.ts:1499`).

`AbortController` composition is first-class. Claude Code creates controllers with higher listener limits and child controllers that follow parent aborts but do not strongly retain children (`src/utils/abortController.ts:16`, `src/utils/abortController.ts:68`, `src/utils/abortController.ts:74`, `src/utils/abortController.ts:87`). `StreamingToolExecutor` gives each tool a child controller; child aborts can bubble to the query controller for user/tool-permission cancellation, while sibling errors can abort sibling tools without aborting the whole query (`src/services/tools/StreamingToolExecutor.ts:45`, `src/services/tools/StreamingToolExecutor.ts:294`, `src/services/tools/StreamingToolExecutor.ts:304`, `src/services/tools/StreamingToolExecutor.ts:312`, `src/services/tools/StreamingToolExecutor.ts:356`).

### Adaptation Guidance for OpenHarness

1. Preserve the existing `SessionTurnQueue` as the source of truth for user-visible turns. It already mirrors Claude Code's priority/FIFO model and is simpler than introducing a second module-level frontend queue.

2. Add an interrupt reason concept to the backend host rather than treating every cancellation as the same `CancelledError`. At minimum distinguish:
   - `user_cancel`: Esc/Ctrl+C or `/stop`, should stop current turn and leave queued turns intact.
   - `submit_interrupt`: urgent/`now` queued message, should avoid an extra “Interrupted by user” transcript if the next user turn immediately explains why.
   - `shutdown`: teardown, should not try to continue/drain.

3. For provider safety, avoid cancelling the query/task without giving `run_query()` a chance to close open tool-use pairs. A conservative Python adaptation is:
   - Track assistant messages/tool uses emitted in the current query iteration.
   - On cancellation, append/yield synthetic `ToolResultBlock(tool_use_id=<id>, content="Interrupted by user", is_error=True)` for every emitted tool use without a result.
   - Append the synthetic user tool-result message to conversation state before returning a cancellation event/result.
   - Tests should assert the next provider request is valid after interrupting during tool execution.

4. Introduce tool-level interrupt behavior only where needed. A Python equivalent could be an optional `interrupt_behavior()` or metadata field on tools, defaulting to `"block"` for safety. Long-running read/search/shell tools can opt into `"cancel"` later. This follows KISS/YAGNI: provider-safe results first, per-tool cancellation second.

5. For urgent busy-submit behavior, reuse the existing `priority="now"` queue. If a `now` turn is enqueued while a turn is active, cancel the active request with `submit_interrupt` semantics and keep the queued `now` turn at the front. This matches Claude Code's `now`-priority abort path without changing normal `next` queueing.

6. Keep drain behavior deterministic: cancellation should stop the drain loop after the current turn, as OpenHarness already does, unless the cancellation reason is specifically `submit_interrupt` and the product requirement is “immediately run newest message.” If immediate newest-message execution is desired, document and test that as a distinct behavior from Esc.

7. Extend tests in the same local style:
   - backend host: `now` queued turn interrupts active turn and either remains queued or drains immediately per chosen requirement;
   - query engine: interruption after assistant tool_use produces matching error tool_result blocks;
   - query engine: normal tool exception behavior remains `return_exceptions=True`;
   - frontend: busy submit continues to enqueue and busy interrupt does not clear queued turns accidentally.

### Related Specs

- `.trellis/spec/backend/index.md` - backend stack and checklist.
- `.trellis/spec/backend/error-handling.md` - query engine errors should become `ErrorEvent` or `ToolResultBlock`; tool exceptions should not escape.
- `.trellis/spec/backend/quality-guidelines.md` - async tests with `pytest.mark.asyncio`, Ruff/mypy expectations, and no bare `except`.

### External References

- Local source reference only: `/Users/maplume/Code/Projects/claude-code`.
- No internet references were needed.

## Caveats / Not Found

- `python3 ./.trellis/scripts/task.py current --source` returned no active task. The research output path was explicit in the dispatch prompt, so the file was written only to `.trellis/tasks/05-08-interrupt-message-queue/research/`.
- Claude Code is TypeScript/React/Ink and OpenHarness is Python/React terminal. The portable design is the state machine and transcript invariants, not the exact implementation.
- I did not find an OpenHarness cancellation token passed through `QueryEngine -> run_query -> tool.execute`; current interruption relies on cancelling the outer asyncio task.
- I did not find OpenHarness per-tool interrupt behavior; all tools currently run under the same outer cancellation semantics.
- I did not verify behavior with a live provider. The provider-safety recommendations are inferred from local code structure and Anthropic-style tool-use pairing requirements already encoded in both projects.
