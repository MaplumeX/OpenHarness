# Design message queue and agent loop

## Goal

Design and implement a Claude Code-like session message queue for OpenHarness so user input,
synthetic task notifications, and future channel messages can enter one deterministic agent-loop
path instead of being rejected or routed through ad hoc follow-up behavior while a turn is busy.

The design should preserve the existing `QueryEngine` / `run_query` model-tool loop and add a
small controller at the UI/runtime boundary that queues work, drains it between turns, and keeps
slash-command handling, snapshots, `/continue`, permission responses, and stream events centralized.

## What I already know

* The user wants to reference the sibling `../claude-code` project for message queue and agent loop
  design.
* Research is captured in `research/claude-code-agent-loop.md` and
  `research/openharness-current-architecture.md`.
* Claude Code uses a process-level command queue with simple priorities (`now`, `next`, `later`),
  a guard that reserves the active query before async preprocessing, and multiple drain sites that
  converge on one prompt execution path.
* OpenHarness already has `QueryEngine.submit_message()` and `continue_pending()` as conversation
  entrypoints, with `run_query()` as the existing model/tool loop.
* OpenHarness React backend currently rejects `submit_line` and `apply_select_command` while busy.
* `handle_line()` already centralizes slash commands, command-triggered prompts, snapshots, and
  `/continue` behavior.
* Existing queues are specialized: React backend request queue, channels bus, swarm mailbox,
  in-process teammate queue, and background task stdin writes. There is no general main-session
  turn queue.

## Assumptions

* The first implementation targets the local React/Textual runtime path, especially
  `ReactBackendHost`, before changing remote channel policy.
* The queue should be in-memory for the MVP. Durable cross-process queue storage is out of scope
  unless a later requirement needs crash recovery.
* Permission and question responses remain out-of-band and should resolve their active futures
  immediately rather than being queued behind prompts.
* The core `run_query()` tool loop should not be rewritten in this task.

## Requirements

* Add a focused session-level queue/controller for line-like work.
* Use typed queue items rather than plain strings.
* Support at least these item kinds:
  * user-submitted line
  * selected command application
  * synthetic follow-up/task notification
* Support simple priority semantics compatible with Claude Code:
  * `now` for urgent control or explicit interrupt-style work
  * `next` for normal user input
  * `later` for background/task notifications
* Preserve FIFO order within the same priority.
* Route direct input and queued input through one execution path based on existing `handle_line()`.
* Replace busy rejection for queueable frontend requests with enqueue behavior.
* Emit protocol-visible queue state so the UI can display queued/running/completed/cancelled items.
* Keep permission response, question response, shutdown, and interrupt handling outside the normal
  queued prompt drain.
* Ensure only one active agent turn executes at a time.
* Reserve the active turn before async preprocessing starts to avoid duplicate loop races.
* Keep cancellation behavior explicit:
  * interrupt cancels the active request
  * queued items remain queued unless a dedicated clear/cancel action is added
* Add tests for queue ordering, busy enqueue behavior, drain behavior, interrupt behavior, and
  protocol event emission.

## Acceptance Criteria

* [ ] Submitting a second queueable request while a turn is active enqueues it instead of returning
  "Session is busy".
* [ ] Queued items drain automatically after the active turn completes.
* [ ] Direct and queued line execution share the same command/model handling path.
* [ ] Queue priority is deterministic and FIFO within priority.
* [ ] Permission/question responses still resolve immediately while a queued or active turn exists.
* [ ] Interrupt cancels the active turn without corrupting queued items.
* [ ] UI/backend protocol has enough events or state snapshots to render queued work.
* [ ] Existing React backend, coordinator drain, and query engine tests still pass.
* [ ] New async tests cover the queue controller and backend integration.
* [ ] Ruff and mypy pass for touched backend files.

## Definition of Done

* Tests added or updated for the behavior above.
* Lint and type-check pass.
* No new dependency unless justified by a clear need.
* Docs/spec notes updated if the implementation establishes a reusable queue pattern.
* Implementation keeps the queue controller small and avoids duplicating `QueryEngine` or
  `run_query` responsibilities.

## Out of Scope

* Rewriting `run_query()` into a new model/tool engine.
* Durable queue persistence across OpenHarness process restarts.
* Changing ohmo gateway replacement/cancel policy to queue remote messages.
* Reworking background task storage or local-agent restart semantics.
* Full per-agent inbox redesign for swarm agents.
* Adding concurrent tool scheduling changes.

## Technical Notes

* Start integration near `ReactBackendHost`, where busy rejection already exists.
* Keep `handle_line()` as the execution entrypoint to preserve slash commands, snapshots, and
  `/continue`.
* Consider a new backend module for queue types/controller instead of embedding queue policy inside
  the UI host.
* Reuse current stream event rendering rather than introducing a parallel event pipeline.
* Research files contain detailed file references and design implications:
  * `.trellis/tasks/05-08-message-queue-agent-loop/research/claude-code-agent-loop.md`
  * `.trellis/tasks/05-08-message-queue-agent-loop/research/openharness-current-architecture.md`
