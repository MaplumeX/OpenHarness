"""Sleep tool."""

from __future__ import annotations

import asyncio
from typing import cast

from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolInterruptBehavior, ToolResult


class SleepToolInput(BaseModel):
    """Arguments for sleep."""

    seconds: float = Field(default=1.0, ge=0.0, le=30.0)


class SleepTool(BaseTool):
    """Pause execution briefly."""

    name = "sleep"
    description = "Sleep for a short duration."
    input_model = SleepToolInput

    def is_read_only(self, arguments: BaseModel) -> bool:
        del arguments
        return True

    def interrupt_behavior(self) -> ToolInterruptBehavior:
        """Allow urgent queued turns to cancel this read-only wait."""
        return "cancel"

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        parsed = cast(SleepToolInput, arguments)
        interrupt_state = getattr(context, "interrupt_state", None)
        if interrupt_state is not None:
            interrupt_state.raise_if_requested()
        await asyncio.sleep(parsed.seconds)
        if interrupt_state is not None:
            interrupt_state.raise_if_requested()
        return ToolResult(output=f"Slept for {parsed.seconds} seconds")
