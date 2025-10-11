from dataclasses import dataclass
from typing import Optional, List, Tuple, Any
from abc import ABC, abstractmethod

from botman.core.api import ArtifactsClient
from botman.core.models import Character
from botman.core.world import World
from botman.core.errors import BotmanError
from botman.core.services import BankService


@dataclass
class TaskContext:
    """Contextual data passed to a task during execution."""
    character: Character
    api: ArtifactsClient
    world: World
    bank: Optional[BankService] = None


@dataclass
class TaskResult:
    """The result of a single execution step of a task."""
    completed: bool
    character: Optional[Character] = None
    error: Optional[BotmanError] = None
    log_messages: Optional[List[Tuple[str, str]]] = None


class Task(ABC):
    """Abstract base class for all tasks."""
    @abstractmethod
    async def execute(self, context: TaskContext) -> "TaskResult":
        """Executes one step of the task."""
        pass

    @abstractmethod
    def progress(self) -> str:
        """Returns a string representing the task's current progress."""
        pass

    @abstractmethod
    def description(self) -> str:
        """Returns a human-readable description of the task."""
        pass