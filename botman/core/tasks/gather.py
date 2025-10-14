from dataclasses import dataclass, field
from enum import Enum

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError, CODE_RESOURCE_NOT_FOUND
from botman.core.bank.messages import CheckItemMessage


class GatherState(str, Enum):
    INIT = "init"
    MOVING = "moving"
    GATHERING = "gathering"
    COMPLETE = "complete"


@dataclass
class GatherTask(Task):
    resource_code: str
    target_amount: int
    gathered_amount: int = 0

    state: GatherState = field(default=GatherState.INIT, init=False, repr=False)
    original_target: int = field(default=0, init=False, repr=False)

    def __post_init__(self):
        self.original_target = self.target_amount

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

        if self.state == GatherState.INIT:
            # Move directly to the resource location
            self.state = GatherState.MOVING
            return TaskResult(completed=False, character=context.character)

        elif self.state == GatherState.MOVING:
            # Move to the resource
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

            self.state = GatherState.GATHERING
            return TaskResult(completed=False, character=context.character)

        elif self.state == GatherState.GATHERING:
            # Gather the resource
            try:
                result = await context.api.gather(name)
                self.gathered_amount += 1

                items_gathered = [f"{drop.code} x{drop.quantity}" for drop in result.details.items]
                items_str = ", ".join(items_gathered) if items_gathered else "nothing"
                completed = self.gathered_amount >= self.target_amount

                log_messages = [(f"Gathered {items_str} ({self.gathered_amount}/{self.target_amount})", "INFO")]
                if completed:
                    log_messages.append((f"Gathering complete for {self.resource_code}!", "INFO"))
                    self.state = GatherState.COMPLETE

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

        # Should not reach here
        return TaskResult(
            completed=True,
            character=context.character,
            log_messages=[("Gather task completed", "INFO")]
        )

    def progress(self) -> str:
        if self.state in {GatherState.INIT, GatherState.MOVING}:
            return "Traveling"
        elif self.state == GatherState.GATHERING:
            return f"{self.gathered_amount}/{self.target_amount}"
        else:
            return "Complete"

    def description(self) -> str:
        resource = self.resource_code.replace("_", " ").title()
        # Use original target for description to show the initial requirement
        display_amount = self.original_target if self.original_target > 0 else self.target_amount
        return f"Gather {resource} x{display_amount}"


@dataclass
class GatherUntilDropTask(Task):
    """
    Gather from a resource until a specific drop item is obtained.
    Supports prunable mode to check inventory/bank before starting.
    """
    resource_code: str
    drop_code: str
    target_quantity: int
    prunable: bool = False

    # Internal state
    gather_count: int = 0
    collected_quantity: int = 0
    state: GatherState = field(default=GatherState.INIT, init=False, repr=False)
    original_target: int = field(default=0, init=False, repr=False)

    def __post_init__(self):
        """Store original target for progress tracking"""
        self.original_target = self.target_quantity

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

        # State machine
        if self.state == GatherState.INIT:
            # Prunable mode: check inventory and bank for existing drops
            if self.prunable:
                # Check inventory for existing drops
                inventory_count = sum(
                    item.quantity for item in context.character.inventory
                    if item.code == self.drop_code
                )

                # Check bank via BankActor
                bank_count = 0
                if context.bank:
                    check_result = await context.bank.ask(
                        CheckItemMessage(
                            code=self.drop_code,
                            quantity=0  # Just checking total availability
                        )
                    )
                    bank_count = check_result.total_in_bank

                total_available = inventory_count + bank_count

                # If we already have enough, mark task as complete
                if total_available >= self.target_quantity:
                    self.state = GatherState.COMPLETE
                    return TaskResult(
                        completed=True,
                        character=context.character,
                        log_messages=[
                            (f"Already have {total_available}/{self.target_quantity} {self.drop_code} (inventory: {inventory_count}, bank: {bank_count})", "INFO"),
                            ("Gathering task skipped - sufficient drops available", "INFO")
                        ]
                    )

                # Reduce target quantity by what we already have
                if total_available > 0:
                    self.target_quantity = max(0, self.target_quantity - total_available)
                    self.collected_quantity = total_available
                    log_msg = f"Found {total_available} {self.drop_code} (inventory: {inventory_count}, bank: {bank_count}). Need {self.target_quantity} more"
                else:
                    log_msg = f"No existing {self.drop_code} found. Gathering for {self.target_quantity}"

                self.state = GatherState.MOVING
                return TaskResult(
                    completed=False,
                    character=context.character,
                    log_messages=[(log_msg, "INFO")]
                )
            else:
                # Non-prunable mode: skip directly to moving
                self.state = GatherState.MOVING
                return TaskResult(completed=False, character=context.character)

        elif self.state == GatherState.MOVING:
            # Move to the resource
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

            self.state = GatherState.GATHERING
            return TaskResult(completed=False, character=context.character)

        elif self.state == GatherState.GATHERING:
            # Gather the resource
            try:
                result = await context.api.gather(name)
                self.gather_count += 1

                # Track drops of the target item
                drops_of_target = 0
                if result.details and result.details.items:
                    for item in result.details.items:
                        if item.code == self.drop_code:
                            drops_of_target += item.quantity
                            self.collected_quantity += item.quantity

                items_gathered = [f"{item.code} x{item.quantity}" for item in result.details.items] if result.details.items else []
                items_str = ", ".join(items_gathered) if items_gathered else "nothing"

                # Check if we've collected enough of the target drop
                completed = self.collected_quantity >= self.target_quantity

                log_messages = [
                    (f"Gathered {items_str}", "INFO")
                ]

                if drops_of_target > 0:
                    log_messages.append((f"Collected {self.drop_code} x{drops_of_target} ({self.collected_quantity}/{self.target_quantity}) after {self.gather_count} gathers", "INFO"))

                if completed:
                    log_messages.append((f"Collected enough {self.drop_code} after {self.gather_count} gathers!", "INFO"))
                    self.state = GatherState.COMPLETE

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

        # Should not reach here
        return TaskResult(
            completed=True,
            character=context.character,
            log_messages=[("Gather until drop task completed", "INFO")]
        )

    def progress(self) -> str:
        if self.state == GatherState.INIT:
            return "Checking availability"
        elif self.state == GatherState.MOVING:
            return "Traveling"
        elif self.state == GatherState.GATHERING:
            return f"{self.collected_quantity}/{self.target_quantity} ({self.gather_count} gathers)"
        else:
            return "Complete"

    def description(self) -> str:
        resource = self.resource_code.replace("_", " ").title()
        drop = self.drop_code.replace("_", " ").title()
        # Use original target for description to show the initial requirement
        display_amount = self.original_target if self.original_target > 0 else self.target_quantity
        return f"Gather {resource} for {drop} x{display_amount}"