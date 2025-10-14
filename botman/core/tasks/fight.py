from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError
from botman.core.bank.messages import (
    CheckItemMessage,
    CheckItemResponse,
    ReserveItemMessage,
    ReserveItemResponse,
    ReleaseReservationMessage,
    UpdateAfterWithdrawMessage,
)


class FightState(str, Enum):
    """Shared states for fight tasks"""
    INIT = "init"
    CHECKING_FOOD = "checking_food"
    MOVING_TO_BANK = "moving_to_bank"
    WITHDRAWING_FOOD = "withdrawing_food"
    MOVING_TO_MONSTER = "moving_to_monster"
    HEALING = "healing"
    FIGHTING = "fighting"
    COMPLETE = "complete"


@dataclass
class FightTask(Task):
    """
    Fight a monster for a specified number of kills.
    Note: No prunable support - kills can't be pre-checked in inventory/bank.
    """
    monster_code: str
    target_kills: int
    kills: int = 0
    state: FightState = FightState.INIT
    food_code: Optional[str] = None
    food_reservation_id: Optional[str] = None
    hp_threshold: int = 50  # Use consumable if HP drops below this

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        monster = context.world.monster(self.monster_code)

        if not monster:
            error = FatalError(
                code=1000,
                message=f"Monster '{self.monster_code}' not found in world data."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # Step 0: Check and reserve food from bank (once at start)
        if self.state == FightState.INIT:
            self.state = FightState.CHECKING_FOOD
            return TaskResult(completed=False, character=context.character)

        if self.state == FightState.CHECKING_FOOD:
            # Check bank for food items (priority: cooked_gudgeon > cooked_chicken)
            if context.bank:
                for food in ["cooked_gudgeon", "cooked_chicken"]:
                    check_result: CheckItemResponse = await context.bank.ask(
                        CheckItemMessage(code=food, quantity=50)
                    )

                    if check_result.available:
                        # Reserve the food
                        reserve_qty = min(50, check_result.free)
                        reserve_result: ReserveItemResponse = await context.bank.ask(
                            ReserveItemMessage(code=food, quantity=reserve_qty, bot_name=name)
                        )

                        if reserve_result.success:
                            self.food_code = food
                            self.food_reservation_id = reserve_result.reservation_id
                            self.state = FightState.MOVING_TO_BANK
                            return TaskResult(
                                completed=False,
                                character=context.character,
                                log_messages=[(f"Reserved {food} x{reserve_qty} from bank", "INFO")]
                            )

            # No food found or no bank access, skip to fighting
            self.state = FightState.MOVING_TO_MONSTER
            return TaskResult(completed=False, character=context.character)

        if self.state == FightState.MOVING_TO_BANK:
            # Move to bank location (4, 1)
            BANK_X, BANK_Y = 4, 1
            current_pos = context.character.position

            if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
                try:
                    result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to bank at ({BANK_X}, {BANK_Y})", "INFO")],
                    )
                except APIError:
                    # Release reservation on error
                    await self._release_reservation(context)
                    self.state = FightState.MOVING_TO_MONSTER
                    return TaskResult(completed=False, character=context.character)

            self.state = FightState.WITHDRAWING_FOOD
            return TaskResult(completed=False, character=context.character)

        if self.state == FightState.WITHDRAWING_FOOD:
            # Withdraw food from bank
            try:
                withdraw_qty = 50  # Withdraw up to 50
                result = await context.api.withdraw_item(
                    items=[{"code": self.food_code, "quantity": withdraw_qty}],
                    name=name
                )

                # Notify BankActor of withdrawal
                if context.bank and self.food_reservation_id:
                    await context.bank.tell(
                        UpdateAfterWithdrawMessage(
                            reservation_id=self.food_reservation_id,
                            actual_quantity=withdraw_qty
                        )
                    )
                    self.food_reservation_id = None

                self.state = FightState.MOVING_TO_MONSTER
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Withdrew {self.food_code} x{withdraw_qty}", "INFO")]
                )

            except APIError:
                # Release reservation and continue without food
                await self._release_reservation(context)
                self.state = FightState.MOVING_TO_MONSTER
                return TaskResult(completed=False, character=context.character)

        if self.state == FightState.MOVING_TO_MONSTER:
            # Find monster location
            location = context.world.gathering_location(self.monster_code)
            if not location:
                error = FatalError(
                    code=1000,
                    message=f"Monster '{self.monster_code}' location not found."
                )
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=error,
                    log_messages=[(str(error), "ERROR")],
                )

            target_x, target_y = location
            current_pos = context.character.position

            # Move to the monster
            if (current_pos.x, current_pos.y) != (target_x, target_y):
                try:
                    result = await context.api.move(x=target_x, y=target_y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to {monster.name} at ({target_x}, {target_y})", "INFO")],
                    )
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            self.state = FightState.HEALING
            return TaskResult(completed=False, character=context.character)

        if self.state == FightState.HEALING:
            # Check HP and heal if needed
            hp = context.character.stats.hp
            max_hp = context.character.stats.max_hp

            # Use consumable if HP is low and we have food
            if hp <= self.hp_threshold and self.food_code:
                # Check if we have the food in inventory
                food_in_inv = next(
                    (item for item in context.character.inventory if item.code == self.food_code),
                    None
                )

                if food_in_inv and food_in_inv.quantity > 0:
                    try:
                        result = await context.api.use_item(
                            item_code=self.food_code,
                            quantity=1,
                            name=name
                        )
                        # Stay in healing state to check HP again
                        return TaskResult(
                            completed=False,
                            character=result.character,
                            log_messages=[(f"Used {self.food_code} to heal (HP: {hp}/{max_hp})", "INFO")],
                        )
                    except APIError:
                        # If healing fails, fall back to resting
                        pass

            # Rest if HP is low and no food or food failed
            if hp <= self.hp_threshold:
                try:
                    result = await context.api.rest(name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Resting to recover HP ({hp}/{max_hp})", "INFO")],
                    )
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            # HP is good, proceed to fighting
            self.state = FightState.FIGHTING
            return TaskResult(completed=False, character=context.character)

        if self.state == FightState.FIGHTING:
            try:
                result = await context.api.fight(name=name)
                self.kills += 1

                fight_result = result.fight.result  # "win" or "lose"

                # Get character-specific fight results (for solo, there's only one)
                char_result = result.fight.characters[0] if result.fight.characters else None
                xp_gained = char_result.xp if char_result else 0
                gold_gained = char_result.gold if char_result else 0
                items_dropped = [f"{drop.code} x{drop.quantity}" for drop in char_result.drops] if char_result else []
                items_str = ", ".join(items_dropped) if items_dropped else "nothing"

                # Get updated character state
                character = result.characters[0] if result.characters else context.character

                completed = self.kills >= self.target_kills

                log_messages = [
                    (f"Fight {fight_result}! XP: +{xp_gained}, Gold: +{gold_gained}, Drops: {items_str} ({self.kills}/{self.target_kills})", "INFO")
                ]

                if completed:
                    log_messages.append((f"Fighting complete for {monster.name}!", "INFO"))
                else:
                    # Go back to healing state to check HP before next fight
                    self.state = FightState.HEALING

                return TaskResult(
                    completed=completed,
                    character=character,
                    log_messages=log_messages,
                )
            except APIError as e:
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=e,
                    log_messages=[(f"Fight failed: {e.message}", level)]
                )

        # Shouldn't reach here
        return TaskResult(completed=True, character=context.character)

    async def _release_reservation(self, context: TaskContext):
        """Release food reservation on error (best effort)"""
        if not self.food_reservation_id or not context.bank:
            return

        try:
            await context.bank.tell(
                ReleaseReservationMessage(reservation_id=self.food_reservation_id)
            )
            self.food_reservation_id = None
        except Exception:
            pass

    def progress(self) -> str:
        if self.state in {FightState.INIT, FightState.CHECKING_FOOD}:
            return "Preparing"
        elif self.state in {FightState.MOVING_TO_BANK, FightState.WITHDRAWING_FOOD}:
            return "Getting supplies"
        elif self.state == FightState.MOVING_TO_MONSTER:
            return "Traveling"
        elif self.state == FightState.HEALING:
            return "Healing"
        else:
            return f"{self.kills}/{self.target_kills}"

    def description(self) -> str:
        monster = self.monster_code.replace("_", " ").title()
        return f"Fight {monster} x{self.target_kills}"


@dataclass
class FightUntilDropTask(Task):
    """
    Fight a monster until a specific item drop is obtained.
    Supports prunable mode to check inventory/bank before starting.
    """
    monster_code: str
    drop_code: str
    target_quantity: int
    prunable: bool = False

    # Internal state
    kills: int = 0
    collected_quantity: int = 0
    state: FightState = field(default=FightState.INIT, init=False, repr=False)
    original_target: int = field(default=0, init=False, repr=False)
    food_code: Optional[str] = field(default=None, init=False, repr=False)
    food_reservation_id: Optional[str] = field(default=None, init=False, repr=False)
    hp_threshold: int = 50

    def __post_init__(self):
        """Store original target for progress tracking"""
        self.original_target = self.target_quantity

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        monster = context.world.monster(self.monster_code)

        if not monster:
            error = FatalError(
                code=1000,
                message=f"Monster '{self.monster_code}' not found in world data."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # State machine
        if self.state == FightState.INIT:
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
                    self.state = FightState.COMPLETE
                    return TaskResult(
                        completed=True,
                        character=context.character,
                        log_messages=[
                            (f"Already have {total_available}/{self.target_quantity} {self.drop_code} (inventory: {inventory_count}, bank: {bank_count})", "INFO"),
                            ("Fighting task skipped - sufficient drops available", "INFO")
                        ]
                    )

                # Reduce target quantity by what we already have
                if total_available > 0:
                    self.target_quantity = max(0, self.target_quantity - total_available)
                    self.collected_quantity = total_available
                    log_msg = f"Found {total_available} {self.drop_code} (inventory: {inventory_count}, bank: {bank_count}). Need {self.target_quantity} more"
                else:
                    log_msg = f"No existing {self.drop_code} found. Fighting for {self.target_quantity}"

                self.state = FightState.CHECKING_FOOD
                return TaskResult(
                    completed=False,
                    character=context.character,
                    log_messages=[(log_msg, "INFO")]
                )
            else:
                # Non-prunable mode: skip directly to food check
                self.state = FightState.CHECKING_FOOD
                return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.CHECKING_FOOD:
            # Check bank for food items (priority: cooked_gudgeon > cooked_chicken)
            if context.bank:
                for food in ["cooked_gudgeon", "cooked_chicken"]:
                    check_result: CheckItemResponse = await context.bank.ask(
                        CheckItemMessage(code=food, quantity=50)
                    )

                    if check_result.available:
                        # Reserve the food
                        reserve_qty = min(50, check_result.free)
                        reserve_result: ReserveItemResponse = await context.bank.ask(
                            ReserveItemMessage(code=food, quantity=reserve_qty, bot_name=name)
                        )

                        if reserve_result.success:
                            self.food_code = food
                            self.food_reservation_id = reserve_result.reservation_id
                            self.state = FightState.MOVING_TO_BANK
                            return TaskResult(
                                completed=False,
                                character=context.character,
                                log_messages=[(f"Reserved {food} x{reserve_qty} from bank", "INFO")]
                            )

            # No food found or no bank access, skip to fighting
            self.state = FightState.MOVING_TO_MONSTER
            return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.MOVING_TO_BANK:
            # Move to bank location (4, 1)
            BANK_X, BANK_Y = 4, 1
            current_pos = context.character.position

            if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
                try:
                    result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to bank at ({BANK_X}, {BANK_Y})", "INFO")],
                    )
                except APIError:
                    # Release reservation on error
                    await self._release_reservation(context)
                    self.state = FightState.MOVING_TO_MONSTER
                    return TaskResult(completed=False, character=context.character)

            self.state = FightState.WITHDRAWING_FOOD
            return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.WITHDRAWING_FOOD:
            # Withdraw food from bank
            try:
                withdraw_qty = 50  # Withdraw up to 50
                result = await context.api.withdraw_item(
                    items=[{"code": self.food_code, "quantity": withdraw_qty}],
                    name=name
                )

                # Notify BankActor of withdrawal
                if context.bank and self.food_reservation_id:
                    await context.bank.tell(
                        UpdateAfterWithdrawMessage(
                            reservation_id=self.food_reservation_id,
                            actual_quantity=withdraw_qty
                        )
                    )
                    self.food_reservation_id = None

                self.state = FightState.MOVING_TO_MONSTER
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Withdrew {self.food_code} x{withdraw_qty}", "INFO")]
                )

            except APIError:
                # Release reservation and continue without food
                await self._release_reservation(context)
                self.state = FightState.MOVING_TO_MONSTER
                return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.MOVING_TO_MONSTER:
            # Find monster location
            location = context.world.gathering_location(self.monster_code)
            if not location:
                error = FatalError(
                    code=1000,
                    message=f"Monster '{self.monster_code}' location not found."
                )
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=error,
                    log_messages=[(str(error), "ERROR")],
                )

            target_x, target_y = location
            current_pos = context.character.position

            # Move to the monster
            if (current_pos.x, current_pos.y) != (target_x, target_y):
                try:
                    result = await context.api.move(x=target_x, y=target_y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to {monster.name} at ({target_x}, {target_y})", "INFO")],
                    )
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            self.state = FightState.HEALING
            return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.HEALING:
            # Check HP and heal if needed
            hp = context.character.stats.hp
            max_hp = context.character.stats.max_hp

            # Use consumable if HP is low and we have food
            if hp <= self.hp_threshold and self.food_code:
                # Check if we have the food in inventory
                food_in_inv = next(
                    (item for item in context.character.inventory if item.code == self.food_code),
                    None
                )

                if food_in_inv and food_in_inv.quantity > 0:
                    try:
                        result = await context.api.use_item(
                            item_code=self.food_code,
                            quantity=1,
                            name=name
                        )
                        # Stay in healing state to check HP again
                        return TaskResult(
                            completed=False,
                            character=result.character,
                            log_messages=[(f"Used {self.food_code} to heal (HP: {hp}/{max_hp})", "INFO")],
                        )
                    except APIError:
                        # If healing fails, fall back to resting
                        pass

            # Rest if HP is low and no food or food failed
            if hp <= self.hp_threshold:
                try:
                    result = await context.api.rest(name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Resting to recover HP ({hp}/{max_hp})", "INFO")],
                    )
                except APIError as e:
                    return TaskResult(completed=False, character=context.character, error=e)

            # HP is good, proceed to fighting
            self.state = FightState.FIGHTING
            return TaskResult(completed=False, character=context.character)

        elif self.state == FightState.FIGHTING:
            try:
                result = await context.api.fight(name=name)
                self.kills += 1

                fight_result = result.fight.result  # "win" or "lose"

                # Get character-specific fight results (for solo, there's only one)
                char_result = result.fight.characters[0] if result.fight.characters else None
                xp_gained = char_result.xp if char_result else 0
                gold_gained = char_result.gold if char_result else 0

                # Track drops of the target item
                drops_of_target = 0
                if char_result and char_result.drops:
                    for drop in char_result.drops:
                        if drop.code == self.drop_code:
                            drops_of_target += drop.quantity
                            self.collected_quantity += drop.quantity

                items_dropped = [f"{drop.code} x{drop.quantity}" for drop in char_result.drops] if char_result else []
                items_str = ", ".join(items_dropped) if items_dropped else "nothing"

                # Get updated character state
                character = result.characters[0] if result.characters else context.character

                # Check if we've collected enough of the target drop
                completed = self.collected_quantity >= self.target_quantity

                log_messages = [
                    (f"Fight {fight_result}! XP: +{xp_gained}, Gold: +{gold_gained}, Drops: {items_str}", "INFO")
                ]

                if drops_of_target > 0:
                    log_messages.append((f"Collected {self.drop_code} x{drops_of_target} ({self.collected_quantity}/{self.target_quantity}) after {self.kills} kills", "INFO"))

                if completed:
                    log_messages.append((f"Collected enough {self.drop_code} after {self.kills} kills!", "INFO"))
                    self.state = FightState.COMPLETE
                else:
                    # Go back to healing state to check HP before next fight
                    self.state = FightState.HEALING

                return TaskResult(
                    completed=completed,
                    character=character,
                    log_messages=log_messages,
                )
            except APIError as e:
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=e,
                    log_messages=[(f"Fight failed: {e.message}", level)]
                )

        # Should not reach here
        return TaskResult(
            completed=True,
            character=context.character,
            log_messages=[("Fight until drop task completed", "INFO")]
        )

    async def _release_reservation(self, context: TaskContext):
        """Release food reservation on error (best effort)"""
        if not self.food_reservation_id or not context.bank:
            return

        try:
            await context.bank.tell(
                ReleaseReservationMessage(reservation_id=self.food_reservation_id)
            )
            self.food_reservation_id = None
        except Exception:
            pass

    def progress(self) -> str:
        if self.state in {FightState.INIT}:
            return "Checking availability"
        elif self.state == FightState.CHECKING_FOOD:
            return "Preparing"
        elif self.state in {FightState.MOVING_TO_BANK, FightState.WITHDRAWING_FOOD}:
            return "Getting supplies"
        elif self.state == FightState.MOVING_TO_MONSTER:
            return "Traveling"
        elif self.state == FightState.HEALING:
            return "Healing"
        elif self.state == FightState.FIGHTING:
            return f"{self.collected_quantity}/{self.target_quantity} ({self.kills} kills)"
        else:
            return "Complete"

    def description(self) -> str:
        monster = self.monster_code.replace("_", " ").title()
        drop = self.drop_code.replace("_", " ").title()
        # Use original target for description to show the initial requirement
        display_amount = self.original_target if self.original_target > 0 else self.target_quantity
        return f"Fight {monster} for {drop} x{display_amount}"
