from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod

from api import ArtifactsClient
from models import Character


@dataclass
class TaskContext:
    """Context passed to tasks during execution"""

    character: Character
    api: ArtifactsClient


class Task(ABC):
    """Base task interface"""

    @abstractmethod
    def execute(self, context: TaskContext) -> "TaskResult":
        """Execute one step of the task"""
        pass

    @abstractmethod
    def progress(self) -> str:
        """Return progress string"""
        pass

    @abstractmethod
    def description(self) -> str:
        """Return task description for UI"""
        pass


@dataclass
class TaskResult:
    """Result from task execution"""

    completed: bool
    character: Optional[Character] = None
    error: Optional[str] = None
    log_messages: Optional[list[tuple[str, str]]] = None


@dataclass
class HelloTask(Task):
    """Simple hello world task for testing"""

    message: str
    target_count: int
    current_count: int = 0

    def execute(self, context: TaskContext) -> TaskResult:
        self.current_count += 1

        log_messages = [
            (f"{self.message} ({self.current_count}/{self.target_count})", "INFO"),
        ]

        if self.current_count % 2 == 0:
            log_messages.append(
                (f"Milestone reached: {self.current_count} iterations", "DEBUG")
            )

        completed = self.current_count >= self.target_count
        if completed:
            log_messages.append(("Hello task completed successfully!", "INFO"))

        import time

        time.sleep(1)

        return TaskResult(
            completed=completed, character=context.character, log_messages=log_messages
        )

    def progress(self) -> str:
        return f"{self.current_count}/{self.target_count}"

    def description(self) -> str:
        return f"Say hello {self.target_count} times"
