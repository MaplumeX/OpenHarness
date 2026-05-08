"""Tests for the interactive session turn queue."""

from __future__ import annotations

from openharness.ui.session_queue import (
    SelectedCommandApplication,
    SessionTurnQueue,
    SyntheticFollowup,
    UserSubmittedLine,
)


def test_session_turn_queue_priority_order_and_fifo() -> None:
    queue = SessionTurnQueue()

    later = queue.enqueue(
        kind="synthetic_followup",
        payload=SyntheticFollowup(message="background"),
        priority="later",
    )
    next_a = queue.enqueue(
        kind="submit_line",
        payload=UserSubmittedLine(line="first"),
        priority="next",
    )
    now = queue.enqueue(
        kind="submit_line",
        payload=UserSubmittedLine(line="urgent"),
        priority="now",
    )
    next_b = queue.enqueue(
        kind="apply_select_command",
        payload=SelectedCommandApplication(command="theme", value="default"),
        priority="next",
    )

    assert [turn.id for turn in queue.snapshot()] == [now.id, next_a.id, next_b.id, later.id]
    assert queue.dequeue() == now
    assert queue.dequeue() == next_a
    assert queue.dequeue() == next_b
    assert queue.dequeue() == later
    assert queue.dequeue() is None


def test_session_turn_queue_remove_and_labels() -> None:
    queue = SessionTurnQueue()
    removed = queue.enqueue(
        kind="submit_line",
        payload=UserSubmittedLine(line="remove me"),
    )
    kept = queue.enqueue(
        kind="apply_select_command",
        payload=SelectedCommandApplication(command="/provider", value="claude-api"),
    )

    assert queue.remove(removed.id) == removed
    assert queue.remove("missing") is None
    assert len(queue) == 1
    assert queue.snapshot()[0].label == "/provider"
    assert queue.dequeue() == kept
    assert queue.empty()


def test_session_turn_queue_compacts_long_labels() -> None:
    queue = SessionTurnQueue()
    turn = queue.enqueue(
        kind="synthetic_followup",
        payload=SyntheticFollowup(message="word " * 60),
        priority="later",
    )

    assert len(turn.label) == 120
    assert turn.label.endswith("...")
