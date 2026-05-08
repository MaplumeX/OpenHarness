# Robust interrupt handling and message queue integration

## Goal

Design and implement a robust interruption model for OpenHarness interactive sessions so user interrupts, mid-turn user messages, tool execution, and the session turn queue share one coherent lifecycle. The intended behavior should be close to Claude Code: safe cancellation is propagated through model/tool execution, queued user messages are preserved and resumed, and interrupted tool turns do not leave malformed conversation state.

## What I already know

* OpenHarness currently has a React terminal turn queue under `src/openharness/ui/session_queue.py` with `now` / `next` / `later` priorities.
* `BackendHost` accepts `interrupt` requests, but interruption currently cancels the active asyncio task directly via `task.cancel()`.
* The React terminal can submit ordinary prompt input while `session.busy` is true through `PromptInput` and `App.onSubmit`; top-level busy input handling still needs explicit test coverage because `App.useInput` returns early for most keys while busy.
* The engine has recovery sanitization for trailing unmatched `tool_use` messages, but runtime interruption does not intentionally emit synthetic `tool_result` blocks for interrupted tools.
* Some tools clean up on `asyncio.CancelledError`, but the tool abstraction does not expose a cancellation token or an interrupt behavior contract.
* Claude Code uses an AbortController-style signal through query/model/tool/hook/shell layers, a global command queue with priority and subscriptions, and per-tool `interruptBehavior(): 'cancel' | 'block'`.

## Assumptions

* The first implementation should focus on the React terminal backend path and the core engine/tool abstractions rather than every legacy CLI or swarm surface.
* We should preserve current simple queue semantics where possible and add only the contracts required for correct interruption.
* Existing Python async cancellation should still be used, but behind an explicit session/query cancellation contract rather than as the only public mechanism.

## Requirements (evolving)

* Introduce a first-class cancellation/interrupt concept that can carry a reason such as user cancel, submit interrupt, shutdown, or tool failure.
* Thread cancellation state through query execution and tool execution so tools can observe interruption before and during long-running work.
* Add tool-level interrupt behavior so safe tools can be cancelled when a user submits a new message while blocking tools can continue and let the message wait.
* Allow user prompt submissions during a running turn to be queued instead of ignored.
* Ensure queue draining resumes predictably after completed, interrupted, and failed turns.
* Preserve provider-safe conversation state when a turn is interrupted after assistant `tool_use` output.
* Implement the Claude Code-style MVP: typed interrupt reasons, provider-safe synthetic tool results, tool-level interrupt behavior with safe defaults, and submit-interrupt behavior for urgent queued turns.

## Acceptance Criteria (evolving)

* [ ] Submitting input while a turn is busy queues the input and surfaces it in the queue snapshot.
* [ ] Ctrl+C/Escape interrupts the active turn without discarding unrelated queued turns unless explicitly requested.
* [ ] A cancellable long-running tool can be interrupted and returns a provider-safe synthetic tool result or equivalent cleanup.
* [ ] A blocking tool can prevent submit-interrupt cancellation while still allowing the new message to remain queued.
* [ ] Queue snapshots correctly show running, queued, completed, and cancelled turns.
* [ ] Tests cover busy-submit queueing, active interruption, queue drain continuation, and interrupted tool-result safety.

## Definition of Done

* Tests added or updated for backend queue behavior, engine interruption behavior, and at least one representative tool.
* Lint and type-check pass for touched Python and frontend code.
* Specs updated if new architectural conventions are introduced.
* Behavior is documented in task notes and reflected in protocol/types where applicable.

## Open Questions

* Confirm final PRD scope before starting implementation.

## Out of Scope (temporary)

* Remote/mobile bridge parity unless it falls out naturally from shared queue APIs.
* Full replacement of all existing task/swarm cancellation systems in the first pass.
* Persistent queue storage across process restart.

## Technical Notes

* Likely impacted OpenHarness files:
  * `src/openharness/ui/backend_host.py`
  * `src/openharness/ui/session_queue.py`
  * `src/openharness/ui/protocol.py`
  * `frontend/terminal/src/App.tsx`
  * `frontend/terminal/src/hooks/useBackendSession.ts`
  * `src/openharness/engine/query.py`
  * `src/openharness/tools/base.py`
  * representative long-running tools such as `bash_tool.py`, `grep_tool.py`, and `sleep_tool.py`
* Claude Code reference areas inspected:
  * `src/utils/abortController.ts`
  * `src/utils/messageQueueManager.ts`
  * `src/utils/queueProcessor.ts`
  * `src/utils/handlePromptSubmit.ts`
  * `src/query.ts`
  * `src/services/tools/StreamingToolExecutor.ts`
  * `src/Tool.ts`

## Research References

* [`research/claude-code-interrupt-queue.md`](research/claude-code-interrupt-queue.md) — Claude Code uses AbortController-style cancellation, priority command queues, per-tool interrupt policy, and synthetic interrupted tool results.
* [`research/openharness-current-gaps.md`](research/openharness-current-gaps.md) — OpenHarness already has turn queueing and busy-submit support, but lacks first-class interrupt reasons, tool policy, cancellation tokens, runtime synthetic tool results, and modal/drain edge handling.

## Research Notes

### What Claude Code does that is portable

* Treats interruption as a typed reason, not only task cancellation (`user-cancel`, `interrupt`, shutdown-like paths).
* Uses queue priority to decide whether a new prompt waits or interrupts.
* Lets each tool declare whether submit-interrupt can cancel it or must wait.
* Ensures assistant `tool_use` blocks always receive matching tool results, including interrupted/error synthetic results.

### Constraints from OpenHarness

* The existing `SessionTurnQueue` is already the right place for user-visible turn state; adding a second global queue would be unnecessary.
* The current backend test suite already expects user interrupt to leave queued turns intact, so any auto-resume behavior after cancellation must be an explicit policy change.
* Python `asyncio.CancelledError` cleanup is already important for subprocess tools; new cancellation handling must preserve subprocess cleanup while preventing malformed conversation history.
* Runtime safety should happen before the next in-memory request, not only at restore time via `sanitize_conversation_messages`.

## Feasible Approaches

### Approach A: Provider-safe cancellation first

Implement typed interrupt reasons and runtime-safe cancellation in the engine/tool loop. On interruption after assistant tool use, synthesize interrupted `ToolResultBlock`s before returning. Keep existing queue behavior mostly unchanged: normal queued turns wait, user cancel leaves queue intact, no broad tool policy yet.

Pros: smallest reliable core; directly fixes the highest-risk malformed conversation bug; easier to test.
Cons: does not yet provide Claude Code-like submit-interrupt semantics for cancellable tools.

### Approach B: Claude Code-style MVP (recommended)

Implement typed interrupt reasons, provider-safe synthetic tool results, tool-level `interrupt_behavior` with default `block`, and submit-interrupt behavior for `priority="now"` queued turns. Normal busy submits remain queued; urgent submits can interrupt cancellable tools and run next. Existing user cancel behavior still leaves unrelated queued turns intact.

Pros: addresses the full product gap without replacing the queue architecture; preserves safety defaults; maps cleanly to Claude Code's proven design.
Cons: touches more layers and needs broader tests across backend host, query engine, tools, and frontend protocol.

### Approach C: Full parity including swarm/remote surfaces

Extend Approach B across React terminal, headless/CLI paths, swarm in-process agents, remote bridges, permission/modal queues, and agent message queues.

Pros: most complete architecture; fewer divergent cancellation paths long term.
Cons: large scope and higher regression risk; likely better as follow-up tasks after core semantics are stable.

## Decision (ADR-lite)

**Context**: OpenHarness already has a session turn queue and busy-submit path, but interruption is implemented as direct task cancellation. This leaves cancellation reasons implicit, does not give tools a policy for submit-interrupt behavior, and can leave assistant `tool_use` blocks without matching `tool_result` blocks if interruption lands mid-tool.

**Decision**: Use Approach B, the Claude Code-style MVP. Implement typed interrupt reasons, runtime provider-safe synthetic interrupted tool results, a default-blocking tool interrupt policy, and an urgent submit-interrupt path using queue priority. Keep full swarm/remote/headless parity out of the first implementation unless shared code naturally covers it.

**Consequences**: This touches backend host, engine, tools, protocol/frontend tests, and representative tool behavior. It avoids a broad queue rewrite and preserves safe defaults, but requires careful tests around cancellation timing and queue drain policy.

## Proposed Implementation Plan

### PR1: Cancellation contracts and provider safety

* Add a small typed interrupt/cancellation model with reason values such as `user_cancel`, `submit_interrupt`, and `shutdown`.
* Thread the cancellation context through `QueryEngine`, `run_query`, and `ToolExecutionContext`.
* Add runtime handling that creates synthetic interrupted `ToolResultBlock`s for emitted assistant tool uses that have no matching result.
* Add engine tests for cancellation after assistant `tool_use`, including parallel tools.

### PR2: Queue and backend host policy

* Teach backend host to distinguish interrupt reasons instead of directly treating every cancellation the same.
* Preserve current user-cancel behavior where unrelated queued turns remain queued.
* Add an explicit submit-interrupt path for urgent queued turns.
* Ensure queue drain state is deterministic after completed, cancelled, and submit-interrupted turns.
* Add backend tests for busy submit snapshots, user cancel, submit interrupt, and queue drain policy.

### PR3: Tool policy and representative tools

* Add `BaseTool.interrupt_behavior()` or equivalent metadata with default `block`.
* Mark safe long-running tools such as `sleep` and selected read/search tools as `cancel`; keep mutating or shell-like tools conservative unless behavior is proven safe.
* Preserve subprocess cleanup on cancellation.
* Add tests for cancellable and blocking tool behavior.

### PR4: Frontend/protocol cleanup

* Extend queue/protocol state only if needed for interrupt reason or blocked state.
* Test busy-state prompt submit behavior through the React terminal path.
* Clear or mark permission/question modal state on active-turn interruption.

## Final Requirements Summary

* The first implementation targets the React terminal session path plus shared engine/tool contracts required by that path.
* Normal busy submissions remain queued and visible in queue snapshots.
* Urgent queued turns can request submit-interrupt; only tools that declare cancellable behavior may be interrupted by that path.
* User cancel (`Ctrl+C`, Escape, `/stop`) interrupts the active turn and preserves unrelated queued turns.
* Shutdown is distinguishable from user cancel and submit-interrupt.
* Interrupted assistant tool uses must be paired with synthetic error tool results before the next provider request.
* Tool interrupt behavior defaults to blocking for safety; tools opt into cancellation intentionally.
* Tests must cover backend queue behavior, query provider-safety, cancellable vs blocking tool policy, and frontend busy-submit behavior.
