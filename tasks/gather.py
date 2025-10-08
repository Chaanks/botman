from dataclasses import dataclass

from tasks import Task, TaskContext, TaskResult
from errors import (
    ResourceNotFoundError,
    InventoryFullError,
    CharacterInCooldownError,
    ArtifactsError,
)


@dataclass
class GatherTask(Task):
    resource_code: str
    target_amount: int
    gathered_amount: int = 0

    async def execute(self, context: TaskContext) -> TaskResult:
        # Get gathering location from world
        name = context.character.name
        location = context.world.gathering_location(self.resource_code)
        if not location:
            error = ResourceNotFoundError(self.resource_code)
            return TaskResult(
                completed=False,
                character=context.character,
                error=str(error),
                log_messages=[(str(error), "ERROR")],
            )

        target_x, target_y = location
        current_pos = context.character.position

        # Move to gathering location if not there
        if (current_pos.x, current_pos.y) != (target_x, target_y):
            try:
                result = await context.api.move(target_x, target_y, name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[
                        (
                            f"Moving to {self.resource_code} at ({target_x}, {target_y})",
                            "INFO",
                        )
                    ],
                )
            except ArtifactsError as e:
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=f"[{e.code}] {e.message}",
                    log_messages=[(f"Move failed: {e.message}", "ERROR")],
                )

        # Gather resource
        try:
            result = await context.api.gather(name)
            self.gathered_amount += 1

            # Get what we gathered from the result
            items_gathered = [
                f"{drop.code} x{drop.quantity}" for drop in result.details.items
            ]
            items_str = ", ".join(items_gathered) if items_gathered else "nothing"

            completed = self.gathered_amount >= self.target_amount
            log_messages = [
                (
                    f"Gathered {items_str} ({self.gathered_amount}/{self.target_amount})",
                    "INFO",
                )
            ]

            if completed:
                log_messages.append(
                    (
                        f"Gathering complete! Collected {self.gathered_amount} times from {self.resource_code}",
                        "INFO",
                    )
                )

            return TaskResult(
                completed=completed,
                character=result.character,
                log_messages=log_messages,
            )

        except InventoryFullError as e:
            # Inventory full - pause task, bot will handle recovery
            return TaskResult(
                completed=False,
                paused=True,
                character=context.character,
                error=f"[{e.code}] Inventory full",
                log_messages=[("Inventory is full, pausing until deposit", "WARNING")],
            )
        except CharacterInCooldownError as e:
            # Should not happen as bot manages cooldowns, but handle anyway
            return TaskResult(
                completed=False,
                character=context.character,
                error=f"[{e.code}] {e.message}",
                log_messages=[("Character still in cooldown", "WARNING")],
            )
        except ArtifactsError as e:
            # Other API errors
            return TaskResult(
                completed=False,
                character=context.character,
                error=f"[{e.code}] {e.message}",
                log_messages=[(f"Gather failed: {e.message}", "ERROR")],
            )

    def progress(self) -> str:
        return f"{self.gathered_amount}/{self.target_amount}"

    def description(self) -> str:
        resource = self.resource_code.replace("_", " ").title()
        return f"Gather {resource} x{self.target_amount}"
