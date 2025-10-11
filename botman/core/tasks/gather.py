from dataclasses import dataclass

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError, CODE_RESOURCE_NOT_FOUND


@dataclass
class GatherTask(Task):
    resource_code: str
    target_amount: int
    gathered_amount: int = 0

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        location = context.world.gathering_location(self.resource_code)

        if not location:
            error = FatalError(
                code=CODE_RESOURCE_NOT_FOUND,
                message=f"Resource '{self.resource_code}' not found in world data."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        target_x, target_y = location
        current_pos = context.character.position

        # Step 1: Move to the resource
        if (current_pos.x, current_pos.y) != (target_x, target_y):
            try:
                result = await context.api.move(x=target_x, y=target_y, name=name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Moving to {self.resource_code} at ({target_x}, {target_y})", "INFO")],
                )
            except APIError as e:
                return TaskResult(completed=False, character=context.character, error=e)

        # Step 2: Gather the resource
        try:
            result = await context.api.gather(name)
            self.gathered_amount += 1

            items_gathered = [f"{drop.code} x{drop.quantity}" for drop in result.details.items]
            items_str = ", ".join(items_gathered) if items_gathered else "nothing"
            completed = self.gathered_amount >= self.target_amount

            log_messages = [(f"Gathered {items_str} ({self.gathered_amount}/{self.target_amount})", "INFO")]
            if completed:
                log_messages.append((f"Gathering complete for {self.resource_code}!", "INFO"))

            return TaskResult(
                completed=completed,
                character=result.character,
                log_messages=log_messages,
            )
        except APIError as e:
            level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
            return TaskResult(
                completed=False,
                character=context.character,
                error=e,
                log_messages=[(f"Gather failed: {e.message}", level)]
            )

    def progress(self) -> str:
        return f"{self.gathered_amount}/{self.target_amount}"

    def description(self) -> str:
        resource = self.resource_code.replace("_", " ").title()
        return f"Gather {resource} x{self.target_amount}"