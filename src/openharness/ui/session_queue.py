"""Session turn queue for interactive UI runtimes."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

QueuedTurnKind = Literal["submit_line", "apply_select_command", "synthetic_followup"]
QueuedTurnPriority = Literal["now", "next", "later"]

_PRIORITY_ORDER: dict[QueuedTurnPriority, int] = {
    "now": 0,
    "next": 1,
    "later": 2,
}


@dataclass(frozen=True)
class UserSubmittedLine:
    """A user-entered line that should pass through handle_line."""

    line: str


@dataclass(frozen=True)
class SelectedCommandApplication:
    """A selected slash-command value from the React selector UI."""

    command: str
    value: str


@dataclass(frozen=True)
class SyntheticFollowup:
    """A system-generated follow-up that should enter the normal turn path."""

    message: str
    transcript_line: str | None = None


QueuedTurnPayload = UserSubmittedLine | SelectedCommandApplication | SyntheticFollowup


@dataclass(frozen=True)
class QueuedTurn:
    """One queued session turn."""

    id: str
    kind: QueuedTurnKind
    payload: QueuedTurnPayload
    priority: QueuedTurnPriority
    created_at: float
    sequence: int
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if isinstance(self.payload, UserSubmittedLine):
            return _compact_label(self.payload.line)
        if isinstance(self.payload, SelectedCommandApplication):
            command = self.payload.command.strip().lstrip("/")
            return f"/{command}" if command else "/"
        return _compact_label(self.payload.transcript_line or self.payload.message)


class SessionTurnQueue:
    """Small in-memory priority queue for session turns.

    Priority order is ``now`` -> ``next`` -> ``later`` and FIFO is preserved
    within a priority by an internal sequence number.
    """

    def __init__(self) -> None:
        self._items: list[QueuedTurn] = []
        self._sequence = itertools.count()

    def enqueue(
        self,
        *,
        kind: QueuedTurnKind,
        payload: QueuedTurnPayload,
        priority: QueuedTurnPriority = "next",
        metadata: dict[str, str] | None = None,
    ) -> QueuedTurn:
        turn = QueuedTurn(
            id=uuid4().hex,
            kind=kind,
            payload=payload,
            priority=priority,
            created_at=time.time(),
            sequence=next(self._sequence),
            metadata=dict(metadata or {}),
        )
        self._items.append(turn)
        return turn

    def dequeue(self) -> QueuedTurn | None:
        if not self._items:
            return None
        index, _ = min(
            enumerate(self._items),
            key=lambda item: (_PRIORITY_ORDER[item[1].priority], item[1].sequence),
        )
        return self._items.pop(index)

    def remove(self, turn_id: str) -> QueuedTurn | None:
        for index, turn in enumerate(self._items):
            if turn.id == turn_id:
                return self._items.pop(index)
        return None

    def snapshot(self) -> list[QueuedTurn]:
        return sorted(
            self._items,
            key=lambda turn: (_PRIORITY_ORDER[turn.priority], turn.sequence),
        )

    def empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)


def _compact_label(value: str) -> str:
    line = " ".join(value.strip().split())
    if len(line) <= 120:
        return line
    return f"{line[:117]}..."


__all__ = [
    "QueuedTurn",
    "QueuedTurnKind",
    "QueuedTurnPayload",
    "QueuedTurnPriority",
    "SelectedCommandApplication",
    "SessionTurnQueue",
    "SyntheticFollowup",
    "UserSubmittedLine",
]
