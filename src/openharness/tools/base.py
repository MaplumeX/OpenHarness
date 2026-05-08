"""Tool abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from openharness.hooks.executor import HookExecutor

InterruptReason = Literal["user_cancel", "submit_interrupt", "shutdown", "tool_failure"]
ToolInterruptBehavior = Literal["cancel", "block"]


@dataclass
class InterruptState:
    """Shared cancellation state for one active query."""

    reason: InterruptReason | None = None
    running_tool_behaviors: set[ToolInterruptBehavior] = field(default_factory=set)

    @property
    def requested(self) -> bool:
        """Return whether cancellation has been requested."""
        return self.reason is not None

    def request(self, reason: InterruptReason) -> None:
        """Mark the query as interrupted with a typed reason."""
        self.reason = reason

    def clear(self) -> None:
        """Reset interruption and active tool policy state."""
        self.reason = None
        self.running_tool_behaviors.clear()

    def set_running_tool_behaviors(self, behaviors: set[ToolInterruptBehavior]) -> None:
        """Record the interrupt policy of currently executing tools."""
        self.running_tool_behaviors = set(behaviors)

    def clear_running_tool_behaviors(self) -> None:
        """Clear active tool policy state."""
        self.running_tool_behaviors.clear()

    def all_running_tools_interruptible(self) -> bool:
        """Return True when submit-interrupt may cancel the current tool phase."""
        return "block" not in self.running_tool_behaviors

    def raise_if_requested(self) -> None:
        """Cooperative cancellation checkpoint for tools and query orchestration."""
        if self.reason is not None:
            raise asyncio.CancelledError(self.reason)


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""

    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    hook_executor: HookExecutor | None = None
    interrupt_state: InterruptState = field(default_factory=InterruptState)


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all OpenHarness tools."""

    name: str
    description: str
    input_model: type[BaseModel]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def interrupt_behavior(self) -> ToolInterruptBehavior:
        """Return whether submit-interrupt may cancel this tool."""
        return "block"

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema expected by the Anthropic Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def to_api_schema(self) -> list[dict[str, Any]]:
        """Return all tool schemas in API format."""
        return [tool.to_api_schema() for tool in self._tools.values()]
