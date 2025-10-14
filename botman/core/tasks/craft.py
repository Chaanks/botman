from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError
from botman.core.api.models import Skill
from botman.core.bank.messages import (
    CheckItemMessage,
    CheckItemResponse,
    ReserveItemMessage,
    ReserveItemResponse,
    UpdateAfterWithdrawMessage,
    ReleaseReservationMessage,
)


class CraftState(str, Enum):
    """States for craft task state machine"""
    INIT = "init"
    MOVING_TO_WORKSHOP = "moving_to_workshop"
    CRAFTING = "crafting"
    RECYCLING = "recycling"
    COMPLETE = "complete"


@dataclass
class CraftTask(Task):
    """
    Craft items at a workshop.
    """
    item_code: str
    target_amount: int
    recycle: bool = False
    crafted_amount: int = 0
    prunable: bool = False

    # Internal state
    state: CraftState = field(default=CraftState.INIT, init=False, repr=False)
    original_target: int = field(default=0, init=False, repr=False)

    def __post_init__(self):
        """Store original target for progress tracking"""
        self.original_target = self.target_amount

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        current_pos = context.character.position

        # Get item info (needed across all states)
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

        # State machine
        if self.state == CraftState.INIT:
            # Prunable mode: check inventory and bank for existing items
            if self.prunable:
                # Check inventory for existing crafted items
                inventory_count = sum(
                    inv_item.quantity for inv_item in context.character.inventory
                    if inv_item.code == self.item_code
                )

                # Check bank via BankActor
                bank_count = 0
                if context.bank:
                    check_result = await context.bank.ask(
                        CheckItemMessage(
                            code=self.item_code,
                            quantity=0  # Just checking total availability
                        )
                    )
                    bank_count = check_result.total_in_bank

                total_available = inventory_count + bank_count

                # If we already have enough, mark task as complete
                if total_available >= self.target_amount:
                    self.state = CraftState.COMPLETE
                    return TaskResult(
                        completed=True,
                        character=context.character,
                        log_messages=[
                            (f"Already have {total_available}/{self.target_amount} {self.item_code} (inventory: {inventory_count}, bank: {bank_count})", "INFO"),
                            ("Crafting task skipped - sufficient items available", "INFO")
                        ]
                    )

                # Reduce target amount by what we already have
                if total_available > 0:
                    self.target_amount = max(0, self.target_amount - total_available)
                    log_msg = f"Found {total_available} {self.item_code} (inventory: {inventory_count}, bank: {bank_count}). Reducing target to {self.target_amount}"
                else:
                    log_msg = f"No existing {self.item_code} found. Crafting {self.target_amount}"

                self.state = CraftState.MOVING_TO_WORKSHOP
                return TaskResult(
                    completed=False,
                    character=context.character,
                    log_messages=[(log_msg, "INFO")]
                )
            else:
                # Non-prunable mode: skip directly to moving
                self.state = CraftState.MOVING_TO_WORKSHOP
                return TaskResult(completed=False, character=context.character)

        elif self.state == CraftState.MOVING_TO_WORKSHOP:
            # Move to workshop if not already there
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

            self.state = CraftState.CRAFTING
            return TaskResult(completed=False, character=context.character)

        elif self.state == CraftState.CRAFTING:
            # Check if crafting is complete and we need to recycle
            if self.recycle and self.crafted_amount >= self.target_amount:
                self.state = CraftState.RECYCLING
                return TaskResult(completed=False, character=context.character)

            # Calculate batch size
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

            # Craft the items
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
                    self.state = CraftState.COMPLETE
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

        elif self.state == CraftState.RECYCLING:
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
                    self.state = CraftState.COMPLETE
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
                self.state = CraftState.COMPLETE
                return TaskResult(
                    completed=True,
                    character=context.character,
                    log_messages=[("Crafting complete (no items to recycle)", "INFO")]
                )

        # Should not reach here
        return TaskResult(
            completed=True,
            character=context.character,
            log_messages=[("Craft task completed", "INFO")]
        )

    def progress(self) -> str:
        """Return progress indicator"""
        if self.state == CraftState.INIT:
            return "Checking availability"
        elif self.state == CraftState.MOVING_TO_WORKSHOP:
            return "Moving to workshop"
        elif self.state == CraftState.CRAFTING:
            return f"{self.crafted_amount}/{self.target_amount}"
        elif self.state == CraftState.RECYCLING:
            return "Recycling"
        else:
            return "Complete"

    def description(self) -> str:
        """Return human-readable task description"""
        item_name = self.item_code.replace("_", " ").title()
        # Use original target for description to show the initial requirement
        display_amount = self.original_target if self.original_target > 0 else self.target_amount
        if self.recycle:
            return f"Craft & Recycle {item_name} x{display_amount}"
        else:
            return f"Craft {item_name} x{display_amount}"

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


class CraftWithMaterialsState(str, Enum):
    """States for craft with materials task state machine"""
    INIT = "init"
    CHECKING_MATERIALS = "checking_materials"
    MOVING_TO_BANK = "moving_to_bank"
    WITHDRAWING = "withdrawing"
    MOVING_TO_WORKSHOP = "moving_to_workshop"
    CRAFTING = "crafting"
    MOVING_TO_BANK_DEPOSIT = "moving_to_bank_deposit"
    DEPOSITING = "depositing"
    COMPLETE = "complete"


@dataclass
class CraftWithMaterialsTask(Task):
    """
    Craft items with automatic material management from bank.

    This task handles the complete crafting workflow:
    1. Check if items already exist (prunable mode)
    2. Reserve and withdraw materials from bank
    3. Move to workshop and craft
    4. Deposit all items back to bank

    Use this for automated workflows (MRP).
    Use CraftTask for manual crafting with pre-staged materials.
    """
    item_code: str
    target_quantity: int
    prunable: bool = True

    # Internal state
    crafted_amount: int = 0
    state: CraftWithMaterialsState = field(default=CraftWithMaterialsState.INIT, init=False, repr=False)
    original_target: int = field(default=0, init=False, repr=False)
    materials_needed: Dict[str, int] = field(default_factory=dict, init=False, repr=False)
    material_reservations: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        """Store original target for progress tracking"""
        self.original_target = self.target_quantity

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        current_pos = context.character.position

        # Bank location
        BANK_X, BANK_Y = 4, 1

        # Get item info (needed across most states)
        item = context.world.item(self.item_code)
        if not item:
            error = FatalError(code=404, message=f"Item '{self.item_code}' not found in world data.")
            return TaskResult(completed=False, character=context.character, error=error, log_messages=[(str(error), "ERROR")])

        if not item.craft:
            error = FatalError(code=498, message=f"Item '{self.item_code}' is not craftable.")
            return TaskResult(completed=False, character=context.character, error=error, log_messages=[(str(error), "ERROR")])

        # State machine
        if self.state == CraftWithMaterialsState.INIT:
            # Prunable mode: check inventory and bank for existing crafted items
            if self.prunable:
                inventory_count = sum(
                    inv_item.quantity for inv_item in context.character.inventory
                    if inv_item.code == self.item_code
                )

                bank_count = 0
                if context.bank:
                    check_result: CheckItemResponse = await context.bank.ask(
                        CheckItemMessage(code=self.item_code, quantity=0)
                    )
                    bank_count = check_result.total_in_bank

                total_available = inventory_count + bank_count

                if total_available >= self.target_quantity:
                    self.state = CraftWithMaterialsState.COMPLETE
                    return TaskResult(
                        completed=True,
                        character=context.character,
                        log_messages=[
                            (f"Already have {total_available}/{self.target_quantity} {self.item_code} (inventory: {inventory_count}, bank: {bank_count})", "INFO"),
                            ("Crafting task skipped - sufficient items available", "INFO")
                        ]
                    )

                if total_available > 0:
                    self.target_quantity = max(0, self.target_quantity - total_available)
                    log_msg = f"Found {total_available} {self.item_code} (inventory: {inventory_count}, bank: {bank_count}). Need to craft {self.target_quantity} more"
                else:
                    log_msg = f"No existing {self.item_code} found. Crafting {self.target_quantity}"

                self.state = CraftWithMaterialsState.CHECKING_MATERIALS
                return TaskResult(completed=False, character=context.character, log_messages=[(log_msg, "INFO")])
            else:
                self.state = CraftWithMaterialsState.CHECKING_MATERIALS
                return TaskResult(completed=False, character=context.character)

        elif self.state == CraftWithMaterialsState.CHECKING_MATERIALS:
            # Calculate materials needed
            recipe_output = item.craft.quantity
            crafts_needed = (self.target_quantity + recipe_output - 1) // recipe_output

            for req in item.craft.requirements:
                self.materials_needed[req.code] = req.quantity * crafts_needed

            if not context.bank:
                error = FatalError(0, "BankActor not available")
                return TaskResult(completed=False, character=context.character, error=error, log_messages=[("BankActor not available", "ERROR")])

            # Check and reserve each material
            for material_code, qty in self.materials_needed.items():
                check_result: CheckItemResponse = await context.bank.ask(
                    CheckItemMessage(code=material_code, quantity=qty)
                )

                if not check_result.available:
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=FatalError(0, f"Insufficient {material_code} in bank"),
                        log_messages=[(
                            f"Cannot craft {self.item_code}: need {material_code} x{qty}, only {check_result.free} available "
                            f"(total: {check_result.total_in_bank}, reserved: {check_result.reserved})",
                            "ERROR"
                        )]
                    )

                reserve_result: ReserveItemResponse = await context.bank.ask(
                    ReserveItemMessage(code=material_code, quantity=qty, bot_name=name)
                )

                if not reserve_result.success:
                    await self._release_all_reservations(context)
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=FatalError(0, f"Failed to reserve {material_code}"),
                        log_messages=[(f"Reservation failed: {reserve_result.error or 'Unknown error'}", "ERROR")]
                    )

                self.material_reservations[material_code] = reserve_result.reservation_id

            materials_summary = ", ".join([f"{code} x{qty}" for code, qty in self.materials_needed.items()])
            self.state = CraftWithMaterialsState.MOVING_TO_BANK
            return TaskResult(
                completed=False,
                character=context.character,
                log_messages=[(f"Reserved materials: {materials_summary}", "INFO")]
            )

        elif self.state == CraftWithMaterialsState.MOVING_TO_BANK:
            if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
                try:
                    result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to bank at ({BANK_X}, {BANK_Y})", "INFO")]
                    )
                except APIError as e:
                    await self._release_all_reservations(context)
                    return TaskResult(completed=False, character=context.character, error=e)

            self.state = CraftWithMaterialsState.WITHDRAWING
            return TaskResult(completed=False, character=context.character)

        elif self.state == CraftWithMaterialsState.WITHDRAWING:
            try:
                withdraw_items = [{"code": code, "quantity": qty} for code, qty in self.materials_needed.items()]
                result = await context.api.withdraw_item(items=withdraw_items, name=name)

                # Notify bank of withdrawal
                if context.bank:
                    for material_code, qty in self.materials_needed.items():
                        reservation_id = self.material_reservations.get(material_code)
                        if reservation_id:
                            await context.bank.tell(
                                UpdateAfterWithdrawMessage(
                                    reservation_id=reservation_id,
                                    actual_quantity=qty
                                )
                            )

                self.material_reservations.clear()

                materials_summary = ", ".join([f"{code} x{qty}" for code, qty in self.materials_needed.items()])
                self.state = CraftWithMaterialsState.MOVING_TO_WORKSHOP
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Withdrew materials: {materials_summary}", "INFO")]
                )
            except APIError as e:
                await self._release_all_reservations(context)
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(completed=False, character=context.character, error=e, log_messages=[(f"Withdraw failed: {e.message}", level)])

        elif self.state == CraftWithMaterialsState.MOVING_TO_WORKSHOP:
            # Get workshop location
            craft_skill_str = item.craft.skill
            try:
                craft_skill = Skill(craft_skill_str)
            except ValueError:
                error = FatalError(499, f"Unknown crafting skill: {craft_skill_str}")
                return TaskResult(completed=False, character=context.character, error=error, log_messages=[(str(error), "ERROR")])

            workshop_map = context.world.map_by_skill(craft_skill)
            if not workshop_map:
                error = FatalError(404, f"Workshop for skill '{craft_skill.value}' not found.")
                return TaskResult(completed=False, character=context.character, error=error, log_messages=[(str(error), "ERROR")])

            if (current_pos.x, current_pos.y) != (workshop_map.x, workshop_map.y):
                try:
                    result = await context.api.move(x=workshop_map.x, y=workshop_map.y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to {craft_skill.value} workshop at ({workshop_map.x}, {workshop_map.y})", "INFO")]
                    )
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            self.state = CraftWithMaterialsState.CRAFTING
            return TaskResult(completed=False, character=context.character)

        elif self.state == CraftWithMaterialsState.CRAFTING:
            # Calculate batch size
            batch = self._calculate_batch_size(context, item)

            if not self._can_craft(context, item, batch):
                error = RecoverableError(478, f"Missing materials to craft {self.item_code} x{batch}")
                return TaskResult(completed=False, character=context.character, error=error, log_messages=[(str(error), "WARNING")])

            try:
                result = await context.api.craft(self.item_code, batch, name)
                self.crafted_amount += batch

                items_crafted = [f"{drop.code} x{drop.quantity}" for drop in result.details.items]
                items_str = ", ".join(items_crafted) if items_crafted else f"{self.item_code} x{batch}"
                xp_gained = result.details.xp

                log_messages = [
                    (f"Crafted {items_str} (+{xp_gained} XP) [{self.crafted_amount}/{self.target_quantity}]", "INFO")
                ]

                if self.crafted_amount >= self.target_quantity:
                    log_messages.append((f"Crafting complete for {self.item_code}!", "INFO"))
                    self.state = CraftWithMaterialsState.MOVING_TO_BANK_DEPOSIT

                return TaskResult(completed=False, character=result.character, log_messages=log_messages)
            except APIError as e:
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(completed=False, character=context.character, error=e, log_messages=[(f"Craft failed: {e.message}", level)])

        elif self.state == CraftWithMaterialsState.MOVING_TO_BANK_DEPOSIT:
            if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
                try:
                    result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                    return TaskResult(completed=False, character=result.character, log_messages=[(f"Moving to bank for deposit", "INFO")])
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            self.state = CraftWithMaterialsState.DEPOSITING
            return TaskResult(completed=False, character=context.character)

        elif self.state == CraftWithMaterialsState.DEPOSITING:
            try:
                # Deposit all items
                deposit_items = [{"code": item.code, "quantity": item.quantity} for item in context.character.inventory]
                if deposit_items:
                    result = await context.api.deposit_item(items=deposit_items, name=name)

                    deposited_summary = ", ".join([f"{item['code']} x{item['quantity']}" for item in deposit_items])
                    self.state = CraftWithMaterialsState.COMPLETE
                    return TaskResult(
                        completed=True,
                        character=result.character,
                        log_messages=[
                            (f"Deposited: {deposited_summary}", "INFO"),
                            ("Craft with materials complete!", "INFO")
                        ]
                    )
                else:
                    self.state = CraftWithMaterialsState.COMPLETE
                    return TaskResult(completed=True, character=context.character, log_messages=[("Craft with materials complete!", "INFO")])
            except APIError as e:
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(completed=False, character=context.character, error=e, log_messages=[(f"Deposit failed: {e.message}", level)])

        # Should not reach here
        return TaskResult(completed=True, character=context.character, log_messages=[("Craft with materials task completed", "INFO")])

    async def _release_all_reservations(self, context: TaskContext):
        """Release all material reservations on error (best effort)"""
        if not self.material_reservations or not context.bank:
            return

        for material_code, reservation_id in list(self.material_reservations.items()):
            try:
                await context.bank.tell(ReleaseReservationMessage(reservation_id=reservation_id))
            except Exception:
                pass

        self.material_reservations.clear()

    def _calculate_batch_size(self, context: TaskContext, item) -> int:
        """Calculate optimal batch size for crafting"""
        character = context.character

        if not item.craft.requirements:
            return 1

        # Calculate max based on available materials
        max_from_materials = float('inf')
        for requirement in item.craft.requirements:
            mat_in_inventory = sum(
                inv_item.quantity for inv_item in character.inventory
                if inv_item.code == requirement.code
            )
            possible = mat_in_inventory // requirement.quantity
            max_from_materials = min(max_from_materials, possible)

        if max_from_materials == float('inf'):
            max_from_materials = 0

        # Calculate max based on inventory space
        free_slots = character.inventory_space()
        max_from_space = free_slots // item.craft.quantity

        # Don't exceed target amount
        remaining = self.target_quantity - self.crafted_amount
        max_from_target = remaining

        # Return the minimum constraint
        batch = min(max_from_materials, max_from_space, max_from_target)
        return max(1, int(batch))

    def _can_craft(self, context: TaskContext, item, quantity: int) -> bool:
        """Check if character has materials to craft the specified quantity"""
        character = context.character

        for requirement in item.craft.requirements:
            mat_qty_needed = requirement.quantity * quantity
            if not character.has_item(requirement.code, mat_qty_needed):
                return False

        return True

    def progress(self) -> str:
        """Return progress indicator"""
        if self.state == CraftWithMaterialsState.INIT:
            return "Checking availability"
        elif self.state == CraftWithMaterialsState.CHECKING_MATERIALS:
            return "Reserving materials"
        elif self.state in {CraftWithMaterialsState.MOVING_TO_BANK, CraftWithMaterialsState.WITHDRAWING}:
            return "Getting materials"
        elif self.state == CraftWithMaterialsState.MOVING_TO_WORKSHOP:
            return "Traveling to workshop"
        elif self.state == CraftWithMaterialsState.CRAFTING:
            return f"{self.crafted_amount}/{self.target_quantity}"
        elif self.state in {CraftWithMaterialsState.MOVING_TO_BANK_DEPOSIT, CraftWithMaterialsState.DEPOSITING}:
            return "Depositing"
        else:
            return "Complete"

    def description(self) -> str:
        """Return human-readable task description"""
        item_name = self.item_code.replace("_", " ").title()
        display_amount = self.original_target if self.original_target > 0 else self.target_quantity
        return f"Craft {item_name} x{display_amount}"