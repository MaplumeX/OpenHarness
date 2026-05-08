# Interrupt Message Insertion & Queue Fate Optimization

## Goal

让 OpenHarness 在中断时的行为与 Claude Code 对齐：(1) 将中断信号作为用户消息插入对话历史（`submit_interrupt` 时跳过）；(2) 用户取消后继续 drain 队列中的剩余消息而非直接退出。

## Requirements

1. **中断消息插入**：当 `run_query()` 因 `CancelledError` 终止且原因不是 `submit_interrupt` 时，在 `QueryEngine._messages` 末尾插入一条用户消息 `[Request interrupted by user]`
2. **submit_interrupt 跳过**：当中断原因为 `submit_interrupt` 时不插入中断消息（队列中的下一条消息本身就是上下文）
3. **队列 drain 继续消费**：`user_cancel` 中断后 `_drain_turn_queue()` 不应 return，应继续处理队列中的剩余 turn
4. **shutdown 仍退出**：`shutdown` 中断时 drain 循环仍应退出（会话即将关闭）

## Acceptance Criteria

- [ ] `user_cancel` 中断后，`QueryEngine.messages` 末尾包含 `[Request interrupted by user]` 用户消息
- [ ] `shutdown` 中断后，`QueryEngine.messages` 末尾包含 `[Request interrupted by user]` 用户消息
- [ ] `submit_interrupt` 中断后，`QueryEngine.messages` 末尾不包含中断用户消息
- [ ] `user_cancel` 中断后，队列中剩余 turn 仍被依次执行
- [ ] `shutdown` 中断后，drain 循环退出
- [ ] 现有测试通过，新增覆盖以上场景的单元测试

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green

## Technical Approach

### 变更 1：中断消息插入（query_engine.py）

在 `QueryEngine.submit_message()` 的 `CancelledError` 分支中，保存消息前根据中断原因决定是否插入中断用户消息：

```python
except asyncio.CancelledError:
    self._messages = list(query_messages)
    reason = self._interrupt_state.reason or "user_cancel"
    if reason != "submit_interrupt":
        self._messages.append(
            ConversationMessage.from_user_text("[Request interrupted by user]")
        )
    raise
```

### 变更 2：队列 drain 继续消费（backend_host.py）

修改 `_drain_turn_queue()` 的中断后行为，仅在 `shutdown` 时退出：

```python
if was_cancelled and cancelled_reason == "shutdown":
    return
```

原逻辑 `if was_cancelled and cancelled_reason != "submit_interrupt": return` 改为只对 `shutdown` 退出，`user_cancel` 时继续循环。

## Decision (ADR-lite)

**Context**: 中断消息应在哪一层插入——QueryEngine 还是 BackendHost？
**Decision**: 在 QueryEngine.submit_message() 中插入，因为这是消息历史的唯一权威持有者，且 submit_interrupt 的跳过判断需要访问 interrupt_state.reason。
**Consequences**: BackendHost 的 `"Interrupted by user."` transcript 事件保持不变（前端 UI 展示用），与对话历史中的消息插入互不干扰。

## Out of Scope

* `tool_failure` 中断的消息插入行为
* Channel MessageBus 的中断消息处理
* Swarm TeammateMailbox 的中断行为修改
* 中断消息的国际化/自定义格式

## Technical Notes

* `query_engine.py:204-208` — `submit_message()` 的 `CancelledError` 分支保存消息但未插入中断用户消息
* `backend_host.py:226-241` — `_run_active_request()` 的 `CancelledError` 处理，向前端发送中断 transcript
* `backend_host.py:322-323` — `_drain_turn_queue()` 在 `user_cancel` 时 return 退出
* `query.py:642-661` — `_cancelled_error_reason()` 和 `_interrupted_tool_result()` 的定义
* `messages.py:79-81` — `ConversationMessage.from_user_text()` 可用于构造中断用户消息
