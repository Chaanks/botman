from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod

from botman.core.api import ArtifactsClient
from botman.core.models import Character
from botman.core.world import World


@dataclass
class TaskContext:
    character: Character
    api: ArtifactsClient
    world: World


class Task(ABC):
    @abstractmethod
    async def execute(self, context: TaskContext) -> "TaskResult":
        pass

    @abstractmethod
    def progress(self) -> str:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


@dataclass
class TaskResult:
    completed: bool
    character: Optional[Character] = None
    error: Optional[str] = None
    log_messages: Optional[list[tuple[str, str]]] = None
    paused: bool = False


from botman.core.tasks.gather import GatherTask


__all__ = ["Task", "TaskContext", "TaskResult", "HelloTask", "GatherTask"]


@dataclass
class HelloTask(Task):
    message: str
    target_count: int
    current_count: int = 0

    async def execute(self, context: TaskContext) -> TaskResult:
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

        import asyncio

        await asyncio.sleep(1)

        return TaskResult(
            completed=completed, character=context.character, log_messages=log_messages
        )

    def progress(self) -> str:
        return f"{self.current_count}/{self.target_count}"

    def description(self) -> str:
        return f"Say hello {self.target_count} times"
