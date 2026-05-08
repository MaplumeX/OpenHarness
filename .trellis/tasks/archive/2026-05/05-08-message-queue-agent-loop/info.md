# Technical design: session queue plus agent loop

## Design shape

OpenHarness should use a small session-turn controller around the current runtime path:

```text
Frontend / channel adapter
  -> SessionTurnQueue.enqueue(...)
  -> SessionTurnRunner.drain()
  -> handle_line(...)
  -> QueryEngine.submit_message(...) / continue_pending()
  -> run_query(...)
  -> existing stream event rendering
```

The queue owns ordering and active-turn state. `QueryEngine` continues to own conversation history,
tool metadata, hooks, and model/tool loop execution.

## Proposed modules

`src/openharness/ui/session_queue.py`

* `QueuedTurnKind`: string enum or literal union for `submit_line`, `apply_select_command`,
  `synthetic_followup`.
* `QueuedTurnPriority`: `now`, `next`, `later`.
* `QueuedTurn`: frozen dataclass or Pydantic model with `id`, `kind`, `payload`, `priority`,
  `created_at`, and optional `metadata`.
* `SessionTurnQueue`: small in-memory queue with `enqueue`, `dequeue`, `remove`, `snapshot`,
  `empty`, and priority/FIFO behavior.

`ReactBackendHost`

* Keep `_request_queue` for raw frontend protocol requests.
* Add a session turn queue for queueable work.
* Continue resolving permission/question responses directly in `_read_requests()`.
* Convert queueable requests into `QueuedTurn` instances when the host is busy.
* Drain queued turns after each active turn finishes.
* Emit queue snapshots or queue lifecycle events through `BackendEvent`.

`src/openharness/ui/protocol.py`

* Add queue-visible event/state types only as needed by the React UI.
* Prefer a compact queue snapshot over a large event taxonomy for the MVP.

## Queue policy

Priority order is `now`, then `next`, then `later`; order is FIFO within a priority.

Normal user input should default to `next`. Synthetic background notifications should default to
`later`. `now` should be reserved for future urgent control work and should not be overused.

The runner must hold one active-turn reservation before calling async preprocessing or
`handle_line()`. This mirrors Claude Code's query guard and prevents a second submit from racing
into another active model loop.

## Execution policy

The runner should execute one queued turn at a time through the same method used for direct turns.
For the first implementation, avoid batching multiple prompts into one model request. Batching can
be added later after real UX pressure exists.

Queue draining should happen at a safe boundary:

1. active `handle_line()` call completes or is cancelled
2. host emits status/transcript/task updates and line completion for that turn
3. runner schedules the next queued turn, if any

This keeps OpenHarness compatible with provider message ordering rules, especially tool-result
messages that must follow tool-use messages.

## Cancellation policy

Interrupt cancels only the currently active turn. Queued turns remain in the queue. A later UI
action can add explicit queued-turn removal or clear-all behavior if needed.

Shutdown should stop active processing and prevent further drains.

## Testing plan

* Unit-test `SessionTurnQueue` priority ordering, FIFO behavior, remove behavior, and snapshots.
* Extend React backend tests to cover:
  * busy submit enqueues instead of rejecting
  * queued turns drain after the active turn
  * permission/question responses resolve immediately while queue is non-empty
  * interrupt cancels the active request and leaves queued items intact
  * backend emits queue-visible state
* Keep existing tests around coordinator drain, `AgentTool`, `send_message`, and ohmo gateway green.

## Non-goals

Do not use `BackgroundTaskManager` as the main interactive queue. Its completed local-agent restart
path intentionally does not preserve process-local interactive context.

Do not move queue state into a task-local `ContextVar`; producers outside the task need explicit
access to enqueue work.

Do not add durable file persistence yet. If that becomes necessary, reuse the atomic-write style
from `swarm/mailbox.py`.
