from dataclasses import dataclass
from typing import Optional
from botman.core.tasks import Task


# Request Messages (Incoming to Bot)


@dataclass
class TaskCreateMessage:
    """Request to add a task to the bot's queue."""
    task: Task


@dataclass
class StatusRequestMessage:
    """Request to publish current status to UI."""
    pass


@dataclass
class GetStatusMessage:
    """Request to get current bot status (synchronous)."""
    pass


# Response Messages (Outgoing from Bot)


@dataclass
class GetStatusResponse:
    """Response containing bot status information."""
    name: str
    status: str
    current_task: Optional[str]
    cooldown: int
