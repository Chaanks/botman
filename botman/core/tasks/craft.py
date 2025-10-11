from dataclasses import dataclass
from typing import Optional

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError
from botman.core.models import Skill


@dataclass
class CraftTask(Task):
    """
    Craft items at a workshop.
    """
    item_code: str
    target_amount: int
    recycle: bool = False
    crafted_amount: int = 0

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        current_pos = context.character.position

        # Get item info
        item = context.world.item(self.item_code)
        if not item:
            error = FatalError(
                code=404,
                message=f"Item '{self.item_code}' not found in world data."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        if not item.craft:
            error = FatalError(
                code=498,
                message=f"Item '{self.item_code}' is not craftable."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # Get workshop location from craft skill
        craft_skill_str = item.craft.skill
        if not craft_skill_str:
            error = FatalError(
                code=499,
                message=f"Item '{self.item_code}' has no crafting skill defined."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # Convert skill string to Skill enum
        try:
            craft_skill = Skill(craft_skill_str)
        except ValueError:
            error = FatalError(
                code=499,
                message=f"Unknown crafting skill: {craft_skill_str}"
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # Step 1: Move to workshop if not already there
        workshop_map = context.world.map_by_skill(craft_skill)
        if not workshop_map:
            error = FatalError(
                code=404,
                message=f"Workshop for skill '{craft_skill.value}' not found."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        if (current_pos.x, current_pos.y) != (workshop_map.x, workshop_map.y):
            try:
                result = await context.api.move(x=workshop_map.x, y=workshop_map.y, name=name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Moving to {craft_skill.value} workshop at ({workshop_map.x}, {workshop_map.y})", "INFO")],
                )
            except APIError as e:
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=e,
                    log_messages=[(f"Failed to move to workshop: {e.message}", "ERROR")]
                )

        # Step 2: Check if we need to recycle (crafting complete)
        if self.recycle and self.crafted_amount >= self.target_amount:
            # Calculate how many items we have to recycle
            items_to_recycle = sum(
                inv_item.quantity
                for inv_item in context.character.inventory
                if inv_item.code == self.item_code
            )

            if items_to_recycle > 0:
                try:
                    result = await context.api.recycle(self.item_code, items_to_recycle, name)
                    recycled_items = [f"{drop.code} x{drop.quantity}" for drop in result.details.items]
                    recycled_str = ", ".join(recycled_items) if recycled_items else "nothing"
                    return TaskResult(
                        completed=True,
                        character=result.character,
                        log_messages=[
                            (f"Recycled {self.item_code} x{items_to_recycle}, got: {recycled_str}", "INFO"),
                            ("Crafting and recycling complete!", "INFO")
                        ]
                    )
                except APIError as e:
                    level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=e,
                        log_messages=[(f"Recycle failed: {e.message}", level)]
                    )
            else:
                # No items to recycle, task complete
                return TaskResult(
                    completed=True,
                    character=context.character,
                    log_messages=[("Crafting complete (no items to recycle)", "INFO")]
                )

        # Step 3: Calculate batch size
        batch = self._calculate_batch_size(context)

        # Check if we can craft
        if not self._can_craft(context, batch):
            error = RecoverableError(
                code=478,
                message=f"Missing materials to craft {self.item_code} x{batch}"
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "WARNING")]
            )

        # Step 4: Craft the items
        try:
            result = await context.api.craft(self.item_code, batch, name)
            self.crafted_amount += batch

            # Build log message
            items_crafted = [f"{drop.code} x{drop.quantity}" for drop in result.details.items]
            items_str = ", ".join(items_crafted) if items_crafted else f"{self.item_code} x{batch}"
            xp_gained = result.details.xp

            log_messages = [
                (f"Crafted {items_str} (+{xp_gained} XP) [{self.crafted_amount}/{self.target_amount}]", "INFO")
            ]

            # Check if crafting is complete (but not recycling yet)
            if self.crafted_amount >= self.target_amount and not self.recycle:
                log_messages.append((f"Crafting complete for {self.item_code}!", "INFO"))
                return TaskResult(
                    completed=True,
                    character=result.character,
                    log_messages=log_messages
                )

            return TaskResult(
                completed=False,
                character=result.character,
                log_messages=log_messages
            )
        except APIError as e:
            level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
            return TaskResult(
                completed=False,
                character=context.character,
                error=e,
                log_messages=[(f"Craft failed: {e.message}", level)]
            )

    def progress(self) -> str:
        """Return progress indicator"""
        if self.recycle and self.crafted_amount >= self.target_amount:
            return "Recycling"
        return f"{self.crafted_amount}/{self.target_amount}"

    def description(self) -> str:
        """Return human-readable task description"""
        item_name = self.item_code.replace("_", " ").title()
        if self.recycle:
            return f"Craft & Recycle {item_name} x{self.target_amount}"
        else:
            return f"Craft {item_name} x{self.target_amount}"

    def _calculate_batch_size(self, context: TaskContext) -> int:
        """Calculate optimal batch size for crafting"""
        item = context.world.item(self.item_code)
        if not item or not item.craft:
            return 1

        character = context.character

        # Get craft requirements
        if not item.craft.requirements:
            return 1

        # Calculate max based on available materials
        max_from_materials = float('inf')
        for requirement in item.craft.requirements:
            mat_in_inventory = sum(
                inv_item.quantity
                for inv_item in character.inventory
                if inv_item.code == requirement.code
            )
            possible = mat_in_inventory // requirement.quantity
            max_from_materials = min(max_from_materials, possible)

        if max_from_materials == float('inf'):
            max_from_materials = 0

        # Calculate max based on inventory space
        # Each craft produces item.craft.quantity items
        free_slots = character.inventory_space()
        max_from_space = free_slots // item.craft.quantity

        # Don't exceed target amount
        remaining = self.target_amount - self.crafted_amount
        max_from_target = remaining

        # Return the minimum constraint
        batch = min(max_from_materials, max_from_space, max_from_target)
        return max(1, int(batch))  # At least 1

    def _can_craft(self, context: TaskContext, quantity: int) -> bool:
        """Check if character has materials to craft the specified quantity"""
        item = context.world.item(self.item_code)
        if not item or not item.craft:
            return False

        character = context.character

        for requirement in item.craft.requirements:
            mat_qty_needed = requirement.quantity * quantity
            if not character.has_item(requirement.code, mat_qty_needed):
                return False

        return True