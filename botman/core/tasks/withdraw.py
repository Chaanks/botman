from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError


class WithdrawState(str, Enum):
    """States for withdraw task state machine"""
    INIT = "init"
    MOVING_TO_BANK = "moving_to_bank"
    RESERVING = "reserving"
    WITHDRAWING = "withdrawing"
    COMPLETE = "complete"


@dataclass
class WithdrawTask(Task):
    """
    Withdraw items from the bank with reservation system.

    The task will:
    1. Check item availability in bank (via BankActor)
    2. Reserve the items to prevent concurrent withdrawals
    3. Move to bank location
    4. Withdraw the items
    5. Update BankActor state with actual withdrawn quantity
    6. Reservation automatically removed on update

    Modes:
    - Single item: Provide item_code and quantity
    - Multiple items: Provide items list [{"code": "ash", "quantity": 10}, ...]
    """
    item_code: Optional[str] = None
    quantity: Optional[int] = None
    items: Optional[List[Dict[str, any]]] = None

    # Internal state
    state: WithdrawState = field(default=WithdrawState.INIT, init=False, repr=False)
    # Track reservations: item_code -> reservation_id
    reservations: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        """Validate configuration"""
        modes = sum([
            bool(self.item_code and self.quantity),
            bool(self.items),
        ])
        if modes == 0:
            raise ValueError("Must specify either item_code+quantity or items list")
        if modes > 1:
            raise ValueError("Can only specify one withdraw mode at a time")

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        current_pos = context.character.position

        # Bank is typically at (4, 1)
        BANK_X, BANK_Y = 4, 1

        # Prepare items list
        if self.items:
            items_to_withdraw = self.items
        else:
            items_to_withdraw = [{"code": self.item_code, "quantity": self.quantity}]

        # State machine
        if self.state == WithdrawState.INIT:
            # Check availability and reserve items
            if not context.bank:
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=FatalError(0, "BankActor not available"),
                    log_messages=[("BankActor not available for withdraw", "ERROR")]
                )

            # Check and reserve each item
            for item in items_to_withdraw:
                item_code = item['code']
                qty = item['quantity']

                # Check availability
                check_result = await context.bank.ask({
                    'type': 'check_item',
                    'code': item_code,
                    'quantity': qty
                })

                if not check_result.get('available'):
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=FatalError(0, f"Insufficient {item_code} in bank"),
                        log_messages=[(
                            f"Cannot withdraw {item_code} x{qty}: only {check_result.get('free', 0)} available "
                            f"(total: {check_result.get('total_in_bank', 0)}, reserved: {check_result.get('reserved', 0)})",
                            "ERROR"
                        )]
                    )

                # Reserve the item
                reserve_result = await context.bank.ask({
                    'type': 'reserve_item',
                    'code': item_code,
                    'quantity': qty,
                    'bot_name': name
                })

                if not reserve_result.get('success'):
                    # Release any reservations made so far
                    await self._release_all_reservations(context)
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=FatalError(0, f"Failed to reserve {item_code}"),
                        log_messages=[(f"Reservation failed: {reserve_result.get('error', 'Unknown error')}", "ERROR")]
                    )

                # Store reservation ID
                self.reservations[item_code] = reserve_result['reservation_id']

            self.state = WithdrawState.MOVING_TO_BANK

            return TaskResult(
                completed=False,
                character=context.character,
                log_messages=[("Items reserved in bank", "INFO")]
            )

        elif self.state == WithdrawState.MOVING_TO_BANK:
            # Move to bank if not already there
            if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
                try:
                    result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                    return TaskResult(
                        completed=False,
                        character=result.character,
                        log_messages=[(f"Moving to bank at ({BANK_X}, {BANK_Y})", "INFO")],
                    )
                except APIError as e:
                    # Release reservations on error
                    await self._release_all_reservations(context)
                    return TaskResult(
                        completed=False,
                        character=context.character,
                        error=e,
                        log_messages=[(f"Failed to move to bank: {e.message}", "ERROR")]
                    )

            self.state = WithdrawState.WITHDRAWING
            return TaskResult(completed=False, character=context.character)

        elif self.state == WithdrawState.WITHDRAWING:
            # Withdraw items
            try:
                result = await context.api.withdraw_item(items=items_to_withdraw, name=name)

                # Notify BankActor of withdrawal with actual quantities
                # (this also removes reservation automatically)
                if context.bank:
                    for item in items_to_withdraw:
                        item_code = item['code']
                        requested_qty = item['quantity']

                        # Find actual quantity from result
                        # The API returns items actually withdrawn in result.items
                        actual_qty = requested_qty  # Default to requested

                        # Try to get actual from API response
                        if hasattr(result, 'items') and result.items:
                            for withdrawn_item in result.items:
                                if withdrawn_item.code == item_code:
                                    actual_qty = withdrawn_item.quantity
                                    break

                        # Get reservation ID for this item
                        reservation_id = self.reservations.get(item_code)
                        if reservation_id:
                            await context.bank.tell({
                                'type': 'update_after_withdraw',
                                'reservation_id': reservation_id,
                                'actual_quantity': actual_qty
                            })

                # Clear reservation tracking
                self.reservations.clear()

                # Build log message
                if len(items_to_withdraw) == 1:
                    item = items_to_withdraw[0]
                    log_msg = f"Withdrew {item['code']} x{item['quantity']} from bank"
                else:
                    total_items = sum(item['quantity'] for item in items_to_withdraw)
                    log_msg = f"Withdrew {len(items_to_withdraw)} item types ({total_items} items) from bank"

                self.state = WithdrawState.COMPLETE
                return TaskResult(
                    completed=True,
                    character=result.character,
                    log_messages=[(log_msg, "INFO"), ("Withdraw complete!", "INFO")]
                )

            except APIError as e:
                # Release reservations on error
                await self._release_all_reservations(context)
                level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=e,
                    log_messages=[(f"Withdraw failed: {e.message}", level)]
                )

        # Shouldn't reach here
        return TaskResult(
            completed=True,
            character=context.character,
            log_messages=[("Withdraw task completed", "INFO")]
        )

    async def _release_all_reservations(self, context: TaskContext):
        """Release all reservations on error (best effort)"""
        if not self.reservations or not context.bank:
            return

        for item_code, reservation_id in list(self.reservations.items()):
            try:
                await context.bank.tell({
                    'type': 'release_reservation',
                    'reservation_id': reservation_id
                })
            except Exception:
                pass  # Best effort

        self.reservations.clear()

    def progress(self) -> str:
        """Return progress indicator"""
        if self.state == WithdrawState.INIT:
            return "Checking availability"
        elif self.state == WithdrawState.MOVING_TO_BANK:
            return "Moving to bank"
        elif self.state == WithdrawState.WITHDRAWING:
            return "Withdrawing"
        else:
            return "Complete"

    def description(self) -> str:
        """Return human-readable task description"""
        if self.items:
            item_count = len(self.items)
            total_qty = sum(item.get("quantity", 0) for item in self.items)
            return f"Withdraw {item_count} Item Types ({total_qty} total)"
        else:
            item_name = self.item_code.replace("_", " ").title()
            return f"Withdraw {item_name} x{self.quantity}"
